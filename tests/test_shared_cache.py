from __future__ import annotations

from maple_data_mcp.shared.cache import cached_fetch


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
