"""Live smoke test for the eurostat module: calls Eurostat's real APIs (not
mocks) for every client function and every tool, per AGENTS.md's "lesson
from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_eurostat.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.eurostat import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _expect_error(label: str, coro, exc_type: type[Exception]) -> bool:
    try:
        await coro
    except exc_type as exc:
        print(f"OK: {label} -> {type(exc).__name__}: {str(exc)[:120]}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


async def main() -> bool:
    ok = True

    search = await client.search_datasets("unemployment monthly")
    codes = [d.code for d in search.datasets]
    print(f"OK: search -> {search.total_matches} matches, top {codes[:5]}")
    ok &= "une_rt_m" in codes

    french = await client.search_datasets("indice des prix à la consommation harmonisé", lang="fr")
    print(f"OK: search (fr) -> {[d.code for d in french.datasets[:5]]}")
    ok &= any(d.code.startswith("prc_hicp") for d in french.datasets)

    for code in ("namq_10_gdp", "prc_hicp_minr", "teina225"):
        structure = await client.describe_dataset(code, lang="fr")
        dims = [(d.id, d.total_codes) for d in structure.dimensions]
        print(f"OK: describe {code} -> {dims}, {len(structure.flags)} flags")
        ok &= bool(structure.dimensions) and bool(structure.flags)

    gdp = await client.get_data(
        "namq_10_gdp",
        {"unit": ["CLV_PCH_PRE"], "s_adj": ["SCA"], "na_item": ["B1GQ"]},
        geo=["EU27", "EURO_AREA", "Germany", "US"],
        last_n=4,
    )
    print(f"OK: GDP -> {len(gdp.rows)} rows, missing {gdp.missing_geo}, flags {gdp.flags}")
    ok &= len(gdp.rows) >= 8 and gdp.missing_geo == ["US"]

    members = await client.get_data(
        "prc_hicp_minr", {"unit": "RCH_A", "coicop18": "TOTAL"}, geo=["EURO_AREA_MEMBERS"], last_n=1
    )
    print(f"OK: HICP members -> {members.total_rows} rows")
    ok &= members.total_rows >= 20

    for indicator in constants.INDICATORS:
        result = await client.compare(indicator)
        latest = [(s.geo, s.latest_time, s.latest_value, s.latest_flag) for s in result.series]
        print(f"OK: {indicator} -> {latest}")
        ok &= len(result.series) == len(constants.DEFAULT_COMPARE_GEO)

    us = await client.compare("unemployment_rate", geo=["EU27", "US"], lang="fr")
    print(f"OK: compare (fr) US -> {us.provenance.commercial_use} | {us.notes}")
    ok &= us.provenance.commercial_use == "not_allowed"
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("unknown dataset", client.describe_dataset("nope_xx"), NotFound)
    ok &= await _expect_error(
        "unknown code", client.get_data("une_rt_m", {"sex": ["X"]}, last_n=1), InvalidInput
    )
    ok &= await _expect_error(
        "too many series", client.get_data("prc_hicp_minr", last_n=1), InvalidInput
    )
    ok &= await _expect_error(
        "future period",
        client.get_data("teina225", geo=["FR"], start_period="2035"),
        NotFound,
    )
    ok &= await _expect_error("unknown indicator", client.compare("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("eurostat_search_datasets", {"query": "government debt", "lang": "fr"}),
        ("eurostat_describe_dataset", {"dataset": "une_rt_m"}),
        (
            "eurostat_get_data",
            {"dataset": "teina225", "geo": ["EU27", "FR"], "last_n": 2},
        ),
        ("eurostat_compare", {"indicator": "hicp_inflation", "geo": ["EURO_AREA", "IT"]}),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            data = json.loads(text)
            print(f"OK: call_tool({name}) -> {sorted(data)[:5]}")
            ok &= not result.is_error
    return ok


async def run() -> int:
    ok = await main()
    ok &= await errors()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
