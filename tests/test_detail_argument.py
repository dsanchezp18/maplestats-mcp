"""`detail` is call_tool's shaping argument; no data tool may take one of its own.

ResponseBudgetMiddleware removes `detail` from every data tool's arguments
(shared/response_budget.py), so a tool parameter of that name could never be
set: statcan_delta_list_tables had `detail: bool` until it became
`include_members`. These tests run the real server, with the Delta File
reader replaced, so nothing reaches www150.statcan.gc.ca.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp import catalogue
from maplestats_mcp.modules.statcan.delta import archive
from maplestats_mcp.modules.statcan.delta.archive_schemas import (
    DeltaDimension,
    DeltaTable,
    DeltaTableList,
)
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.response_budget import DETAIL_ARGUMENT

DAY = "2026-10-02"


def _tables(n: int) -> DeltaTableList:
    tables = [
        DeltaTable(
            product_id=10100001 + i,
            title_en=f"Table {i}",
            dimensions=[DeltaDimension(position_id=1, member_count=2)],
        )
        for i in range(n)
    ]
    return DeltaTableList(
        date=DAY,
        zip_url="https://www150.statcan.gc.ca/n1/delta/20261002.zip",
        table_count=n,
        returned=n,
        tables=tables,
        provenance=Provenance(
            source="statcan-delta",
            url="https://www150.statcan.gc.ca/n1/delta/20261002.zip",
            queried_at=datetime(2026, 10, 2, tzinfo=UTC),
            cached=False,
            schema_name="statcan.DeltaTableList",
        ),
    )


@pytest.fixture
def seen(monkeypatch) -> list[dict[str, Any]]:
    """The keyword arguments each statcan_delta_list_tables call reached the reader with."""
    calls: list[dict[str, Any]] = []

    async def list_tables(date: str, **kwargs: Any) -> DeltaTableList:
        calls.append({"date": date, **kwargs})
        return _tables(8)

    monkeypatch.setattr(archive, "list_tables", list_tables)
    return calls


def _body(result: Any) -> dict[str, Any]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return json.loads(block.text)


async def test_delta_option_reaches_the_tool_through_call_tool(seen):
    async with Client(mcp) as client:
        await client.call_tool(
            "call_tool",
            {
                "name": "statcan_delta_list_tables",
                "arguments": {"date": DAY, "product_id": 10100001, "include_members": True},
            },
        )
        await client.call_tool(
            "call_tool",
            {"name": "statcan_delta_list_tables", "arguments": {"date": DAY}, "detail": "full"},
        )
    assert seen[0]["include_members"] is True
    assert seen[0]["product_id"] == 10100001
    # call_tool's own `detail` shapes the result and is not passed to the tool.
    assert seen[1]["include_members"] is False
    assert DETAIL_ARGUMENT not in seen[1]


async def test_call_tool_detail_still_shapes_a_delta_result(seen):
    async with Client(mcp) as client:
        brief = await client.call_tool(
            "call_tool",
            {
                "name": "statcan_delta_list_tables",
                "arguments": {"date": DAY, "include_members": True, "product_id": 10100001},
            },
        )
        full = await client.call_tool(
            "call_tool",
            {
                "name": "statcan_delta_list_tables",
                "arguments": {"date": DAY, "include_members": True, "product_id": 10100001},
                "detail": "full",
            },
        )
    # Brief keeps the citation and drops null fields and the query time; full keeps all.
    brief_body = _body(brief)
    assert brief_body["provenance"]["source"] == "statcan-delta"
    assert "queried_at" not in brief_body["provenance"]
    assert "cansim_id" not in brief_body["tables"][0]
    full_body = _body(full)
    assert full_body["tables"][0]["product_id"] == 10100001
    assert full_body["tables"][0]["cansim_id"] is None
    assert full_body["provenance"]["queried_at"].startswith("2026-10-02")
    assert all(call["include_members"] is True for call in seen)


def test_no_data_tool_takes_a_detail_parameter():
    """A tool's own `detail` would be removed before it ran, so it could never be set.

    The catalogue lists every tool, including those behind a setting
    (test_tool_catalogue.py keeps it current).
    """
    modules = catalogue.read_catalogue()
    assert modules is not None
    clashing = sorted(
        tool["name"]
        for module in modules.values()
        for tool in module["tools"]
        if DETAIL_ARGUMENT in (tool.get("parameters") or {}).get("properties", {})
    )
    assert clashing == [], f"rename the `detail` parameter of: {', '.join(clashing)}"
