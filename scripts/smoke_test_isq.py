"""Live smoke test for the Institut de la statistique du Québec module, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_isq.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.isq import client


async def main() -> int:
    ok = True

    found = await client.search_tables("revenu disponible MRC", lang="fr")
    print(f"OK: search 'revenu disponible MRC' -> {found.total_matched}")
    ok &= found.total_matched >= 1

    everything = await client.search_tables("population", lang="all", limit=1)
    print(f"OK: search 'population' -> {everything.total_matched}")
    ok &= everything.total_matched > 50

    # Disposable income per capita by MRC (ISQ's own estimates), checked 2026-09-26.
    income = await client.get_table("3970", max_rows=3)
    first = income.rows[0] if income.rows else {}
    print(f"OK: table 3970 -> {income.total_rows} rows, {len(income.columns)} columns: {first}")
    ok &= income.kind == "dynamic" and income.total_rows > 100
    ok &= any(isinstance(v, int) and v > 20_000 for v in first.values())

    # Cinema indicators, 1975 to the latest year, with flags.
    cinema = await client.get_table("2736")
    print(f"OK: table 2736 -> {cinema.total_rows} rows; legend {len(cinema.flag_legend)} signs")
    ok &= cinema.total_rows >= 5 and "r" in cinema.flag_legend and bool(cinema.notes)

    # Grouped survey table with confidence intervals.
    survey = await client.get_table("4074", max_rows=2)
    print("OK: table 4074 columns ->", survey.columns[:4])
    ok &= survey.columns[0] == "Groupe" and survey.total_rows > 500

    static = await client.get_table(
        "population-by-age-group-2016-2041-reference-scenario-a-bas-saint-laurent", lang="en"
    )
    print(f"OK: static table -> {static.total_rows} rows, excel {static.excel_url}")
    ok &= static.kind == "static" and static.total_rows > 10 and static.excel_url is not None

    print("\nISQ SMOKE TEST PASSED" if ok else "\nISQ SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
