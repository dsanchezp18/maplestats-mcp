"""Live smoke test for the statcan.census_profile module's client.py: calls
the real 2021 Census Profile SDMX API (not mocks), per AGENTS.md's "lesson
from auditing the StatCan module" -- a clean mocked pytest run only proves
the code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_statcan_census_profile.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.census_profile import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    geo = await client.search_geography("canada_provinces_territories", "ontario")
    print(f"OK: search_geography(canada_provinces_territories, 'ontario') -> {geo.total_matched}")
    ok &= geo.total_matched == 1
    ontario_code = geo.matches[0].code
    ok &= ontario_code == "2021A000235"

    char = await client.search_characteristic("population, 2021")
    print(f"OK: search_characteristic('population, 2021') -> {char.total_matched}")
    ok &= char.total_matched >= 1
    population_char = next(m.code for m in char.matches if m.name == "Population, 2021")

    data = await client.get_data("canada_provinces_territories", [ontario_code], [population_char])
    print(f"OK: get_data -> {len(data.values)} value(s), release_date={data.release_date}")
    ok &= len(data.values) == 1
    value = data.values[0]
    print("  sample:", value.model_dump())
    ok &= value.geography_name.startswith("Ontario")
    ok &= value.value is not None and value.value > 10_000_000  # confirmed live: 14,223,942

    csd = await client.search_geography("census_subdivisions", "toronto", limit=5)
    print(f"OK: search_geography(census_subdivisions, 'toronto') -> {csd.total_matched}")
    ok &= csd.total_matched > 0

    try:
        await client.get_data("not_a_real_level", [ontario_code], [population_char])
        print("FAIL: expected InvalidInput for a bogus level")
        ok = False
    except InvalidInput:
        print("OK: bogus level raises InvalidInput as expected")

    print("\nSTATCAN CENSUS PROFILE SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
