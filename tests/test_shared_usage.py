"""Usage counts hold tool names and outcomes, never what a caller typed."""

from __future__ import annotations

import json
from collections import Counter

from fastmcp import Client
from fastmcp.tools import ToolResult

from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound
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
    for n in range(MAX_DAYS + 10):
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


async def test_a_tool_that_raises_is_counted_as_an_error() -> None:
    from fastmcp import FastMCP

    from maplestats_mcp.shared.usage import UsageMiddleware

    stats = UsageStats(("failing_tool",))
    server = FastMCP("t")
    server.add_middleware(UsageMiddleware(stats))

    @server.tool
    async def failing_tool() -> str:
        raise ValueError("upstream said no")

    async with Client(server) as client:
        await client.call_tool("failing_tool", {}, raise_on_error=False)
    assert stats.snapshot()["by_tool"] == {"failing_tool": {"ok": 0, "error": 1}}


async def test_a_result_flagged_as_an_error_is_counted_as_an_error() -> None:
    from fastmcp import FastMCP

    from maplestats_mcp.shared.usage import UsageMiddleware

    stats = UsageStats(("flagged_tool",))
    server = FastMCP("t")
    server.add_middleware(UsageMiddleware(stats))

    @server.tool
    async def flagged_tool() -> ToolResult:
        return ToolResult(content="refused", is_error=True)

    async with Client(server) as client:
        await client.call_tool("flagged_tool", {}, raise_on_error=False)
    assert stats.snapshot()["by_tool"] == {"flagged_tool": {"ok": 0, "error": 1}}


async def test_a_call_made_inside_a_tool_is_not_counted_again() -> None:
    from fastmcp import FastMCP

    from maplestats_mcp.shared.usage import UsageMiddleware

    stats = UsageStats(("outer_tool", "inner_tool"))
    server = FastMCP("t")
    server.add_middleware(UsageMiddleware(stats))

    @server.tool
    async def inner_tool() -> str:
        return "x"

    @server.tool
    async def outer_tool() -> str:
        async with Client(server) as inner:
            await inner.call_tool("inner_tool", {})
        return "y"

    async with Client(server) as client:
        await client.call_tool("outer_tool", {})
        await client.call_tool("inner_tool", {})
    snap = stats.snapshot()
    assert snap["by_tool"] == {
        "outer_tool": {"ok": 1, "error": 0},
        "inner_tool": {"ok": 1, "error": 0},
    }


# ---- MAPLE_USAGE_STATS_FILE: counts kept across restarts


def test_counts_survive_a_restart(tmp_path) -> None:
    path = tmp_path / "usage" / "stats.json"
    first = UsageStats(("boc_get_observations",), path=path)
    first.record("boc_get_observations", True)
    first.record("boc_get_observations", False)
    assert first.save()
    second = UsageStats(("boc_get_observations",), path=path)
    snap = second.snapshot()
    assert snap["calls"] == 2 and snap["errors"] == 1 and snap["persisted"] is True
    assert snap["counting_since"] == first.since.isoformat()
    second.record("boc_get_observations", True)
    assert second.save()
    assert UsageStats(path=path).snapshot()["by_tool"] == {
        "boc_get_observations": {"ok": 2, "error": 1}
    }


def test_two_processes_saving_to_one_file_add_up(tmp_path) -> None:
    # During a rollout the old and new revisions both count calls into one file.
    path = tmp_path / "stats.json"
    old = UsageStats(("wds_search_cubes",), path=path)
    old.record("wds_search_cubes", True)
    old.save()
    new = UsageStats(("wds_search_cubes",), path=path)
    old.record("wds_search_cubes", True)
    new.record("wds_search_cubes", True)
    old.save()
    new.save()
    assert new.snapshot()["calls"] == 3
    assert UsageStats(path=path).snapshot()["calls"] == 3


def test_saving_twice_does_not_count_twice(tmp_path) -> None:
    path = tmp_path / "stats.json"
    stats = UsageStats(("wds_search_cubes",), path=path)
    stats.record("wds_search_cubes", True)
    stats.save()
    stats.save()
    assert UsageStats(path=path).snapshot()["calls"] == 1


