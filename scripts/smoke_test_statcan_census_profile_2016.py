"""Live smoke test for statcan/census_profile_2016 (2 tools).

The service lives on www12.statcan.gc.ca, which since at least 2026-10-02 answers
scripts with a Cloudflare managed challenge (HTTP 403, Cf-Mitigated: challenge).
This script does not try to pass the challenge. It asks the service once and
then checks whichever state it finds:

- blocked: both tools must raise the "unavailable" error that names the
  alternatives, and the alternative the error names (WDS table 17100123, the
  2016 census indicator profile) must answer;
- reachable: both tools must return real data (the block was lifted).

Usage:
    uv run python scripts/smoke_test_statcan_census_profile_2016.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.census_profile_2016 import client
from maplestats_mcp.modules.statcan.wds import client as wds
from maplestats_mcp.shared.errors import CloudflareChallenge


def check(ok: bool, label: str, detail: object = "") -> bool:
    print(f"{'OK  ' if ok else 'FAIL'}: {label}" + (f" -> {detail}" if detail != "" else ""))
    return ok


async def main() -> int:
    ok = True
    try:
        geographies = await client.list_geographies("canada_provinces_territories")
    except CloudflareChallenge as exc:
        print("www12 is behind the Cloudflare challenge: checking blocked-detection.")
        ok &= check(
            "Cloudflare" in str(exc) and "17100123" in str(exc),
            "list_geographies reports the block",
            str(exc)[:120],
        )
        try:
            await client.get_data("2016A000011124")
            ok &= check(False, "get_data must not succeed while blocked")
        except CloudflareChallenge:
            ok &= check(True, "get_data reports the block")
        meta = await wds.get_cube_metadata(17100123, member_limit=3)
        ok &= check(
            "2016" in meta.cube_title_en,
            "alternative: WDS 17100123 answers",
            meta.cube_title_en[:80],
        )
    else:
        print("www12 answered: the block is lifted, checking real data.")
        ok &= check(
            geographies.returned_count > 10,
            "list_geographies returns data",
            geographies.returned_count,
        )
        canada = next(g for g in geographies.geographies if g.geo_name == "Canada")
        data = await client.get_data(canada.geo_uid, topic="population")
        ok &= check(len(data.values) > 0, "get_data returns data", len(data.values))

    print("\nSTATCAN CENSUS PROFILE 2016 SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
