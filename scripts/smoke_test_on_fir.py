"""Live smoke test for the on_fir module: downloads real Ontario FIR files (not
mocks) and calls every client function and every tool, per AGENTS.md's
"lesson from auditing the StatCan module".

The first run downloads four years (about 40 MB) into MAPLE_ON_FIR_CACHE_DIR;
it prints each year's download and conversion time and Parquet size.

Usage:
    uv run python scripts/smoke_test_on_fir.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp import config
from maplestats_mcp.modules.on_fir import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound

POLICE = "slc.40X.L0420.C01.11"


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
    years, _ = await client.list_years()
    print("OK: index ->", [(y.year, y.last_updated) for y in years[:4]], f"... {len(years)} years")
    ok &= len(years) >= 26 and years[-1].year == 2000

    newest, default = years[0].year, years[1].year
    for year in (default, newest, 2019, 2005):
        started = time.monotonic()
        schedules = await client.list_schedules(year)
        elapsed = time.monotonic() - started
        files = sorted(config.get_on_fir_cache_dir().glob(f"fir_{year}_*.parquet"))
        size = files[-1].stat().st_size / 1e6 if files else 0
        print(
            f"OK: {year} -> {schedules.municipalities_filed} filed, "
            f"{len(schedules.schedules)} schedules, {elapsed:.1f} s, {size:.1f} MB Parquet"
        )
        ok &= bool(schedules.schedules) and schedules.municipalities_filed > 0
        if year in (default, 2019, 2005):
            ok &= schedules.municipalities_filed >= 400
    default_list = await client.list_schedules()
    ok &= default_list.year == default

    toronto = await client.search_municipalities("toronto", default)
    print(
        "OK: search toronto ->", [(m.munid, m.name, m.population) for m in toronto.municipalities]
    )
    ok &= any(m.munid == "20002" for m in toronto.municipalities)
    upper = await client.search_municipalities("", default, tier="UT", limit=5, lang="fr")
    print(f"OK: upper tiers -> {upper.total}, {upper.municipalities[0].tier_name}")
    ok &= upper.total >= 25

    lines = await client.search_lines("police total expenses", default, "40")
    print("OK: lines ->", [(line.slc, line.municipalities) for line in lines.lines])
    ok &= any(line.slc == POLICE for line in lines.lines)
    reserves = await client.search_lines("reserves balance end of year", default, "60")
    ok &= reserves.total >= 1

    schedule = await client.get_schedule("Toronto", "40", default, line="0420")
    print(
        "OK: Toronto police ->",
        [(v.column_desc, v.amount) for v in schedule.values][:4],
    )
    ok &= any(v.slc == POLICE and (v.amount or 0) > 1e9 for v in schedule.values)
    taxes = await client.get_schedule("Ottawa", "26", default)
    ok &= {v.slc[4:7] for v in taxes.values} >= {"26A"}

    ranked = await client.compare(POLICE, [default], tier="ST", per_capita=True, limit=5)
    print(
        "OK: police per capita ST ->",
        [(r.municipality, round(r.per_capita or 0)) for r in ranked.rows],
        ranked.provenance.coverage,
    )
    ok &= len(ranked.rows) == 5 and all(r.per_capita for r in ranked.rows)
    series = await client.compare(POLICE, [default, 2019, 2005], municipalities=["Ottawa C"])
    print(
        "OK: Ottawa police over time ->",
        [(r.year, r.amount) for r in series.rows],
        series.label_changes,
    )
    ok &= len(series.rows) >= 2
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("unknown year", client.list_schedules(1990), NotFound)
    ok &= await _expect_error("bad slc", client.compare("police"), InvalidInput)
    ok &= await _expect_error("nobody reports", client.compare("slc.40X.L9999.C01.11"), NotFound)
    ok &= await _expect_error(
        "unknown municipality", client.get_schedule("Atlantis", "40"), NotFound
    )
    ok &= await _expect_error("bad schedule", client.get_schedule("Toronto", "4X0"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("on_fir_list_schedules", {"lang": "fr"}),
        ("on_fir_search_municipalities", {"query": "sault"}),
        ("on_fir_search_lines", {"query": "closing net book value", "schedule": "51"}),
        ("on_fir_get_schedule", {"municipality": "Peel R", "schedule": "74"}),
        (
            "on_fir_compare",
            {"slc": POLICE, "municipalities": ["Toronto", "Ottawa"], "per_capita": True},
        ),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            if result.is_error:
                print(f"FAIL: call_tool({name}) -> {text[:300]}")
                ok = False
                continue
            data = json.loads(text)
            print(f"OK: call_tool({name}) -> {sorted(data)[:5]}")
    return ok


async def run() -> int:
    print(f"cache: {config.get_on_fir_cache_dir()} ({constants.INDEX_URL})")
    ok = await main()
    ok &= await errors()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
