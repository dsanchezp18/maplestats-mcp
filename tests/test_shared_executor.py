from __future__ import annotations

import threading
import time

import pytest

from maplestats_mcp import config
from maplestats_mcp.shared import executor, file_tables
from maplestats_mcp.shared.errors import UpstreamError


async def test_run_parse_uses_the_dedicated_pool():
    name = await executor.run_parse(lambda: threading.current_thread().name)
    assert name.startswith("maple-parse")


async def test_run_in_pool_passes_arguments():
    assert await executor.run_in_pool(lambda a, b=0: a + b, 2, b=3) == 5


async def test_pool_size_comes_from_config(monkeypatch):
    monkeypatch.setattr(executor, "_executor", None)
    monkeypatch.setenv("MAPLE_PARSE_WORKERS", "2")
    try:
        assert executor.get_executor()._max_workers == 2
    finally:
        executor.get_executor().shutdown(wait=False)
    monkeypatch.setattr(executor, "_executor", None)


def test_parse_config_bounds(monkeypatch):
    monkeypatch.delenv("MAPLE_PARSE_WORKERS", raising=False)
    monkeypatch.delenv("MAPLE_PARSE_TIMEOUT_SECONDS", raising=False)
    assert config.get_parse_workers() == 4
    assert config.get_parse_timeout_seconds() == 60.0
    monkeypatch.setenv("MAPLE_PARSE_WORKERS", "0")
    assert config.get_parse_workers() == 1


async def test_slow_parse_fails_at_the_budget_and_the_thread_stops(monkeypatch):
    monkeypatch.setattr(config, "get_parse_timeout_seconds", lambda: 0.2)
    stopped = threading.Event()

    def pathological() -> None:
        try:
            while True:
                executor.check_deadline()
                time.sleep(0.01)
        finally:
            stopped.set()

    started = time.monotonic()
    with pytest.raises(UpstreamError, match="longer than"):
        await executor.run_parse(pathological)
    assert time.monotonic() - started < 2
    # check_deadline() ends the worker too, so its slot is freed.
    assert stopped.wait(2)


async def test_csv_scan_honours_the_budget(monkeypatch):
    monkeypatch.setattr(config, "get_parse_timeout_seconds", lambda: 0.05)
    real_check = executor.check_deadline

    def slow_check() -> None:
        time.sleep(0.01)
        real_check()

    monkeypatch.setattr(file_tables, "check_deadline", slow_check)
    body = b"a,b,c\n" + b"1,2,3\n" * 50_000
    with pytest.raises(UpstreamError):
        await executor.run_parse(file_tables.describe, body, "csv", None)


def test_check_deadline_is_a_no_op_outside_the_pool():
    executor.check_deadline()
