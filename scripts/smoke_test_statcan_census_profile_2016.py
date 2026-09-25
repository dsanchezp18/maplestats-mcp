"""Live smoke test for the statcan.census_profile_2016 module's client.py:
calls the real 2016 Census Profile Web Data Service (not mocks), per
AGENTS.md's "lesson from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_census_profile_2016.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.census_profile_2016 import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    geos = await client.list_geographies("canada_provinces_territories")
    print(f"OK: list_geographies(canada_provinces_territories) -> {geos.returned_count}")
    ok &= geos.returned_count == 14  # confirmed live: Canada + 10 provinces + 3 territories
    canada = next(g for g in geos.geographies if g.geo_name == "Canada")
    print("  Canada:", canada.model_dump())

    data = await client.get_data(canada.geo_uid, topic="population")
    print(f"OK: get_data(Canada, population) -> {data.returned_count} value(s)")
    ok &= data.returned_count > 0
    pop_2016 = next(v for v in data.values if v.label == "Population, 2016")
    print("  Population, 2016:", pop_2016.model_dump())
    ok &= pop_2016.total_value == 35151728.0  # confirmed live figure

    fr = await client.get_data(canada.geo_uid, topic="population", lang="fr")
    print(f"OK: get_data(Canada, population, lang=fr) -> {fr.returned_count} value(s)")
    ok &= fr.returned_count > 0

    on_geos = await client.list_geographies("census_divisions", province_territory="ontario")
    print(f"OK: list_geographies(census_divisions, ontario) -> {on_geos.returned_count}")
    ok &= on_geos.returned_count > 0

    try:
        await client.get_data("not-a-real-dguid", topic="not_a_real_topic")
        print("FAIL: expected InvalidInput for a bogus topic")
        ok = False
    except InvalidInput:
        print("OK: bogus topic raises InvalidInput as expected")

    print("\nSTATCAN CENSUS PROFILE 2016 SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
