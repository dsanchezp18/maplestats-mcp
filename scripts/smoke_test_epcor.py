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

    print("EPCOR SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
