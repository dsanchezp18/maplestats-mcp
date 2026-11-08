"""Live smoke test for boc/surveys.py: the Business Outlook Survey, the
Canadian Survey of Consumer Expectations, Monetary Policy Report projections
and staff economic projections, resolved from Valet's groups. Checks that the
newest quarter, Report and vintage are found from the live inventory (not a
hard-coded date) in English and French, that a named period works, and that
a Report with no tables raises NotFound.

Usage:
    uv run python scripts/smoke_test_boc_surveys.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.boc import surveys
from maplestats_mcp.shared.errors import NotFound


async def main() -> int:
    ok = True
    for lang in ("en", "fr"):
        bos = await surveys.get_survey("bos", lang=lang)
        print(f"BOS {lang}: {bos.quarter}, {len(bos.rows)} rows, release {bos.release}")
        ok &= len(bos.rows) > 10 and bos.release is not None
        ok &= any(r.series == "PC1" for r in bos.rows)

        csce = await surveys.get_survey("csce", lang=lang)
        horizons = {r.series: r.value for r in csce.rows if r.series.startswith("CES_C1_")}
        print(f"CSCE {lang}: {csce.quarter}, inflation expectations {horizons}")
        ok &= len(horizons) == 4 and csce.release is not None

        mpr = await surveys.get_mpr_projection(lang=lang)
        tables = {r.table for r in mpr.rows}
        print(f"MPR {lang}: {mpr.report}, tables {sorted(tables)}, {mpr.release.link}")
        ok &= "summary" in tables

        staff = await surveys.get_staff_projections(lang=lang)
        print(f"Staff {lang}: {staff.vintage}, {[v.code for v in staff.variables]}")
        ok &= any(r.projected for r in staff.rows) and any(not r.projected for r in staff.rows)

    older = await surveys.get_survey("bos", "2019Q1")
    print(f"BOS 2019Q1: {len(older.rows)} rows")
    ok &= older.quarter == "2019Q1" and len(older.rows) > 10

    named = await surveys.get_mpr_projection("July 2026")
    ok &= named.report == "2026M07" and bool(named.rows)

    vintage = await surveys.get_staff_projections(["CIRINV", "GDP"], "2005Q2", 0)
    ok &= vintage.vintage == "2005Q2" and len(vintage.variables) == 2

    try:
        await surveys.get_mpr_projection("2025-04")
        print("FAIL: MPR 2025M04 (no tables) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: MPR 2025M04 raised NotFound: {exc}")

    print()
    print("BOC SURVEYS SMOKE TEST PASSED" if ok else "BOC SURVEYS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
