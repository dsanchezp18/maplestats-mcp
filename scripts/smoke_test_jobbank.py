"""Live smoke test for the Job Bank wages module (jobbank_).

uv run python scripts/smoke_test_jobbank.py
"""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage

from maplestats_mcp.modules.jobbank import client
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)


async def main() -> int:
    ok = True
    try:
        # Checked 2026-11-03: the newest release was 2025 (resource
        # 9da94d63-b178-4a64-aeb3-b6a3bd721ad2), with 2024 and 2023 also on NOC 2021.
        found = await client.search_occupations("software")
        release = found.release
        codes = [m.noc_code for m in found.matches]
        print(f"OK: search 'software' -> {codes} in the {release.release_year} release")
        ok &= release.release_year >= 2025 and {"21231", "21232"} <= set(codes)
        ok &= release.note is None and 2023 in release.available_years

        french = await client.search_occupations("infirmières autorisées", lang="fr")
        print(f"OK: search FR -> {[(m.noc_code, m.title_fr[:40]) for m in french.matches]}")
        ok &= any(m.noc_code == "31301" for m in french.matches)

        # 2025 release: NOC 21231 in Toronto, median 56.49/hour (LFS 2023-2024).
        toronto = await client.get_wages("21231", region="Toronto")
        row = toronto.rows[0]
        print(
            f"OK: 21231 Toronto -> low {row.low_wage}, median {row.median_wage}, high "
            f"{row.high_wage} {row.wage_unit}, {row.data_source} {row.reference_period}"
        )
        ok &= row.region_code == "ER3530" and row.wage_unit == "hourly"
        ok &= row.median_wage is not None and 30 < row.median_wage < 100
        ok &= bool(row.data_source and row.reference_period)

        everywhere = await client.get_wages("21231")
        print(
            f"OK: 21231 everywhere -> {everywhere.returned_count} rows, "
            f"{everywhere.unpublished_count} unpublished"
        )
        ok &= everywhere.returned_count == 86 and everywhere.unpublished_count > 0

        ontario = await client.get_wages("21231", province="ON", published_only=True)
        ok &= all(r.province == "ON" and r.published for r in ontario.rows)

        legislators = await client.get_wages("00010", region="Canada")
        first = legislators.rows[0]
        print(f"OK: 00010 Canada -> {first.median_wage} {first.wage_unit}")
        ok &= first.wage_unit == "annual"

        compared = await client.compare_occupations(["21231", "21232", "21211"], region="ER3530")
        print(f"OK: compare in Toronto -> {[(r.noc_code, r.median_wage) for r in compared.rows]}")
        ok &= len(compared.rows) == 3 and not compared.mixed_units

        montreal = await client.compare_occupations(
            ["21231", "21232"], region="Montréal", lang="fr"
        )
        shown = [(r.occupation[:30], r.data_source) for r in montreal.rows]
        print(f"OK: compare FR Montréal -> {shown}")
        ok &= montreal.region_code == "ER2440"

        regions = await client.list_regions("QC")
        print(f"OK: Quebec regions -> {regions.returned_count}")
        ok &= regions.returned_count >= 15

        older = await client.get_wages("21231", region="Toronto", release_year=2023)
        print(f"OK: 2023 release -> {older.rows[0].median_wage} ({older.rows[0].reference_period})")
        ok &= older.release.release_year == 2023

        for label, call, exc_type in (
            ("ambiguous region", client.get_wages("21231", region="Northeast"), InvalidInput),
            ("unknown NOC", client.get_wages("99999"), NotFound),
            ("NOC 2016 release", client.get_wages("21231", release_year=2019), InvalidInput),
        ):
            try:
                await call
                print(f"FAIL: {label} did not raise")
                ok = False
            except exc_type as exc:
                print(f"OK: {label} -> {type(exc).__name__}")
    except (UpstreamError, UpstreamUnavailable) as exc:
        skip_outage("open.canada.ca", exc)

    print("\nJOB BANK SMOKE TEST PASSED" if ok else "\nJOB BANK SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
