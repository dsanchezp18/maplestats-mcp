"""Brief and full results (shared/brief.py), and the `detail` argument through call_tool."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Client, FastMCP
from mcp.types import TextContent
from pydantic import BaseModel

from maplestats_mcp.server import AnnotatedBM25SearchTransform
from maplestats_mcp.shared.brief import (
    csv_rows,
    expand_tables,
    is_csv_block,
    licence_id,
    shape,
    share_repeated_notes,
)
from maplestats_mcp.shared.response_budget import ResponseBudgetMiddleware, with_detail
from maplestats_mcp.shared.usage import UsageMiddleware, UsageStats

LICENCE = (
    "Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence). "
    "Attribution: 'Source: Statistics Canada.'"
)


def _observation(period: str, value: float | None, status: str = "normal") -> dict[str, Any]:
    return {
        "ref_period": period,
        "value": value,
        "decimals": 1,
        "scalar_factor_code": 0,
        "scale_multiplier": 1,
        "symbol_code": 0,
        "status_code": 0 if status == "normal" else 1,
        "security_level_code": 0,
        "release_time": "2026-11-06T12:30:00Z",
        "symbol": "none",
        "status": status,
        "security_level": "public",
    }


def _series(vector: int, member: str, n: int, note: str) -> dict[str, Any]:
    return {
        "product_id": 14100287,
        "vector_id": vector,
        "context": {
            "citation": (
                "Statistics Canada. Table 14-10-0287-01, Labour force characteristics. "
                f"Vector v{vector}. Released 2026-11-06."
            ),
            "table_id": "14-10-0287-01",
            "table_title": "Labour force characteristics",
            "table_url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701",
            "series_title": f"Canada;{member};Seasonally adjusted",
            "unit": "Percent",
            "scale": "units",
            "members": [
                {"dimension": "Geography", "member": "Canada", "member_id": 1},
                {"dimension": "Characteristic", "member": member, "member_id": 7},
                {"dimension": "Data type", "member": "Seasonally adjusted", "member_id": 1},
            ],
            "table_release_time": "2026-11-06T08:30",
            "notes": [note, f"Only {member} carries this note about its own definition."],
        },
        "observations": [
            _observation(
                f"2026-{m:02d}-01", 6.0 + m / 10, "use with caution" if m == 3 else "normal"
            )
            for m in range(1, n + 1)
        ],
        "transformed": None,
    }


def _payload(n: int = 8) -> dict[str, Any]:
    shared = "Estimates for the territories are three-month moving averages, not monthly."
    return {
        "series": [
            _series(2062815, "Unemployment rate", n, shared),
            _series(2062816, "Participation rate", n, shared),
        ],
        "failed": [],
        "provenance": {
            "source": "statcan-wds",
            "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
            "queried_at": "2026-11-08T12:00:00Z",
            "as_of": None,
            "freshness": "Monthly, on the first Friday at 8:30 a.m. ET.",
            "coverage": None,
            "limits": "Newer data exist: pass recent for the latest values.",
            "cached": False,
            "lang": "en",
            "schema_name": "statcan.wds.VectorDataSet",
            "licence": LICENCE,
            "commercial_use": "allowed",
            "caveats": ["LFS figures are survey estimates with standard errors."],
            "reproduce": "For scripts, call reproduce_code with this tool's name and arguments.",
        },
    }


def test_brief_keeps_values_citations_flags_and_caveats():
    full = _payload()
    brief = shape(full, "brief")
    assert brief is not None
    text = json.dumps(brief)
    provenance = brief["provenance"]
    for kept in ("source", "url", "limits", "caveats", "commercial_use"):
        assert provenance[kept] == full["provenance"][kept]
    assert provenance["licence"] == (
        "Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence)"
    )
    for dropped in ("queried_at", "freshness", "cached", "schema_name", "reproduce", "lang"):
        assert dropped not in provenance
    assert "detail='full'" in brief["detail"]
    for series in full["series"]:
        assert series["context"]["citation"] in text
        assert series["context"]["series_title"] in text
    rows = expand_tables(brief)["series"][0]["observations"]
    assert [r["ref_period"] for r in rows] == [
        o["ref_period"] for o in full["series"][0]["observations"]
    ]
    assert [r["value"] for r in rows] == [o["value"] for o in full["series"][0]["observations"]]
    # The one flag that differs from "normal" stays, on its row; the codes go.
    assert [r.get("status") for r in rows].count("use with caution") == 1
    assert "status_code" not in brief["series"][0]["observations"]["csv"]
    context = brief["series"][0]["context"]
    assert "members" not in context and "table_title" not in context
    assert context["unit"] == "Percent" and context["scale"] == "units"
    assert len(text) < len(json.dumps(full)) / 2


def test_short_lists_stay_json_and_missing_values_stay_null():
    full = _payload(n=3)
    full["series"][0]["observations"][1]["value"] = None
    brief = shape(full, "brief")
    assert brief is not None
    observations = brief["series"][0]["observations"]
    assert isinstance(observations, list)
    assert observations[1] == {"ref_period": "2026-02-01", "value": None}


def test_full_is_unchanged_except_repeated_notes():
    plain = _payload()
    for series in plain["series"]:
        series["context"]["notes"] = series["context"]["notes"][1:]
    assert shape(plain, "full") is None
    repeated = _payload()
    full = shape(repeated, "full")
    assert full is not None
    assert full["shared_notes"] == [repeated["series"][0]["context"]["notes"][0]]
    for series in full["series"]:
        assert series["context"]["notes"][0] == "shared_notes[0]"
        assert series["context"]["notes"][1].startswith("Only ")
    # Everything but the notes is as the tool returned it.
    full.pop("shared_notes")
    for series in full["series"]:
        series["context"]["notes"] = series["context"]["notes"][1:]
    for series in repeated["series"]:
        series["context"]["notes"] = series["context"]["notes"][1:]
    assert full == repeated


def test_repeated_licences_in_items_are_shared():
    payload = {"datasets": [{"id": i, "licence": LICENCE} for i in range(3)], "provenance": {}}
    assert share_repeated_notes(payload)
    assert payload["shared_notes"] == [LICENCE]
    assert {d["licence"] for d in payload["datasets"]} == {"shared_notes[0]"}


def test_csv_round_trip_keeps_types_and_nested_values():
    rows = [
        {"ref_date": f"2026-10-{d:02d}", "values": {"FXUSDCAD": 1.38 + d / 100}, "note": 'a, "b"'}
        for d in range(1, 8)
    ]
    rows[2]["values"] = {"FXUSDCAD": None}
    brief = shape({"observations": rows}, "brief")
    assert brief is not None
    block = brief["observations"]
    assert is_csv_block(block) and block["rows"] == 7
    back = csv_rows(block)
    assert back[0] == rows[0]
    assert back[2]["values"] == {}
    assert back[6]["values"]["FXUSDCAD"] == rows[6]["values"]["FXUSDCAD"]


def test_rows_with_deeper_structure_stay_json():
    rows = [{"id": i, "points": [1, 2]} for i in range(8)]
    brief = shape({"items": rows}, "brief")
    assert brief is not None
    assert isinstance(brief["items"], list)


def test_wrapped_list_result_is_compacted():
    rows = [{"name": f"n{i}", "value": i} for i in range(7)]
    brief = shape({"result": rows}, "brief", wrapped=True)
    assert brief is not None
    assert is_csv_block(brief["result"])


def test_licence_id():
    assert licence_id("Name only, no link. And conditions.") == "Name only, no link."
    assert (
        licence_id(
            "Bank of Canada Terms of Use (https://www.bankofcanada.ca/terms/): attribute the Bank"
        )
        == "Bank of Canada Terms of Use (https://www.bankofcanada.ca/terms/)"
    )


def test_with_detail_precedence():
    assert with_detail(None, None) == {"detail": "brief"}
    assert with_detail({"detail": "full"}, None) == {"detail": "full"}
    assert with_detail({"detail": "full", "x": 1}, "brief") == {"detail": "brief", "x": 1}


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


class Rows(BaseModel):
    rows: list[dict[str, Any]]
    provenance: dict[str, Any]


def _server(stats: UsageStats | None = None) -> FastMCP:
    mcp = FastMCP("brief-test")
    if stats is not None:
        mcp.add_middleware(UsageMiddleware(stats))
    mcp.add_middleware(ResponseBudgetMiddleware())

    @mcp.tool
    def table(n: int = 10) -> Rows:
        return Rows(
            rows=[{"period": f"2026-{m:02d}", "value": m, "empty": None} for m in range(1, n + 1)],
            provenance={"source": "x", "url": "https://x", "queried_at": "now", "cached": False},
        )

    mcp.add_transform(AnnotatedBM25SearchTransform(always_visible=[]))
    return mcp


async def test_call_tool_is_brief_by_default_and_full_on_request():
    async with Client(_server()) as client:
        brief = await client.call_tool("call_tool", {"name": "table", "arguments": {}})
        full = await client.call_tool(
            "call_tool", {"name": "table", "arguments": {}, "detail": "full"}
        )
        inner = await client.call_tool(
            "call_tool", {"name": "table", "arguments": {"detail": "full"}}
        )
        direct = await client.call_tool("table", {})
    brief_body = json.loads(_text(brief))
    assert is_csv_block(brief_body["rows"])
    assert brief_body["provenance"] == {"source": "x", "url": "https://x"}
    full_body = json.loads(_text(full))
    assert full_body["rows"][0] == {"period": "2026-01", "value": 1, "empty": None}
    assert full_body["provenance"]["queried_at"] == "now"
    assert json.loads(_text(inner)) == full_body
    # A direct call is checked against the tool's output schema: full by default.
    assert json.loads(_text(direct)) == full_body


async def test_usage_records_the_size_the_client_reads():
    stats = UsageStats(tool_names=["table", "call_tool", "search_tools"])
    async with Client(_server(stats)) as client:
        brief = await client.call_tool("call_tool", {"name": "table", "arguments": {}})
        await client.call_tool("call_tool", {"name": "table", "arguments": {}, "detail": "full"})
    sizes = stats.snapshot()["result_size"]["table"]
    assert sizes["results"] == 2
    assert sizes["max_chars"] > len(_text(brief))
    assert sizes["mean_tokens_est"] == (sizes["mean_chars"] + 3) // 4
    assert "rows" not in json.dumps(stats.snapshot()["result_size"])