def test_a_bad_file_is_moved_aside_not_overwritten(tmp_path) -> None:
    path = tmp_path / "stats.json"
    path.write_text('{"version": 1, "by_tool": {"x": {"ok": -5, "error": 0}}}', encoding="utf-8")
    stats = UsageStats(("wds_search_cubes",), path=path)
    assert stats.snapshot()["calls"] == 0
    assert (tmp_path / "stats.json.bad").exists()
    stats.record("wds_search_cubes", True)
    assert stats.save()
    assert UsageStats(path=path).snapshot()["calls"] == 1


def test_a_failed_save_keeps_the_calls_for_the_next_one(tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    stats = UsageStats(("wds_search_cubes",), path=blocker / "stats.json")
    stats.record("wds_search_cubes", True)
    assert not stats.save()
    assert stats.snapshot()["calls"] == 1
    blocker.unlink()
    assert stats.save()
    assert UsageStats(path=blocker / "stats.json").snapshot()["calls"] == 1


def test_without_a_file_nothing_is_written(tmp_path) -> None:
    stats = UsageStats(("wds_search_cubes",))
    stats.record("wds_search_cubes", True)
    assert not stats.save()
    assert stats.snapshot()["persisted"] is False
    assert list(tmp_path.iterdir()) == []


async def test_the_http_app_saves_the_counts_at_shutdown() -> None:
    from maplestats_mcp.asgi import with_shutdown_save

    saved: list[bool] = []
    seen: list[str] = []

    async def inner(scope, receive, send):
        while True:
            message = await receive()
            seen.append(message["type"])
            if message["type"] == "lifespan.shutdown":
                return

    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):  # pragma: no cover - the inner app sends nothing
        pass

    app = with_shutdown_save(inner, lambda: saved.append(True))
    await app({"type": "lifespan"}, receive, send)
    assert saved == [True]
    assert seen == ["lifespan.startup", "lifespan.shutdown"]


def test_a_namespaced_name_counts_as_its_tool() -> None:
    stats = UsageStats(("wds_search_cubes",))
    stats.record("MapleStats.WDS_search_cubes", True)
    assert stats.snapshot()["by_tool"] == {"wds_search_cubes": {"ok": 1, "error": 0}}


def test_an_unreadable_file_is_never_overwritten(tmp_path, monkeypatch) -> None:
    # A transient read error on the Azure Files share must not let a save replace
    # the saved history with only the counts since the last save.
    path = tmp_path / "stats.json"
    first = UsageStats(("wds_search_cubes",), path=path)
    for _ in range(5):
        first.record("wds_search_cubes", True)
    assert first.save()
    stats = UsageStats(("wds_search_cubes",), path=path)
    stats.record("wds_search_cubes", True)
    real_read = type(path).read_text

    def flaky(self, *args, **kwargs):
        if self == path:
            raise OSError("transient SMB error")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", flaky)
    assert not stats.save()
    monkeypatch.setattr(type(path), "read_text", real_read)
    assert UsageStats(path=path).snapshot()["calls"] == 5
    assert stats.save()
    assert UsageStats(path=path).snapshot()["calls"] == 6


# ---- error codes: why calls fail, as a fixed list and never the message


def test_failures_are_counted_by_tool_and_code() -> None:
    stats = UsageStats(("boc_get_observations", "wds_search_cubes"))
    stats.record("boc_get_observations", False, code="not_found")
    stats.record("boc_get_observations", False, code="not_found")
    stats.record("boc_get_observations", False, code="invalid_input")
    stats.record("boc_get_observations", True)
    stats.record("wds_search_cubes", False)
    snap = stats.snapshot()
    assert snap["errors"] == 4
    assert snap["error_codes"] == {"not_found": 2, "invalid_input": 1, "error": 1}
    assert snap["by_error"] == {
        "boc_get_observations": {"not_found": 2, "invalid_input": 1},
        "wds_search_cubes": {"error": 1},
    }


def test_a_code_outside_the_fixed_list_is_never_stored() -> None:
    stats = UsageStats(("boc_get_observations",))
    stats.record("boc_get_observations", False, code="what is my neighbour's income?")
    snap = stats.snapshot()
    assert snap["by_error"] == {"boc_get_observations": {"error": 1}}
    assert "neighbour" not in json.dumps(snap)


