"""The server-wide response budget and the fitness caveats it adds to provenance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel

from maplestats_mcp.server import mcp
from maplestats_mcp.shared import response_budget
from maplestats_mcp.shared.limits import json_size, response_max_bytes, trim_payload
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.response_budget import ResponseBudgetMiddleware, apply_budget


def _provenance(limits: str | None = None) -> dict[str, Any]:
    return Provenance(
        source="test",
        url="https://example.org",
        queried_at=datetime(2026, 1, 1, tzinfo=UTC),
        cached=False,
        schema_name="test.Rows",
        limits=limits,
    ).model_dump(mode="json")


def _rows(n: int, width: int = 100) -> list[dict[str, Any]]:
    return [{"id": i, "text": "x" * width} for i in range(n)]


def _result(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
    )


@pytest.fixture
def no_rules(monkeypatch):
    monkeypatch.setattr(response_budget, "_notes_loaded", True)
    monkeypatch.setattr(response_budget, "_notes_for", None)


def test_trim_keeps_a_prefix_of_the_largest_list_within_budget():
    payload = {"rows": _rows(2_000), "tags": ["a", "b"], "returned_count": 2_000}
    trimmed = trim_payload(payload, 50_000)
    assert json_size(payload) <= 50_000
    assert [t.pattern for t in trimmed] == ["rows"]
    assert trimmed[0].total == 2_000 and trimmed[0].kept == len(payload["rows"])
    assert payload["rows"][0]["id"] == 0  # a prefix
    assert payload["tags"] == ["a", "b"]
    assert payload["returned_count"] == len(payload["rows"])  # the count follows the rows


def test_payload_within_budget_is_untouched():
    payload = {"rows": _rows(10)}
    before = json.dumps(payload)
    assert trim_payload(payload, 50_000) == []
    assert json.dumps(payload) == before


def test_each_series_keeps_its_most_recent_observations():
    # Three series of ascending observations: every series stays, each loses its
    # oldest rows, not the third series as a whole.
    series = [
        {
            "vector_id": v,
            "observations": [
                {"ref_period": f"{1900 + i}-01-01", "value": i, "pad": "x" * 60}
                for i in range(1_000)
            ],
        }
        for v in range(3)
    ]
    payload = {"series": series}
    trimmed = trim_payload(payload, 60_000)
    assert len(payload["series"]) == 3
    assert trimmed[0].pattern == "series[*].observations" and trimmed[0].latest
    for item in payload["series"]:
        assert item["observations"][-1]["ref_period"] == "2899-01-01"
        assert len(item["observations"]) < 1_000
    assert json_size(payload) <= 60_000


def test_a_small_list_in_the_group_is_cut_last():
    payload = {
        "dimensions": [
            {"name": "geo", "members": _rows(1_000)},
            {"name": "sex", "members": _rows(3)},
        ]
    }
    trim_payload(payload, 40_000)
    assert len(payload["dimensions"][1]["members"]) == 3
    assert len(payload["dimensions"][0]["members"]) < 1_000


def test_geometry_is_never_cut():
    ring = [[float(i), float(i)] for i in range(5_000)]
    payload = {"features": [{"geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    assert trim_payload(payload, 20_000) == []
    assert len(payload["features"][0]["geometry"]["coordinates"][0]) == 5_000


def test_budget_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAPLE_RESPONSE_MAX_BYTES", "150000")
    assert response_max_bytes() == 150_000
    monkeypatch.setenv("MAPLE_RESPONSE_MAX_BYTES", "junk")
    assert response_max_bytes() == 200_000
    monkeypatch.setenv("MAPLE_RESPONSE_MAX_BYTES", "5")
    assert response_max_bytes() == 10_000


def test_trimmed_result_says_so_and_text_matches_structured(no_rules):
    payload = {"rows": _rows(3_000), "provenance": _provenance("rows capped at 3,000")}
    out = apply_budget(_result(payload), "demo_tool", {"lang": "en"}, 50_000)
    text = out.content[0].text  # type: ignore[union-attr]
    assert len(text.encode()) <= 50_000
    assert json.loads(text) == out.structured_content
    limits = out.structured_content["provenance"]["limits"]  # type: ignore[index]
    assert limits.startswith("rows capped at 3,000. Trimmed to fit")
    assert "of 3,000 items in `rows`" in limits and "reproduce_code" in limits


def test_french_note(no_rules):
    payload = {"rows": _rows(3_000), "provenance": _provenance()}
    out = apply_budget(_result(payload), "demo_tool", {"lang": "fr"}, 50_000)
    limits = out.structured_content["provenance"]["limits"]  # type: ignore[index]
    assert limits.startswith("Réponse réduite au budget de 50")
    assert "sur 3" in limits and "premiers éléments" in limits


def test_untouched_result_is_the_same_object(no_rules):
    result = _result({"rows": _rows(5), "provenance": _provenance()})
    assert apply_budget(result, "demo_tool", {}, 50_000) is result


def test_caveats_are_filled_from_the_rules(monkeypatch):
    seen: list[tuple[str, dict[str, Any], str]] = []

    def notes_for(tool, arguments, lang):
        seen.append((tool, dict(arguments), lang))
        return ["Survey estimate: mind the sampling error."]

    monkeypatch.setattr(response_budget, "_notes_loaded", True)
    monkeypatch.setattr(response_budget, "_notes_for", notes_for)
    result = _result({"rows": _rows(5), "provenance": _provenance()})
    out = apply_budget(result, "wds_get_data_from_vectors", {"lang": "fr", "latest_n": 3}, 50_000)
    assert seen == [("wds_get_data_from_vectors", {"lang": "fr", "latest_n": 3}, "fr")]
    caveats = out.structured_content["provenance"]["caveats"]  # type: ignore[index]
    assert caveats == ["Survey estimate: mind the sampling error."]
    assert json.loads(out.content[0].text) == out.structured_content  # type: ignore[union-attr]


def test_a_broken_rule_does_not_fail_the_call(monkeypatch):
    def notes_for(tool, arguments, lang):
        raise RuntimeError("bad rule")

    monkeypatch.setattr(response_budget, "_notes_loaded", True)
    monkeypatch.setattr(response_budget, "_notes_for", notes_for)
    result = _result({"rows": _rows(5), "provenance": _provenance()})
    assert apply_budget(result, "demo_tool", {}, 50_000) is result


def test_missing_rules_module_means_no_caveats(monkeypatch):
    monkeypatch.setattr(response_budget, "_notes_loaded", False)
    monkeypatch.setattr(response_budget, "_notes_for", None)

    def missing(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(response_budget.importlib, "import_module", missing)
    assert response_budget.caveats_for("demo_tool", {}, "en") == []


def test_error_and_non_text_results_pass_through(no_rules):
    error = ToolResult(
        content=[TextContent(type="text", text="x" * 100_000)],
        structured_content={"rows": _rows(2_000)},
        is_error=True,
    )
    assert apply_budget(error, "demo_tool", {}, 50_000) is error


# Through a server ---------------------------------------------------------------


class _Rows(BaseModel):
    rows: list[dict[str, Any]]
    returned_count: int
    provenance: Provenance


def _server() -> FastMCP:
    server = FastMCP("budget-test")
    server.add_middleware(ResponseBudgetMiddleware(max_bytes=30_000))

    @server.tool
    def big(n: int = 2_000) -> _Rows:
        rows = _rows(n)
        return _Rows(
            rows=rows,
            returned_count=len(rows),
            provenance=Provenance.model_validate(_provenance()),
        )

    @server.tool
    async def nested() -> int:
        # An in-process call made while a tool runs (as reproduce_workbook does)
        # gets every row; only the outer result is budgeted.
        async with Client(server) as client:
            result = await client.call_tool("big", {})
        return len(result.structured_content["rows"])  # type: ignore[index]

    return server


async def test_middleware_trims_a_tool_result(no_rules):
    async with Client(_server()) as client:
        result = await client.call_tool("big", {})
    assert result.structured_content is not None
    text = result.content[0].text  # type: ignore[union-attr]
    assert len(text.encode()) <= 30_000
    assert json.loads(text) == result.structured_content
    rows = result.structured_content["rows"]
    assert 0 < len(rows) < 2_000
    assert result.structured_content["returned_count"] == len(rows)
    assert "Trimmed to fit" in result.structured_content["provenance"]["limits"]


async def test_inner_in_process_call_is_not_trimmed(no_rules):
    async with Client(_server()) as client:
        result = await client.call_tool("nested", {})
    assert result.structured_content == {"result": 2_000}


async def test_server_adds_caveats_through_call_tool(monkeypatch):
    monkeypatch.setattr(response_budget, "_notes_loaded", True)
    monkeypatch.setattr(
        response_budget, "_notes_for", lambda tool, arguments, lang: [f"{tool} {lang}"]
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "call_tool",
            {"name": "plan_query", "arguments": {"question": "rents in Calgary", "lang": "fr"}},
        )
    assert result.structured_content is not None
    # Once, from the target's own pass, not again for the call_tool wrapper.
    assert result.structured_content["provenance"]["caveats"] == ["plan_query fr"]
    assert json.loads(result.content[0].text) == result.structured_content  # type: ignore[union-attr]
