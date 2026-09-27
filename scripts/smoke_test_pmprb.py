"""Live smoke test for the PMPRB module (every client function, EN and FR).

uv run python scripts/smoke_test_pmprb.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.pmprb import client


async def main() -> int:
    ok = True

    listing = await client.list_report_tables()
    years = sorted(r.year for r in listing.reports if r.kind == "annual_report")
    print(f"OK: annual reports as HTML -> {years}")
    # confirmed live 2026-09-27: 2018 to 2024, lists for 2020 and 2021
    ok &= years[0] == 2018 and years[-1] >= 2024

    tables = await client.list_report_tables(2024)
    unlabelled = [t.index for t in tables.tables if not t.label]
    print(f"OK: 2024 report -> {tables.total_matched} tables, unlabelled {unlabelled}")
    ok &= tables.total_matched >= 40 and not unlabelled

    pmpi = await client.list_report_tables(query="price index consumer")
    print(f"OK: PMPI tables across years -> {[(t.year, t.index) for t in pmpi.tables]}")
    ok &= len({t.year for t in pmpi.tables}) >= 6

    figure = await client.get_report_table(2024, "Figure 1")
    last = figure.tables[0].rows[-1]
    print(f"OK: 2024 Figure 1 last row -> {last}")
    ok &= last.get("Year") == 2024 and isinstance(last.get("CPI index"), float)

    sales = await client.get_report_table(2024, "Tableau 5", lang="fr")
    first = sales.tables[0].rows[0]
    print(f"OK: 2024 Tableau 5 (fr) -> {sales.tables[0].info.columns[:3]}; {first}")
    ok &= first.get("Année") == 2024 and len(sales.tables[0].info.columns) >= 7

    subtables = await client.get_report_table(2024, "Table 2")
    print(f"OK: 2024 Table 2 -> {[t.info.subtitle for t in subtables.tables]}")
    ok &= len(subtables.tables) >= 2 and all(t.info.subtitle for t in subtables.tables)

    humira = await client.search_patented_medicines("adalimumab")
    print(f"OK: adalimumab 2021 -> {humira.total_matched}, {humira.by_status}")
    ok &= humira.total_matched >= 2 and humira.medicines[0].din.isdigit()

    everything = await client.search_patented_medicines(year=2020, lang="fr", limit=1)
    print(f"OK: 2020 list (fr) -> {everything.total_matched}, {everything.by_status}")
    ok &= everything.total_matched > 1000 and "other" not in everything.by_status

    print("\nPMPRB SMOKE TEST PASSED" if ok else "\nPMPRB SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
