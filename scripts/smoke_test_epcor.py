"""Live smoke test for the EPCOR Edmonton water quality module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.epcor import client


async def main() -> int:
    failures = 0
    for plant in ("els", "rossdale"):
        daily = await client.get_daily_water_quality(plant)  # type: ignore[arg-type]
        # The newest rows can be blank or partial (the page lists the current day
        # before it is published; Rossdale's pH lags), so check the newest day
        # that has a pH, not the last row.
        with_ph = [r for r in daily.readings if r.ph is not None]
        latest = with_ph[-1] if with_ph else None
        print(f"OK: daily {plant} readings={len(daily.readings)} latest_with_ph={latest}")
        failures += len(daily.readings) != 7 or latest is None or latest.date is None
        failures += daily.provenance.as_of is None

    print("EPCOR SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
