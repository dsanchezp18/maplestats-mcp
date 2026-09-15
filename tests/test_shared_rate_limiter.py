from __future__ import annotations

import time

from maple_data_mcp.shared.rate_limiter import TokenBucket, get_limiter


async def test_token_bucket_allows_burst_up_to_capacity():
    bucket = TokenBucket(rate=10.0, capacity=3.0)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


async def test_token_bucket_throttles_beyond_capacity():
    bucket = TokenBucket(rate=20.0, capacity=1.0)
    await bucket.acquire()
    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.03


def test_get_limiter_returns_same_instance_for_same_source():
    a = get_limiter("test-source-x", rate=5, capacity=5)
    b = get_limiter("test-source-x", rate=999, capacity=999)
    assert a is b
    assert a.rate == 5


def test_get_limiter_returns_different_instances_for_different_sources():
    a = get_limiter("test-source-y1", rate=5, capacity=5)
    b = get_limiter("test-source-y2", rate=5, capacity=5)
    assert a is not b
