"""Live smoke test for the dfo_landings module: calls every client function
against open.canada.ca and DFO's data hub (not mocks), and checks values
against an independent read of the same published files.

Usage:
    uv run python scripts/smoke_test_dfo_landings.py
"""

from __future__ import annotations

import asyncio
import csv
import sys

import httpx

from maplestats_mcp.modules.dfo_landings import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


def _report(label: str, passed: bool, detail: str) -> bool:
    print(f"{'OK' if passed else 'FAIL'}: {label} -> {detail}")
    return passed


def _raw_rows(url: str) -> list[list[str]]:
    raw = httpx.get(url, timeout=60.0).content
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return list(csv.reader(text.splitlines()))


async def main() -> int:
    ok = True
    catalogue = await client.list_tables()
    sea_table, fresh_table = catalogue.tables
    ok &= _report(
        "list_tables",
        sea_table.first_year == 1990
        and (sea_table.last_year or 0) >= 2024
        and (fresh_table.last_year or 0) >= 2019
        and len(fresh_table.files) >= 60,
        f"sea {sea_table.first_year}-{sea_table.last_year} ({len(sea_table.files)} files), "
        f"freshwater {fresh_table.first_year}-{fresh_table.last_year} "
        f"({len(fresh_table.files)} files)",
    )

    # Independent read of the English sea file: Nova Scotia lobster, 2024.
    sea_url = next(f.url for f in sea_table.files if f.language == "en")
    raw = next(
        r
        for r in _raw_rows(sea_url)
        if r[:2] == ["2024", "Nova Scotia"] and len(r) > 3 and r[3] == "Lobster"
    )
    lobster = await client.get_landings(year=2024, region="Nova Scotia", species="Lobster")
    row = lobster.rows[0]
    expected_kg = float(raw[4].replace(",", ""))
    expected_value = float(raw[5].replace(",", ""))
    ok &= _report(
        "sea NS lobster 2024 matches the file",
        len(lobster.rows) == 1
        and row.quantity_tonnes == round(expected_kg / 1000, 3)
        and row.value_dollars == expected_value,
        f"{row.quantity_tonnes} t, ${row.value_dollars:,.0f} (file {raw[4]} kg, ${raw[5]})",
    )

    french = await client.get_landings(
        year=2024, region="Nouvelle-Écosse", species="Homard", lang="fr"
    )
    ok &= _report(
        "sea French file",
        len(french.rows) == 1
        and french.rows[0].quantity_tonnes == row.quantity_tonnes
        and abs((french.rows[0].value_dollars or 0) - (row.value_dollars or 0)) < 1,
        f"{french.rows[0].region} {french.rows[0].species} {french.rows[0].value_dollars}",
    )

    # The provinces' group rows add up to Canada's within rounding.
    canada = await client.get_landings(year=2024, species="Total shellfish", limit=50)
    by_region = {r.region: r.value_dollars or 0 for r in canada.rows}
    provinces = sum(v for k, v in by_region.items() if k not in {"Canada", "Atlantic"})
    ok &= _report(
        "sea provinces sum to Canada",
        abs(provinces - by_region.get("Canada", 0)) <= 0.001 * by_region.get("Canada", 1),
        f"provinces ${provinces:,.0f} vs Canada ${by_region.get('Canada', 0):,.0f}",
    )

    suppressed = await client.get_landings(year=2006, region="New Brunswick", species="Clams")
    ok &= _report(
        "sea suppressed cell",
        bool(suppressed.rows) and suppressed.rows[0].suppressed,
        f"{suppressed.rows[0] if suppressed.rows else 'none'}",
    )

    # Freshwater: every year's provinces add up to its Canada quantity, and
    # the 2011 file's mislabelled Q/V row is read as (Q, V).
    totals = await client.get_landings(
        "freshwater", start_year=2010, end_year=2019, species="Total", limit=500
    )
    gaps = {}
    for year in totals.years:
        rows = [r for r in totals.rows if r.year == year]
        canada_q = next((r.quantity_tonnes for r in rows if r.region == "Canada"), None)
        parts = sum(r.quantity_tonnes or 0 for r in rows if r.region != "Canada")
        gaps[year] = round(abs(parts - (canada_q or 0)))
    ok &= _report(
        "freshwater provinces sum to Canada 2010-2019",
        len(gaps) == 10 and all(gap <= 150 for gap in gaps.values()),
        f"largest gap {max(gaps.values())} t ({gaps})",
    )
    ns_2011 = await client.get_landings("freshwater", year=2011, region="Nova Scotia")
    alewife = next((r for r in ns_2011.rows if r.species == "Alewife"), None)
    ok &= _report(
        "freshwater 2011 Nova Scotia alewife",
        alewife is not None and alewife.quantity_tonnes == 226.0,
        f"{alewife}",
    )
    oldest = await client.get_landings("freshwater", year=1990, region="Ontario", species="Perch")
    ok &= _report(
        "freshwater 1990 spaces as thousands separators",
        bool(oldest.rows) and oldest.rows[0].quantity_tonnes == 6483.0,
        f"{oldest.rows[0] if oldest.rows else 'none'}",
    )
    french_fw = await client.get_landings("freshwater", year=2019, region="Manitoba", lang="fr")
    ok &= _report(
        "freshwater French 2019",
        any(r.species == "Doré jaune" for r in french_fw.rows),
        f"{len(french_fw.rows)} rows",
    )

    try:
        await client.get_landings("freshwater", year=2024)
        ok &= _report("freshwater after 2019", False, "expected NotFound")
    except NotFound as err:
        ok &= _report("freshwater after 2019", True, f"NotFound: {err}")
    try:
        await client.get_landings("freshwater", start_year=1990, end_year=2019)
        ok &= _report("freshwater 30 years", False, "expected InvalidInput")
    except InvalidInput as err:
        ok &= _report("freshwater 30 years", True, f"InvalidInput: {err}")

    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
