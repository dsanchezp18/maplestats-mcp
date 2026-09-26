from __future__ import annotations

import asyncio

import pytest

from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.http import recording


async def test_cached_fetch_calls_fetcher_once_on_repeat_calls():
    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        return {"n": calls}

    data1, cached1 = await cached_fetch("shared-cache-test-key", ttl=60, fetcher=fetcher)
    data2, cached2 = await cached_fetch("shared-cache-test-key", ttl=60, fetcher=fetcher)

    assert cached1 is False
    assert cached2 is True
    assert data1 == data2 == {"n": 1}
    assert calls == 1


async def test_cached_fetch_does_not_cache_a_failed_fetch():
    calls = 0

    async def flaky_fetcher():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("transient")
        return "ok"

    try:
        await cached_fetch("shared-cache-flaky-key", ttl=60, fetcher=flaky_fetcher)
    except ValueError:
        pass

    data, was_cached = await cached_fetch("shared-cache-flaky-key", ttl=60, fetcher=flaky_fetcher)
    assert data == "ok"
    assert was_cached is False
    assert calls == 2


async def test_cache_bucket_is_bounded_by_max_entries(monkeypatch):
    """Some cache keys (e.g. WDS's getDataFromVectorsAndLatestNPeriods,
    keyed on an arbitrary list of vector ids) encode an effectively
    unbounded combination of caller input rather than a small, reused
    resource id — the per-ttl bucket must cap total entries rather than
    growing forever as new combinations are queried."""
    monkeypatch.setattr(cache_module.config, "get_cache_max_entries", lambda: 3)

    async def fetcher():
        return "value"

    # A ttl unused by any other test/module, so this exercises a fresh bucket.
    unique_ttl = 3600123
    for i in range(10):
        await cached_fetch(f"bounded-test-key-{i}", ttl=unique_ttl, fetcher=fetcher)

    assert len(cache_module._caches[unique_ttl]) <= 3


async def test_concurrent_misses_share_one_fetch():
    calls = 0
    release = asyncio.Event()

    async def slow_fetcher():
        nonlocal calls
        calls += 1
        await release.wait()
        return {"n": calls}

    tasks = [
        asyncio.create_task(cached_fetch("single-flight-key", ttl=60, fetcher=slow_fetcher))
        for _ in range(5)
    ]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert all(data is results[0][0] for data, _ in results)
    assert not cache_module._inflight


async def test_concurrent_failure_reaches_every_waiter_and_is_not_cached():
    calls = 0
    release = asyncio.Event()

    async def failing_fetcher():
        nonlocal calls
        calls += 1
        await release.wait()
        raise ValueError("upstream down")

    tasks = [
        asyncio.create_task(cached_fetch("single-flight-fail", ttl=60, fetcher=failing_fetcher))
        for _ in range(3)
    ]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert calls == 1
    assert all(isinstance(r, ValueError) for r in results)
    assert not cache_module._inflight

    async def ok_fetcher():
        return "ok"

    assert await cached_fetch("single-flight-fail", ttl=60, fetcher=ok_fetcher) == ("ok", False)


async def test_cancelled_owner_does_not_strand_waiters():
    started = asyncio.Event()

    async def hanging_fetcher():
        started.set()
        await asyncio.Event().wait()

    owner = asyncio.create_task(
        cached_fetch("single-flight-cancel", ttl=60, fetcher=hanging_fetcher)
    )
    await started.wait()

    async def ok_fetcher():
        return "ok"

    waiter = asyncio.create_task(cached_fetch("single-flight-cancel", ttl=60, fetcher=ok_fetcher))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    # The waiter retries with its own fetcher rather than inheriting the
    # owner's cancellation.
    assert await waiter == ("ok", False)
    assert not cache_module._inflight


async def test_recording_reads_through_the_cache():
    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        return calls

    await cached_fetch("single-flight-recording", ttl=60, fetcher=fetcher)
    with recording():
        data, was_cached = await cached_fetch("single-flight-recording", ttl=60, fetcher=fetcher)
    assert (data, was_cached) == (2, False)
    assert calls == 2
