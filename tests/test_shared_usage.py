"""Usage counts hold tool names and outcomes, never what a caller typed."""

from __future__ import annotations

import json
from collections import Counter

from fastmcp import Client

from maplestats_mcp.server import mcp
from maplestats_mcp.shared.security import with_stats_endpoint
from maplestats_mcp.shared.usage import MAX_DAYS, STATS, UsageStats


def test_counts_by_tool_day_and_outcome() -> None:
    stats = UsageStats(("boc_get_observations", "wds_search_cubes"))
    stats.record("boc_get_observations", True)
    stats.record("boc_get_observations", False)
    stats.record("wds_search_cubes", True)
    snap = stats.snapshot()
    assert snap["calls"] == 3 and snap["errors"] == 1
    assert snap["by_tool"]["boc_get_observations"] == {"ok": 1, "error": 1}
    assert next(iter(snap["by_tool"])) == "boc_get_observations"
    assert sum(day["ok"] + day["error"] for day in snap["by_day"].values()) == 3


def test_caller_text_is_never_stored() -> None:
    stats = UsageStats(("boc_get_observations", "wds_search_cubes"))
    stats.record("what is my neighbour's income?", True)
    stats.record("x" * 500, True)
    assert list(stats.snapshot()["by_tool"]) == ["other"]
    assert "neighbour" not in json.dumps(stats.snapshot())


def test_old_days_are_dropped() -> None:
    stats = UsageStats(("boc_get_observations", "wds_search_cubes"))
    for n in range(100):
        stats.days[f"2020-01-01-{n:03d}"] = Counter({True: 1})
    stats.record("boc_get_observations", True)
    assert len(stats.days) == MAX_DAYS


async def test_call_tool_counts_its_target_not_its_arguments() -> None:
    before = STATS.snapshot()["calls"]
    async with Client(mcp) as client:
        await client.call_tool("search_tools", {"query": "private words that must not be stored"})
    snap = STATS.snapshot()
    assert snap["calls"] == before + 1
    assert "private words" not in json.dumps(snap)


async def test_stats_route_serves_the_snapshot() -> None:
    sent: list[dict] = []

    async def inner(scope, receive, send):  # pragma: no cover - must not be reached
        raise AssertionError("/stats should be answered by the stats route")

    async def receive():  # pragma: no cover - the route never reads the body
        return {}

    async def send(message):
        sent.append(message)

    app = with_stats_endpoint(inner, snapshot=lambda: {"calls": 7})
    await app({"type": "http", "path": "/stats", "method": "GET"}, receive, send)
    assert sent[0]["status"] == 200
    assert json.loads(sent[1]["body"]) == {"calls": 7}


async def test_unknown_tool_name_is_never_published():
    marker = "private_identifier_in_unknown_tool"
    async with Client(mcp) as client:
        await client.call_tool("call_tool", {"name": marker, "arguments": {}}, raise_on_error=False)
    assert marker not in json.dumps(STATS.snapshot())
    assert "other" in STATS.snapshot()["by_tool"]


def test_names_with_valid_spelling_still_need_registration():
    stats = UsageStats(("boc_get_observations",))
    for n in range(100):
        stats.record(f"private_name_{n}", False)
    assert stats.snapshot()["by_tool"] == {"other": {"ok": 0, "error": 100}}
