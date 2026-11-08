"""Live smoke test for the fed module: reads the Federal Reserve Board's real
release files (not mocks) through every client function and every tool, per
AGENTS.md's "lesson from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_fed.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.fed import client, constants
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
    releases = await client.list_releases()
    ok &= len(releases.releases) == len(constants.RELEASES)

    # Every release file parses and has series (2026-11-07: from 3 in DSR to
    # 2,796 in SCOOS).
    for code in constants.RELEASES:
        structure = await client.describe_release(code)
        print(f"OK: {code} -> {structure.series_count} series, prepared {structure.prepared}")
        ok &= structure.series_count > 0 and bool(structure.groups)

    # Every preset series exists and has recent values.
    for name, spec in constants.INDICATORS.items():
        result = await client.get_indicator(name, last_n=1)
        row = result.rows[-1]
        print(f"OK: {name} -> {row.date} {row.value} {row.unit}")
        ok &= row.series_id == spec.series and row.date >= "2026"

    found = await client.search_series("canada dollar")
    print("OK: search canada dollar ->", [s.series_id for s in found.series])
    ok &= "RXI_N.B.CA" in [s.series_id for s in found.series]

    motor = await client.search_series(
        "motor vehicle assemblies", release="G17", frequency="monthly"
    )
    print(f"OK: search G17 motor vehicles -> {motor.total_matches} matches")
    ok &= motor.total_matches > 0

    yields = await client.get_series(
        "H15", ["RIFLGFCY02_N.M", "RIFLGFCY10_N.M"], start_date="2025-01", lang="fr"
    )
    print(f"OK: H15 monthly yields -> {len(yields.rows)} rows")
    ok &= len({r.series_id for r in yields.rows}) == 2
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("unknown release", client.describe_release("Z1"), InvalidInput)
    ok &= await _expect_error("unknown series", client.get_series("H15", ["NOPE"]), NotFound)
    ok &= await _expect_error(
        "future dates", client.get_series("H15", ["RIFSPFF_N.B"], start_date="2031"), NotFound
    )
    ok &= await _expect_error("unknown indicator", client.get_indicator("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("fed_list_releases", {"lang": "fr"}),
        ("fed_describe_release", {"release": "PRATES"}),
        ("fed_search_series", {"query": "Treasury 5-year", "release": "H15"}),
        ("fed_get_series", {"release": "H10", "series": ["RXI_N.M.JA"], "last_n": 3}),
        ("fed_get_indicator", {"indicator": "treasury_10y", "last_n": 5}),
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
