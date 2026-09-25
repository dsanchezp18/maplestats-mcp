"""Live smoke test for the EPCOR Edmonton water quality module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.epcor import client


async def main() -> int:
    failures = 0
    for plant in ("els", "rossdale"):
        daily = await client.get_daily_water_quality(plant)  # type: ignore[arg-type]
        latest = daily.readings[-1] if daily.readings else None
        print(f"OK: daily {plant} readings={len(daily.readings)} latest={latest}")
        failures += len(daily.readings) != 7 or latest is None or latest.date is None
        failures += latest is not None and latest.ph is None

    reports = await client.list_water_quality_reports()
    print(f"OK: reports total={reports.total_matches} kinds={reports.kinds_available}")
    print(f"    newest={reports.reports[0] if reports.reports else None}")
    failures += reports.total_matches < 200

    typo = await client.list_water_quality_reports(year=2025, month=3, kind="monthly-report")
    print(f"OK: 2025-03 monthly-report -> {[r.file_name for r in typo.reports]}")
    failures += typo.total_matches != 1

    print("EPCOR SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
