"""Live smoke test for the Canadian Dairy Commission module, per AGENTS.md.

Covers every cdc_ tool in both languages, with values checked against
the CDC pages on 2026-09-26.

Usage:
    uv run python scripts/smoke_test_cdc.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from maplestats_mcp.modules.cdc import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    catalogue = client.catalogue("fr")
    print("OK: catalogue ->", [d.key for d in catalogue.datasets], len(catalogue.related_sources))
    ok &= len(catalogue.datasets) == 5 and catalogue.datasets[0].title.startswith("Prix")

    current = await client.get_component_prices()
    print(
        f"OK: component prices {current.year_from} -> {current.row_count} rows, "
        f"latest {current.rows[-1].effective_date} {current.rows[-1].milk_class}"
    )
    ok &= current.row_count >= 6 and current.year_from == current.year_to

    history = await client.get_component_prices(2024, 2025, milk_class="5(a)")
    first = history.rows[0]
    print(f"OK: 5(a) 2024-2025 -> {history.row_count} rows, first {first}")
    ok &= history.row_count == 24 and history.milk_class == "5(a)"
    ok &= len(history.source_files) == 2

    jan_2025 = await client.get_component_prices(2025, 2025, milk_class="3d")
    row = jan_2025.rows[0]
    print(f"OK: 3(d) Jan 2025 -> {row.butterfat_per_kg}, {row.protein_per_kg}")
    # From pricing_history_2025.csv: 3D,2025-01-01,11.3584,9.7089,0.8921.
    ok &= (row.butterfat_per_kg, row.protein_per_kg, row.other_solids_per_kg) == (
        11.3584,
        9.7089,
        0.8921,
    )

    early = await client.get_component_prices(2002, 2002, lang="fr")
    print(f"OK: 2002 -> classes {sorted({r.milk_class for r in early.rows})}, notes fr")
    ok &= {r.milk_class_code for r in early.rows} == {"4A", "5A", "5B", "5C"}
    ok &= early.notes[0].startswith("Les prix")

    four_m = await client.get_component_prices(2023, 2023, milk_class="4(m)")
    print(
        f"OK: 4(m) 2023 butterfat all None -> {all(r.butterfat_per_kg is None for r in four_m.rows)}"
    )
    ok &= all(r.butterfat_per_kg is None for r in four_m.rows) and four_m.row_count == 12

    try:
        await client.get_component_prices(2020, 2020, milk_class="2(a)")
        ok = False
        print("FAIL: class 2(a) did not raise")
    except InvalidInput as exc:
        print("OK: class 2(a) ->", type(exc).__name__)

    support = await client.get_butter_support_prices()
    newest = support.rows[0]
    print(f"OK: support prices -> {support.row_count} rows, newest {newest}")
    ok &= newest.butter_per_kg is not None and newest.butter_per_kg > 10
    may_2024 = next(r for r in support.rows if r.effective_label.startswith("2024"))
    ok &= may_2024.effective_date == date(2024, 5, 1) and may_2024.butter_per_kg == 10.3505

    support_fr = await client.get_butter_support_prices(lang="fr")
    ok &= support_fr.source_page.endswith("/fr/node/720") and support_fr.rows == support.rows

    quota = await client.get_national_quota()
    print(
        f"OK: quota latest year {quota.year_from} -> {[(r.period, r.total_quota_kg_butterfat) for r in quota.rows[:3]]}"
    )
    ok &= quota.row_count >= 1

    quota_2026 = await client.get_national_quota(2026, 2026)
    ok &= quota_2026.rows[0].period == "2026-01"
    ok &= quota_2026.rows[0].total_quota_kg_butterfat == 34_391_869

    span = await client.get_national_quota(2017, 2023, lang="fr")
    march_2023 = next(r for r in span.rows if r.period == "2023-03")
    dec_2017 = next(r for r in span.rows if r.period == "2017-12")
    print(f"OK: quota 2017-2023 -> {span.row_count} rows; notes {span.notes[1:]}")
    ok &= (
        march_2023.total_quota_kg_butterfat is None and march_2023.published_value == "34,889,4085"
    )
    ok &= (
        dec_2017.total_quota_kg_butterfat == 32_462_282
        and dec_2017.change_from_year_ago_pct == 4.67
    )
    ok &= any("2018-12" in note for note in span.notes)
    ok &= span.row_count == 7 * 12 - 1

    try:
        await client.get_national_quota(2010, 2010)
        ok = False
        print("FAIL: quota 2010 did not raise")
    except NotFound as exc:
        print("OK: quota 2010 ->", exc)

    classes = await client.get_milk_classes()
    four_a = next(c for c in classes.classes if c.milk_class == "4(a)")
    print(f"OK: milk classes -> {classes.class_count}, 4(a) has {len(four_a.products)} products")
    ok &= classes.class_count == 31 and len(four_a.products) == 6

    cheese_fr = await client.get_milk_classes("3(c)", lang="fr")
    print(
        "OK: 3(c) fr ->", [c.milk_class for c in cheese_fr.classes], cheese_fr.classes[0].products
    )
    ok &= len(cheese_fr.classes) == 6 and cheese_fr.classes[0].products == ["Féta."]

    production = await client.query_market_data("production", province="ON", limit=3)
    print(
        f"OK: ON production -> {production.total_matched} months, latest "
        f"{production.latest_date}: {production.rows[0].value} {production.rows[0].unit}"
    )
    ok &= production.total_matched >= 120 and production.rows[0].unit == "L"

    sales = await client.query_market_data(
        "sales_p10", milk_class="4A", segment="butterfat_revenue", date_from="2026", limit=12
    )
    print(f"OK: P10 4A butterfat revenue 2026 -> {sales.total_matched} rows, {sales.rows[0]}")
    ok &= sales.total_matched >= 6 and all(r.unit == "$" for r in sales.rows)

    west = await client.query_market_data(
        "sales_by_region",
        region="ouest",
        milk_class="1",
        date_from="2026-06",
        date_to="2026-06",
        lang="fr",
    )
    print(f"OK: West class 1 June 2026 fr -> {west.total_matched}, {west.rows[0].segment!r}")
    ok &= west.total_matched > 0 and all(r.region == "Ouest" for r in west.rows)

    farms = await client.query_market_data("farms", province="QC")
    print(f"OK: QC farms -> {[(r.period_end.isoformat(), r.value) for r in farms.rows[:3]]}")
    ok &= farms.total_matched >= 9 and farms.rows[0].unit == "count"

    print("\nCDC SMOKE TEST PASSED" if ok else "\nCDC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
