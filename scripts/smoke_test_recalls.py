"""Live smoke test for the Recalls and Safety Alerts module, per AGENTS.md.

Covers recalls_search, recalls_summarize and recalls_get in both
languages, including a legacy (migrated) notice page.

Usage:
    uv run python scripts/smoke_test_recalls.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.recalls import client


async def main() -> int:
    ok = True

    latest = await client.search(limit=5)
    newest = latest.recalls[0]
    print(f"OK: {latest.total_matched} current notices, newest {newest.recall_id} {newest.title!r}")
    # confirmed live 2026-09-26: 19,687 non-archived of 34,131 notices
    ok &= latest.total_matched > 15000 and latest.returned_count == 5
    ok &= all(not r.archived for r in latest.recalls)

    food = await client.search("milk", product_type="food", agency="cfia", limit=3)
    print("OK: CFIA 'milk' ->", food.total_matched, [r.recall_id for r in food.recalls])
    ok &= food.total_matched > 10 and all(r.agency == "cfia" for r in food.recalls)

    type_one = await client.search(
        recall_class="Type I", product_type="health_product", include_archived=True, limit=3
    )
    print("OK: Type I health products ->", type_one.total_matched)
    ok &= type_one.total_matched > 500
    ok &= all("Type I" in (r.recall_class or "").split(" - ") for r in type_one.recalls)

    vehicles = await client.search(agency="transport_canada", updated_from="2025-01-01", limit=3)
    print("OK: TC since 2025 ->", [r.tc_recall_number for r in vehicles.recalls])
    ok &= vehicles.total_matched > 100 and all(r.tc_recall_number for r in vehicles.recalls)

    french = await client.search("arachides", product_type="food", include_archived=True, lang="fr")
    first_fr = french.recalls[0].title if french.recalls else ""
    print(f"OK: FR 'arachides' -> {french.total_matched}, first {first_fr!r}")
    ok &= french.total_matched > 20

    years = await client.summarize("year", product_type="food")
    counts = {g.key: g.count for g in years.groups}
    print(
        "OK: food notices by year, 2023-2025 ->", [counts.get(y) for y in ("2023", "2024", "2025")]
    )
    ok &= years.total_matched > 4000 and counts.get("2024", 0) > 100

    agencies = await client.summarize("agency", include_archived=False)
    print("OK: agencies ->", [(g.key, g.count) for g in agencies.groups])
    ok &= {g.key for g in agencies.groups} == {"health_canada", "cfia", "transport_canada"}

    issues = await client.summarize("issue", product_type="food", top=5, lang="fr")
    print("OK: FR food issues ->", [(g.key, g.count) for g in issues.groups])
    ok &= len(issues.groups) == 5

    # Current layout, English: CFIA milk allergen recall, checked 2026-09-26.
    beans = await client.get_recall(82667)
    print(f"OK: 82667 -> {beans.layout} {beans.recall_class} {beans.tables[0].columns}")
    ok &= beans.layout == "current" and beans.agency == "cfia"
    ok &= beans.recall_date is not None and bool(beans.tables and beans.tables[0].rows)

    # Current layout, French: Health Canada insulin advisory with a lot table.
    insulin = await client.get_recall(82686, lang="fr")
    print(f"OK: 82686 fr -> {insulin.alert_type!r}, {len(insulin.tables[0].rows)} lots")
    ok &= insulin.alert_type == "Avis public" and len(insulin.tables[0].rows) >= 10

    # Transport Canada notice: agency_reference is the TC recall number.
    truck = await client.get_recall(vehicles.recalls[0].recall_id)
    print(f"OK: TC notice -> {truck.agency_reference}")
    ok &= truck.agency == "transport_canada" and truck.agency_reference is not None

    # Legacy (migrated, archived) CFIA notice from 2011.
    beets = await client.get_recall(48704, lang="fr")
    print(f"OK: 48704 fr -> {beets.layout}, archived={beets.archived}, {beets.recall_class}")
    ok &= beets.layout == "legacy" and beets.archived and beets.agency == "cfia"

    try:
        await client.get_recall(99999999)
        ok = False
        print("FAIL: unknown recall id did not raise")
    except Exception as exc:  # noqa: BLE001 - reporting the type is the point
        print(f"OK: unknown id -> {type(exc).__name__}")
        ok &= type(exc).__name__ == "NotFound"

    print("\nRECALLS SMOKE TEST PASSED" if ok else "\nRECALLS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
