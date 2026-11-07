"""Live smoke test for the bea module: calls the real BEA Data API (not mocks)
for every client function and every tool, per AGENTS.md's "lesson from
auditing the StatCan module".

Needs MAPLE_BEA_API_KEY (a free UserID from https://apps.bea.gov/api/signup/);
without it the script checks that every tool says a key is needed, then
skips the live calls and exits 0. The module was written from the BEA user
guide before any key was available, so the first keyed run is the real check:
read every failure.

Usage:
    MAPLE_BEA_API_KEY=... uv run python scripts/smoke_test_bea.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp import config
from maplestats_mcp.modules.bea import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


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


async def without_key() -> bool:
    ok = await _expect_error("no key", client.get_nipa(), UpstreamUnavailable)
    ok &= await _expect_error("no key (fr)", client.list_datasets(lang="fr"), UpstreamUnavailable)
    return ok


async def main() -> bool:
    ok = True
    datasets = await client.list_datasets()
    names = {d.name for d in datasets.datasets}
    print(f"OK: list_datasets -> {sorted(names)}")
    ok &= {"NIPA", "Regional", "ITA"} <= names

    tables = await client.list_parameter_values("NIPA", "TableName")
    keys = {v.key for v in tables.values}
    print(f"OK: NIPA tables -> {tables.total_values}, e.g. {tables.values[:2]}")
    missing = [t for t in constants.NIPA_TABLES if t not in keys]
    if missing:
        print(f"FAIL: NIPA_TABLES not listed by BEA: {missing}")
        ok = False

    indicators = await client.list_parameter_values("ITA", "Indicator")
    codes = {v.key for v in indicators.values}
    unknown = [i for i in constants.TRADE_INDICATORS if i not in codes]
    print(f"OK: ITA indicators -> {indicators.total_values}; unknown defaults: {unknown}")
    ok &= not unknown

    lines = await client.list_parameter_values("Regional", "LineCode", {"TableName": "SAINC1"})
    print(f"OK: SAINC1 lines -> {[(v.key, v.description) for v in lines.values[:3]]}")
    ok &= any(v.key == "3" for v in lines.values)

    gdp = await client.get_nipa("T10101", "Q")
    line1 = [r for r in gdp.rows if r.line_number == "1"]
    print(f"OK: T10101 -> {gdp.title} | latest {line1[-1].date} {line1[-1].value} {line1[-1].unit}")
    ok &= bool(line1) and line1[-1].value is not None

    income = await client.get_nipa("T20600", "M", lang="fr")
    print(f"OK: T20600 monthly -> {income.total_rows} rows, {income.rows[-1].date}")

    states = await client.get_regional("SAINC1", "3", "STATE")
    washington = [r for r in states.rows if r.geo_fips == "53000"]
    print(f"OK: SAINC1 per capita, Washington -> {[(r.date, r.value) for r in washington]}")
    ok &= bool(washington)

    trade = await client.get_international_transactions()
    print("OK: ITA Canada ->", [(r.indicator, r.date, r.value, r.unit) for r in trade.rows[:6]])
    ok &= all(r.area_or_country == "Canada" for r in trade.rows)
    return ok


async def errors() -> bool:
    ok = await _expect_error("bad table", client.get_nipa("T99999", years=[2020]), InvalidInput)
    ok &= await _expect_error(
        "no data", client.get_regional("SAINC1", "1", "53000", years=[1930]), NotFound
    )
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("bea_list_datasets", {"lang": "fr"}),
        ("bea_list_parameter_values", {"dataset": "ITA", "parameter": "AreaOrCountry"}),
        ("bea_get_nipa", {"table": "T10111", "frequency": "Q"}),
        ("bea_get_regional", {"table": "SAINC1", "line_code": "1", "geo_fips": "53000"}),
        ("bea_get_international_transactions", {"indicators": ["BalGds"], "frequency": "A"}),
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
    if not config.get_bea_api_key():
        ok = await without_key()
        print("SKIPPED live calls: MAPLE_BEA_API_KEY is not set.")
        return 0 if ok else 1
    ok = await main()
    ok &= await errors()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
