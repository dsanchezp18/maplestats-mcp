"""Live smoke test for the ons module: calls the real ONS search API and time
series pages (not mocks) for every client function and every tool, per
AGENTS.md's "lesson from auditing the StatCan module".

About 40 requests at one a second, well under the ONS limits.

Usage:
    uv run python scripts/smoke_test_ons.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.ons import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _expect_error(label: str, coro, exc_type: type[Exception]) -> bool:
    try:
        await coro
    except exc_type as exc:
        print(f"OK: {label} -> {type(exc).__name__}: {str(exc)[:140]}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


async def main() -> bool:
    ok = True
    for query, dataset, expected in (
        ("CPIH annual rate all items", None, "L55O"),
        ("CPI annual rate all items", "MM23", "D7G7"),
        ("unemployment rate aged 16 and over seasonally adjusted", "LMS", "MGSX"),
    ):
        found = await client.search_series(query, dataset=dataset, limit=5)
        ids = [s.series_id for s in found.series]
        print(f"OK: search {query!r} -> {found.total_matches} matches, top {ids}")
        if expected not in ids:
            print(f"FAIL: {expected} not in the top 5 for {query!r}")
            ok = False

    cpi = await client.get_series("d7g7", last_n=3)
    print(f"OK: D7G7 -> {cpi.title} {cpi.unit} {[(o.period, o.value) for o in cpi.observations]}")
    print(
        f"   frequencies {cpi.available_frequencies}, released {cpi.release_date}, next {cpi.next_release}"
    )
    ok &= cpi.frequency == "monthly" and cpi.observations[-1].period[4] == "-"

    gdp = await client.get_series("IHYQ", start_period="2025-Q1", lang="fr")
    print(
        f"OK: IHYQ (fr) -> {gdp.dataset} others {gdp.other_datasets} {[(o.period, o.value) for o in gdp.observations]}"
    )
    ok &= gdp.frequency == "quarterly" and bool(gdp.notes)

    annual = await client.get_series(
        "D7G7", frequency="annual", start_period="2020", end_period="2025"
    )
    print(f"OK: D7G7 annual -> {[(o.period, o.value) for o in annual.observations]}")
    ok &= [o.period for o in annual.observations] == [str(y) for y in range(2020, 2026)]

    for indicator in constants.INDICATORS:
        result = await client.get_indicator(indicator)
        print(
            f"OK: {indicator} -> {result.series_id}/{result.dataset} {result.latest_period} "
            f"{result.latest_value} ({result.unit}) | {result.title[:60]}"
        )
        ok &= bool(result.observations) and result.canada_counterpart.startswith("Canada")

    french = await client.get_indicator("unemployment_rate", lang="fr")
    print(f"OK: (fr) {french.indicator_label} | {french.canada_counterpart[:60]}")
    ok &= french.indicator_label.startswith("Taux de chômage")
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("bad id", client.get_series("CPI annual"), InvalidInput)
    ok &= await _expect_error("unknown id", client.get_series("ZZZ9"), NotFound)
    ok &= await _expect_error("wrong dataset", client.get_series("D7G7", dataset="LMS"), NotFound)
    ok &= await _expect_error(
        "wrong frequency", client.get_series("IHYQ", frequency="monthly"), InvalidInput
    )
    ok &= await _expect_error("unknown indicator", client.get_indicator("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    ok = True
    calls = [
        ("ons_search_series", {"query": "CPIH annual rate", "dataset": "MM23"}),
        ("ons_get_series", {"series_id": "MGSX", "last_n": 3}),
        ("ons_get_indicator", {"indicator": "cpi_inflation", "lang": "fr"}),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            data = json.loads(text)
            print(f"OK: call_tool({name}) -> {sorted(data)[:6]}")
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
