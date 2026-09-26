"""Process-local, size-bounded TTL cache shared by every module.

In-memory only (cachetools.TTLCache). Not shared across worker
processes — fine for a single uvicorn worker; note this explicitly if
the hosted deployment ever scales to multiple workers, since a cache
hit in one worker is a miss in another.

Bounded by MAPLE_CACHE_MAX_ENTRIES (see config.py): some cache keys
encode an unbounded combination of caller input — WDS's
getDataFromVectorsAndLatestNPeriods keys off the full, arbitrary list
of vector IDs in one request, not a small, self-limiting resource id —
so an uncapped cache grows with usage diversity, not with time, on a
long-running hosted instance. cachetools.TTLCache evicts its
soonest-to-expire entry once a bucket's maxsize is reached, on top of
normal TTL expiry; the previous aiocache.SimpleMemoryCache had no size
cap at all.

cachetools.TTLCache fixes one ttl per cache instance rather than per
item, but this module's callers pass several different ttl values
(cube-list, cube-metadata, code-sets, observations, RDaaS...) — so one
TTLCache is created per distinct ttl value seen, each independently
bounded to MAPLE_CACHE_MAX_ENTRIES. The number of distinct ttl values
is small and fixed by the constants each module defines, so this stays
a handful of buckets in practice, not one per key.

Concurrent misses on the same (ttl, key) share one fetch ("single
flight"): without it, N identical requests arriving before the first
finished each hit the upstream, which for a slow, rate-limited source
turns one call into N and can trip its limit. Callers get the stored
object itself, not a copy (results can be large), so a caller must not
mutate what cached_fetch returns.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from cachetools import TTLCache

from maplestats_mcp import config
from maplestats_mcp.shared.http import is_recording

_caches: dict[int, TTLCache] = {}
_inflight: dict[tuple[int, str], asyncio.Future[Any]] = {}


def _cache_for_ttl(ttl: int) -> TTLCache:
    cache = _caches.get(ttl)
    if cache is None:
        cache = TTLCache(maxsize=config.get_cache_max_entries(), ttl=ttl)
        _caches[ttl] = cache
    return cache


async def cached_fetch(
    key: str,
    ttl: int,
    fetcher: Callable[[], Awaitable[Any]],
) -> tuple[Any, bool]:
    """Return (data, was_cached). Only successful fetches are cached.

    A fetcher that raises is never cached — a transient upstream failure
    should not poison the cache for the TTL window.
    """
    cache = _cache_for_ttl(ttl)
    # While reproduce_code records a tool's requests, a cache hit (or a
    # joined in-flight fetch) would hide them, so read through to the source.
    if is_recording():
        data = await fetcher()
        cache[key] = data
        return data, False

    flight_key = (ttl, key)
    while True:
        try:
            return cache[key], True
        except KeyError:
            pass
        pending = _inflight.get(flight_key)
        if pending is None:
            break
        # shield: a waiter being cancelled must not cancel the fetch the
        # other waiters share. A fetch cancelled with its owner leaves no
        # result, so loop and either find one cached or start a new fetch.
        try:
            return await asyncio.shield(pending), False
        except asyncio.CancelledError:
            if not pending.cancelled():
                raise

    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _inflight[flight_key] = future
    try:
        data = await fetcher()
    except asyncio.CancelledError:
        future.cancel()
        raise
    except BaseException as exc:
        future.set_exception(exc)
        # Mark it retrieved so asyncio doesn't log "exception never
        # retrieved" when no other caller was waiting; the owner re-raises.
        future.exception()
        raise
    else:
        cache[key] = data
        future.set_result(data)
        return data, False
    finally:
        _inflight.pop(flight_key, None)


def forget(key: str) -> None:
    """Drop `key` from every TTL bucket, e.g. a result found to be partial."""
    for cache in _caches.values():
        cache.pop(key, None)