async def _failures(error: Exception) -> dict[str, int]:
    from fastmcp import FastMCP

    from maplestats_mcp.shared.error_hints import ErrorHintMiddleware
    from maplestats_mcp.shared.usage import UsageMiddleware

    stats = UsageStats(("failing_tool",))
    server = FastMCP("t")
    # The order server.py uses: the hint middleware outside the counter.
    server.add_middleware(ErrorHintMiddleware())
    server.add_middleware(UsageMiddleware(stats))

    @server.tool
    async def failing_tool() -> str:
        raise error

    async with Client(server) as client:
        await client.call_tool("failing_tool", {}, raise_on_error=False)
    return stats.snapshot()["by_error"]["failing_tool"]


async def test_a_failing_tool_is_counted_under_its_error_class() -> None:
    assert await _failures(NotFound("no such series")) == {"not_found": 1}
    assert await _failures(InvalidInput("bad date")) == {"invalid_input": 1}
    assert await _failures(ValueError("odd")) == {"error": 1}


async def test_real_server_failures_get_the_code_the_client_reads() -> None:
    before = STATS.snapshot()["by_error"]
    async with Client(mcp) as client:
        # Arguments that fail the tool's schema, and a name that is no tool.
        await client.call_tool(
            "call_tool",
            {"name": "boc_get_observations", "arguments": {"series_names": "not a list"}},
            raise_on_error=False,
        )
        await client.call_tool(
            "call_tool",
            {"name": "private_identifier_in_code_test", "arguments": {}},
            raise_on_error=False,
        )
    after = STATS.snapshot()["by_error"]
    assert after["boc_get_observations"]["invalid_input"] == (
        before.get("boc_get_observations", {}).get("invalid_input", 0) + 1
    )
    assert after["other"]["unknown_tool"] == before.get("other", {}).get("unknown_tool", 0) + 1
    assert "private_identifier_in_code_test" not in json.dumps(STATS.snapshot())


async def test_a_result_flagged_as_an_error_is_coded_from_its_leading_bracket() -> None:
    from fastmcp import FastMCP

    from maplestats_mcp.shared.usage import UsageMiddleware

    stats = UsageStats(("coded_tool", "plain_tool"))
    server = FastMCP("t")
    server.add_middleware(UsageMiddleware(stats))

    @server.tool
    async def coded_tool() -> ToolResult:
        return ToolResult(content="[not_found] no such table", is_error=True)

    @server.tool
    async def plain_tool() -> ToolResult:
        return ToolResult(content="[made_up_by_a_tool] refused", is_error=True)

    async with Client(server) as client:
        await client.call_tool("coded_tool", {}, raise_on_error=False)
        await client.call_tool("plain_tool", {}, raise_on_error=False)
    assert stats.snapshot()["by_error"] == {
        "coded_tool": {"not_found": 1},
        "plain_tool": {"error": 1},
    }


def test_error_codes_survive_a_restart(tmp_path) -> None:
    path = tmp_path / "stats.json"
    first = UsageStats(("boc_get_observations",), path=path)
    first.record("boc_get_observations", False, code="not_found")
    assert first.save()
    second = UsageStats(("boc_get_observations",), path=path)
    second.record("boc_get_observations", False, code="not_found")
    second.record("boc_get_observations", False, code="invalid_input")
    assert second.save()
    snap = UsageStats(path=path).snapshot()
    assert snap["by_error"] == {"boc_get_observations": {"not_found": 2, "invalid_input": 1}}
    assert snap["error_codes"] == {"not_found": 2, "invalid_input": 1}


def test_a_file_from_before_error_codes_still_loads(tmp_path) -> None:
    path = tmp_path / "stats.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "counting_since": "2026-11-07T16:39:30+00:00",
                "by_tool": {"boc_get_observations": {"ok": 3, "error": 2}},
                "by_day": {"2026-11-07": {"ok": 3, "error": 2}},
            }
        ),
        encoding="utf-8",
    )
    stats = UsageStats(("boc_get_observations",), path=path)
    stats.record("boc_get_observations", False, code="not_found")
    snap = stats.snapshot()
    assert snap["errors"] == 3
    assert snap["error_codes"] == {"not_found": 1, "uncoded": 2}
    assert not (tmp_path / "stats.json.bad").exists()
    assert stats.save()
    assert UsageStats(path=path).snapshot()["by_error"] == {
        "boc_get_observations": {"not_found": 1}
    }
