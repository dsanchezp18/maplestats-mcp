"""Live smoke test for IRCC's monthly open data tables, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_ircc_monthly.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.ircc.monthly import client
from maplestats_mcp.shared.errors import UpstreamError


async def main() -> int:
    ok = True

    catalogue = await client.list_tables()
    everything = await client.list_tables(include_archived=True)
    print(f"OK: {catalogue.returned_count} current tables, {everything.total_tables} in all")
    # confirmed live 2026-09-25: 96 CSV resources in 12 datasets
    ok &= everything.total_tables >= 90 and catalogue.returned_count >= 55

    pr = await client.describe_table("ODP-PR-PT_IMMCAT")
    print(f"OK: PR by province {pr.first_period}..{pr.last_period}, {pr.row_count} rows")
    ok &= pr.first_period == "2015-01" and (pr.last_period or "") >= "2026-07"

    canada = await client.query_table(
        "ODP-PR-PT_IMMCAT", year_from=2024, year_to=2024, period="year", group_by=[]
    )
    total = canada.rows[0].value if canada.rows else None
    print(f"OK: Canada PR admissions 2024 -> {total}")
    # IRCC's published 2024 total is 483,640; rounded cells summed gave
    # 482,570 on 2026-09-26 (within 0.3%).
    ok &= total is not None and abs(total - 483_640) < 483_640 * 0.02

    ab = await client.query_table(
        "ODP-PR-PT_IMMCAT",
        {"province_territory": "Alberta"},
        year_from=2024,
        year_to=2024,
        period="year",
        group_by=[],
    )
    value = ab.rows[0].value if ab.rows else None
    print(f"OK: Alberta PR admissions 2024 -> {value}")
    ok &= value is not None and 40_000 < value < 90_000

    citz = await client.query_table(
        "ODP-TR-Study-IS_CITZ",
        year_from=2025,
        year_to=2025,
        period="year",
        group_by=["country_of_citizenship"],
        sort="value_desc",
        limit=3,
    )
    print("OK: top study-permit countries 2025 ->", [r.dimensions for r in citz.rows])
    ok &= citz.returned_count == 3

    dli = await client.describe_table("ODP-TR-Study-DLI_name_PT_Inst_type", lang="fr")
    print("OK: DLI table dimensions ->", [d.key for d in dli.dimensions])
    ok &= any("learning" in d.key for d in dli.dimensions)

    for comma_file in ("ODP-Syrian_Refugees-Admissions-SkillLevel", "ODP-Afghan-AgeGroup"):
        described = await client.describe_table(comma_file)
        print(f"OK: {comma_file} (comma-separated) -> {described.row_count} rows")
        ok &= described.row_count > 0

    try:
        await client.describe_table("ODP-PR-FRE_SP_IMMCAT")
        print("NOTE: ODP-PR-FRE_SP_IMMCAT now has a header row; update the findings.")
    except UpstreamError:
        print("OK: headerless ODP-PR-FRE_SP_IMMCAT reported as unreadable")

    print("\nIRCC MONTHLY SMOKE TEST PASSED" if ok else "\nIRCC MONTHLY SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
