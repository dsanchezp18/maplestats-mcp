"""Live smoke test for the NRCan mineral production module.

uv run python scripts/smoke_test_nrcan_minerals.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.nrcan_minerals import client


async def main() -> int:
    ok = True

    latest = await client.get_production(commodity="gold", province="ON")
    print(
        f"OK: latest {latest.year} ({latest.title}) -> {[(r.category, r.value) for r in latest.rows]}"
    )
    # confirmed live 2026-10-03: 2025 preliminary, years back to 1990
    ok &= latest.year >= 2025 and min(latest.available_years) == 1990 and len(latest.rows) == 3

    for year in (2019, 2018, 1990):
        data = await client.get_production(year, province="Canada", category="value")
        unnamed = [r for r in data.rows if not r.commodity or r.commodity[-1] == ")"][:3]
        print(
            f"OK: {year} -> {data.total_matched} Canada value rows, {len(data.commodities)} commodities"
        )
        ok &= data.total_matched > 30 and not any("(1" in r.commodity for r in unnamed)

    series = await client.get_series("Grand total", from_year=2010)
    print(f"OK: grand total -> {[(p.year, p.value) for p in series.points]}")
    ok &= len(series.points) >= 15 and not series.missing_years

    gold = await client.get_series("gold", province="QC", category="quantity_shipped")
    print(f"OK: Quebec gold shipped -> {len(gold.points)} years, missing {gold.missing_years}")
    ok &= len(gold.points) >= 30

    print("\nNRCAN MINERALS SMOKE TEST PASSED" if ok else "\nNRCAN MINERALS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
