"""Live smoke test for the bls module: calls the real BLS Public Data API (not
mocks) for every client function and every tool, per AGENTS.md's "lesson
from auditing the StatCan module".

Runs without a key, at the BLS's unregistered limits: 25 queries a day per
address. A full run spends about 9; set MAPLE_BLS_API_KEY to use registered
limits (and to see catalog titles). The keyless run is the one that matters
most, since the server must work without one.

Usage:
    uv run python scripts/smoke_test_bls.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp import config
from maplestats_mcp.modules.bls import client, constants
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
    print(f"Key set: {config.get_bls_api_key() is not None}")

    surveys = await client.list_surveys()
    codes = {s.code for s in surveys.surveys}
    print(f"OK: list_surveys -> {len(codes)} surveys")
    ok &= {"CU", "CE", "LN", "JT"} <= codes
    unnamed = [c for c in constants.RELEASES if c not in codes]
    if unnamed:
        print(f"FAIL: RELEASES prefixes the BLS does not list: {unnamed}")
        ok = False

    found = await client.search_series("core", survey="CU")
    print("OK: search CU ->", [(m.series_id, m.popular) for m in found.matches[:4]])
    ok &= found.matches[0].series_id.endswith("SA0L1E")

    # Every known series in one or two queries (25 ids per query unregistered).
    ids = list(constants.KNOWN_SERIES)
    for start in range(0, len(ids), constants.UNREGISTERED_MAX_SERIES):
        batch = ids[start : start + constants.UNREGISTERED_MAX_SERIES]
        result = await client.get_series(batch, 2025, 2026)
        got = {s.series_id for s in result.series}
        print(f"OK: {len(got)} of {len(batch)} known series have 2025-2026 data")
        if got != set(batch):
            print(f"FAIL: known series without data: {sorted(set(batch) - got)}")
            ok = False

    payrolls = await client.get_indicator("nonfarm_payrolls")
    latest = payrolls.series.observations[-1]
    print(
        f"OK: payrolls {latest.date} {latest.value} change {latest.change_from_previous} "
        f"prelim {latest.preliminary}"
    )
    ok &= payrolls.series.units == "thousands of persons" and latest.value is not None

    cpi = await client.get_indicator("cpi_all_items", seasonally_adjusted=False, lang="fr")
    obs = [o for o in cpi.series.observations if o.value is not None][-1]
    print(f"OK: CPI-U NSA (fr) {obs.date} {obs.value}, 12 mois {obs.pct_change_from_year_ago}")
    ok &= obs.pct_change_from_year_ago is not None

    long = await client.get_series(["LNS14000000"], 2007, 2026)
    print(f"OK: 2007-2026 -> {long.start_year}-{long.end_year}, notes {long.notes[:1]}")
    ok &= (
        long.series[0].observations[-1].year == 2026 or long.series[0].observations[-1].year == 2025
    )
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("unknown id", client.get_series(["ZZZZZ99999"], 2025, 2026), NotFound)
    ok &= await _expect_error("bad id", client.get_series(["cpi all items"]), InvalidInput)
    ok &= await _expect_error("unknown indicator", client.get_indicator("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("bls_list_surveys", {"lang": "fr"}),
        ("bls_search_series", {"query": "shelter"}),
        ("bls_get_series", {"series_ids": ["CUSR0000SAH1"], "start_year": 2025}),
        ("bls_get_indicator", {"indicator": "unemployment_rate"}),
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
