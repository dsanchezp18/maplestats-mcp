"""Live smoke test for the abs module: calls the real ABS Data API (not mocks)
for every client function and every tool, per AGENTS.md's "lesson from
auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_abs.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.abs import client, constants
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
    for query, expected in (
        ("consumer price index", "CPI"),
        ("labour force", "LF"),
        ("wage price index", "WPI"),
        ("national accounts key aggregates", "ANA_AGG"),
    ):
        found = await client.search_datasets(query, limit=5)
        ids = [d.id for d in found.datasets]
        print(f"OK: search {query!r} -> {found.total_matches} matches, top {ids[:3]}")
        if expected not in ids:
            print(f"FAIL: {expected} not in the top 5 for {query!r}")
            ok = False

    for dataset in ("CPI", "LF"):
        structure = await client.describe_dataset(dataset)
        print(
            f"OK: describe {dataset} -> {structure.key_template} e.g. {structure.example_key!r}, "
            f"{[d.total_codes for d in structure.dimensions]}"
        )
        ok &= all(d.codes for d in structure.dimensions)

    states = await client.get_data("LF", "M13.3.1599.20.1+2+AUS.M", last_n=2)
    print(
        "OK: LF states ->", [(s.key, s.region, s.adjustment, s.latest_value) for s in states.series]
    )
    ok &= len(states.series) == 3

    cpi = await client.get_data("CPI", "3.10001.10.50.M", start_period="2026-01")
    print("OK: CPI ->", [(r.period, r.value) for r in cpi.rows[-3:]])
    # The ABS release page: CPI rose 4.3% in the 12 months to September 2026.
    sept = next((r.value for r in cpi.rows if r.period == "2026-09"), None)
    ok &= sept is not None and abs(sept - 4.3) < 0.05

    for indicator in constants.INDICATORS:
        result = await client.get_indicator(indicator)
        print(
            f"OK: {indicator} -> {result.latest_period} {result.latest_value} ({result.unit}, "
            f"{result.frequency}), {len(result.observations)} obs"
        )
        ok &= bool(result.observations) and result.canada_counterpart.startswith("Canada")

    french = await client.get_indicator("unemployment_rate", lang="fr")
    print(f"OK: (fr) {french.indicator_label}")
    ok &= french.indicator_label.startswith("Taux de chômage")
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("short key", client.get_data("LF", "M13.3"), InvalidInput)
    ok &= await _expect_error(
        "unknown code", client.get_data("LF", "M99.3.1599.20.AUS.M", last_n=1), InvalidInput
    )
    ok &= await _expect_error("unknown dataset", client.describe_dataset("NOPE_X"), NotFound)
    ok &= await _expect_error(
        "future period",
        client.get_data("LF", "M13.3.1599.20.AUS.M", start_period="2040-01"),
        NotFound,
    )
    return ok


async def through_server() -> bool:
    ok = True
    calls = [
        ("abs_search_datasets", {"query": "labour force"}),
        ("abs_describe_dataset", {"dataset": "WPI"}),
        ("abs_get_data", {"dataset": "LF", "key": "M13.3.1599.20.AUS.M", "last_n": 3}),
        ("abs_get_indicator", {"indicator": "cpi_inflation", "lang": "fr"}),
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
