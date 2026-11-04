"""Forwarded counts carry a registry tool name, the instance and the outcome, nothing a caller typed."""

from __future__ import annotations

import json

import httpx
import pytest

from maplestats_mcp import config
from maplestats_mcp.shared import goatcounter
from maplestats_mcp.shared.goatcounter import GoatCounterForwarder
from maplestats_mcp.shared.usage import UsageStats


def _recorder(status: int = 200) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={})

    return seen, httpx.MockTransport(handler)


async def test_batches_events_with_the_token_and_no_sessions() -> None:
    seen, transport = _recorder()
    forwarder = GoatCounterForwarder("https://example.goatcounter.com", "tok", "azure", transport)
    stats = UsageStats(("boc_get_observations",), forwarder=forwarder)
    stats.record("boc_get_observations", True)
    stats.record("boc_get_observations", False)
    stats.record("what is my neighbour's income?", True)
    assert await forwarder.flush() == 3
    [request] = seen
    assert str(request.url) == "https://example.goatcounter.com/api/v0/count"
    assert request.headers["Authorization"] == "Bearer tok"
    body = json.loads(request.content)
    assert body["no_sessions"] is True
    assert [hit["path"] for hit in body["hits"]] == [
        "mcp/azure/boc_get_observations",
        "mcp/azure/boc_get_observations/error",
        "mcp/azure/other",
    ]
    assert all(hit["event"] is True for hit in body["hits"])
    assert "neighbour" not in request.content.decode()
    assert forwarder.queue == []


async def test_more_than_a_batch_is_split() -> None:
    seen, transport = _recorder()
    forwarder = GoatCounterForwarder("https://example.goatcounter.com", "tok", "render", transport)
    for _ in range(goatcounter.BATCH_SIZE + 5):
        forwarder.add("wds_search_cubes", True)
    assert await forwarder.flush() == goatcounter.BATCH_SIZE + 5
    assert [len(json.loads(r.content)["hits"]) for r in seen] == [goatcounter.BATCH_SIZE, 5]


async def test_a_failed_batch_is_dropped_not_retried() -> None:
    seen, transport = _recorder(status=500)
    forwarder = GoatCounterForwarder("https://example.goatcounter.com", "tok", "azure", transport)
    forwarder.add("wds_search_cubes", True)
    assert await forwarder.flush() == 0
    assert forwarder.queue == [] and len(seen) == 1
    assert await forwarder.flush() == 0 and len(seen) == 1


def test_the_queue_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(goatcounter, "MAX_QUEUED", 3)
    forwarder = GoatCounterForwarder("https://example.goatcounter.com", "tok", "azure")
    for _ in range(5):
        forwarder.add("wds_search_cubes", True)
    assert len(forwarder.queue) == 3 and forwarder.dropped == 2


def test_off_without_url_and_token() -> None:
    forwarder = GoatCounterForwarder(None, "tok", "azure")
    forwarder.add("wds_search_cubes", True)
    assert not forwarder.enabled and forwarder.queue == []


def test_config_accepts_only_https_and_cleans_the_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPLE_GOATCOUNTER_URL", "http://example.goatcounter.com")
    assert config.get_goatcounter_url() is None
    monkeypatch.setenv("MAPLE_GOATCOUNTER_URL", "https://example.goatcounter.com/")
    assert config.get_goatcounter_url() == "https://example.goatcounter.com"
    monkeypatch.setenv("MAPLE_INSTANCE_NAME", "Azure/Canada Central!")
    assert config.get_instance_name() == "azurecanadacentral"
    monkeypatch.delenv("MAPLE_INSTANCE_NAME")
    assert config.get_instance_name() == "server"
