"""Repo-wide pytest setup, shared by `tests/` and every module's `__tests__/`."""

from __future__ import annotations

import sys

import pytest
from tenacity import BaseRetrying, wait_none

from maple_data_mcp.shared.rate_limiter import TokenBucket


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop tenacity's exponential backoff so retry tests don't really sleep.

    Retry *counts* and retryable-status rules stay exactly as in
    production -- only the 1s/2s waits between attempts are removed.
    Without this, every "upstream 5xx" test sleeps ~3s, which made the
    mocked suite take ~8 minutes. Scans already-imported project modules
    for tenacity-decorated functions (their `.retry` attribute is the
    shared `BaseRetrying` each call copies its settings from).
    """
    for name, module in list(sys.modules.items()):
        if not name.startswith("maple_data_mcp") or module is None:
            continue
        for attr in vars(module).values():
            retrying = getattr(attr, "retry", None)
            if isinstance(retrying, BaseRetrying):
                monkeypatch.setattr(retrying, "wait", wait_none())


@pytest.fixture(autouse=True)
def _no_rate_limit_waits(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make per-source token buckets non-blocking outside their own tests.

    Buckets are process-wide singletons (1-3 req/s), so mocked tests that
    fire many requests otherwise spend most of their runtime sleeping on
    tokens other tests already spent. test_shared_rate_limiter still
    exercises the real bucket.
    """
    if request.module.__name__.endswith("test_shared_rate_limiter"):
        return

    async def acquire(self: TokenBucket) -> None:
        return None

    monkeypatch.setattr(TokenBucket, "acquire", acquire)
