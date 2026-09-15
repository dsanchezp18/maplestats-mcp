"""Process-local TTL cache shared by every module.

In-memory only (aiocache.SimpleMemoryCache). Not shared across worker
processes — fine for a single uvicorn worker; note this explicitly if
the hosted deployment ever scales to multiple workers, since a cache
hit in one worker is a miss in another.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiocache import SimpleMemoryCache

_cache = SimpleMemoryCache()


async def cached_fetch(
    key: str,
    ttl: int,
    fetcher: Callable[[], Awaitable[Any]],
) -> tuple[Any, bool]:
    """Return (data, was_cached). Only successful fetches are cached.

    A fetcher that raises is never cached — a transient upstream failure
    should not poison the cache for the TTL window.
    """
    cached_value = await _cache.get(key)
    if cached_value is not None:
        return cached_value, True

    data = await fetcher()
    await _cache.set(key, data, ttl=ttl)
    return data, False
