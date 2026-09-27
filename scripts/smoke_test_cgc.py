"""Live smoke test for the Canadian Grain Commission module, per AGENTS.md.

Calls every client function against grainscanada.gc.ca. Reference values
were read from the CGC's own Excel report for week 7 of 2026-27 on
2026-09-26 (Primary worksheet: canola deliveries 55.1, 217.7, 91.8 and 2.6
thousand tonnes in Manitoba, Saskatchewan, Alberta and British Columbia,
367.2 in total); past-year checks use completed crop years, which do not
change.

Usage:
    uv run python scripts/smoke_test_cgc.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.cgc import client


def check(ok: bool, label: str) -> bool:
    print(("OK:   " if ok else "FAIL: ") + label)
    return ok


async def main() -> int:
    ok = True

    latest = await client.describe_weekly()
    sheets = {w.worksheet for w in latest.worksheets}
    ok &= check(
        len(sheets) == 12 and {"Primary", "Terminal Exports", "Summary"} <= sheets,
        f"weekly describe {latest.crop_year}: {len(sheets)} worksheets, "
        f"latest week {latest.latest_week} ending {latest.latest_week_ending}",
    )
    ok &= check(
        latest.latest_week_ending is not None
        and (client._today() - latest.latest_week_ending).days < 21,
        "latest week ended less than three weeks ago",
    )

    week7 = await client.query_weekly(
        "Primary",
        crop_year="2026-27",
        metric="Deliveries",
        period="Current Week",
        grain="Canola",
        week_from=7,
        week_to=7,
    )
    by_region = {r.region: r.ktonnes for r in week7.rows}
    ok &= check(
        by_region
        == {"Manitoba": 55.1, "Saskatchewan": 217.7, "Alberta": 91.8, "British Columbia": 2.6},
        f"2026-27 week 7 canola deliveries by province: {by_region}",
    )
    summed = await client.query_weekly(
        "Primary",
        crop_year="2026-27",
        metric="Deliveries",
        period="Current Week",
        grain="Canola",
        week_from=7,
        week_to=7,
        group_by=["grain"],
    )
    ok &= check(
        len(summed.rows) == 1 and round(summed.rows[0].ktonnes or 0, 1) == 367.2,
        f"summed over provinces: {[r.ktonnes for r in summed.rows]}",
    )

    # Older layouts: 2013-14 (csv/ folder, "1,191.10" values), 2017-18
    # (grain_week first), and the French file of 2025-26 (headers without
    # accents, Windows-1252).
    for year in ("2013-14", "2017-18", "2024-25"):
        exports = await client.query_weekly(
            "Terminal Exports",
            crop_year=year,
            period="Crop Year",
            grain="Wheat",
            latest_week_only=True,
            group_by=["grain"],
        )
        row = exports.rows[0] if exports.rows else None
        ok &= check(
            row is not None and (row.ktonnes or 0) > 10_000,
            f"{year} crop-year wheat terminal exports, week {exports.latest_week}: "
            f"{row.ktonnes if row else None}",
        )

    french = await client.query_weekly(
        "Silos primaires",
        crop_year="2025-26",
        lang="fr",
        metric="Livraisons",
        period="Campagne agricole",
        grain="Blé",
        latest_week_only=True,
        group_by=["grain"],
    )
    ok &= check(
        len(french.rows) == 1 and (french.rows[0].ktonnes or 0) > 10_000,
        f"fr 2025-26 wheat deliveries to date: {[(r.grain, r.ktonnes) for r in french.rows]}",
    )

    described = await client.describe_exports()
    ok &= check(
        described.first_month == "2013-01"
        and described.latest_month is not None
        and described.latest_month >= "2026-05"
        and "China P.R." in described.destinations,
        f"exports describe: {described.first_month} to {described.latest_month}, "
        f"{len(described.destinations)} destinations",
    )
    canola = await client.query_exports(
        grain="Canola", destination="China P.R.", year_from=2025, year_to=2025, frequency="year"
    )
    ok &= check(
        len(canola.rows) == 1
        and 1_000 < canola.rows[0].ktonnes < 10_000
        and canola.rows[0].months == 12,
        f"canola to China 2025: {[(r.period, r.ktonnes, r.months) for r in canola.rows]}",
    )
    by_crop_year = await client.query_exports(
        grain="Wheat", year_from=2023, frequency="crop_year", group_by=["grain"]
    )
    ok &= check(
        any(r.period == "2024-25" and r.months == 12 for r in by_crop_year.rows)
        and any(r.period == "2022-23" and r.months == 7 for r in by_crop_year.rows),
        f"wheat by crop year: {[(r.period, round(r.ktonnes), r.months) for r in by_crop_year.rows]}",
    )
    french_exports = await client.query_exports(
        lang="fr", grain="Blé", destination="Japon", year_from=2025, year_to=2025, frequency="year"
    )
    ok &= check(
        len(french_exports.rows) == 1 and french_exports.rows[0].ktonnes > 100,
        f"fr wheat to Japan 2025: {[(r.period, r.ktonnes) for r in french_exports.rows]}",
    )

    print("\nCGC SMOKE TEST PASSED" if ok else "\nCGC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
