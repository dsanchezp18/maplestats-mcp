"""Live smoke test for the statcan.indicators module's client.py: calls the
real Indicators JSON feeds (not mocks), per AGENTS.md's "lesson from
auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_indicators.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.indicators import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    econ = await client.get_indicators("economic", limit=5)
    print(f"OK: get_indicators(economic) -> {econ.returned_count} of {econ.total_matched}")
    ok &= econ.total_matched > 0
    sample = econ.indicators[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.title)
    ok &= bool(sample.value)

    population = await client.get_indicators("all", "population estimate")
    print(f"OK: get_indicators(all, 'population estimate') -> {population.total_matched}")
    ok &= population.total_matched > 0

    canada_only = await client.get_indicators("all", "population estimate", geo_code=0)
    print(f"OK: get_indicators(geo_code=0) -> {canada_only.total_matched}")
    ok &= canada_only.total_matched > 0
    ok &= all(i.geo_code == 0 for i in canada_only.indicators)

    fr = await client.get_indicators("homepage", lang="fr", limit=3)
    print(f"OK: get_indicators(homepage, lang=fr) -> {fr.returned_count}")
    ok &= fr.returned_count > 0

    try:
        await client.get_indicators("not_a_real_dataset")
        print("FAIL: expected InvalidInput for a bogus dataset")
        ok = False
    except InvalidInput:
        print("OK: bogus dataset raises InvalidInput as expected")

    print("\nSTATCAN INDICATORS SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
