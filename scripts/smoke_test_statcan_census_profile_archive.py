"""Live smoke test for the statcan.census_profile_archive module: resolves
real download links and confirms each one actually serves a file (checked
via a streamed GET that reads only the response headers and first chunk,
never the full body -- some of these archives are hundreds of megabytes),
per AGENTS.md's "lesson from auditing the StatCan module."

Usage:
    uv run python scripts/smoke_test_statcan_census_profile_archive.py
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from maplestats_mcp.modules.statcan.census_profile_archive import client
from maplestats_mcp.shared.errors import InvalidInput


async def _check_url_serves_a_file(url: str) -> bool:
    # Confirmed live: 2016's GetFile.cfm resolver sometimes answers with
    # Content-Type: application/unknown instead of application/zip (e.g.
    # GEONO=050, aggregate dissemination areas) even though the file is
    # genuinely served -- Content-Disposition's attachment filename is
    # the reliable signal, not Content-Type, for this particular quirk.
    async with (
        httpx.AsyncClient(timeout=30.0) as http_client,
        http_client.stream("GET", url) as response,
    ):
        if response.status_code != 200:
            print(f"  FAIL: {url} -> HTTP {response.status_code}")
            return False
        content_disposition = response.headers.get("content-disposition", "")
        print(f"  OK: {url} -> {response.status_code} ({content_disposition})")
        return "attachment" in content_disposition.lower() and ".zip" in content_disposition.lower()


async def main() -> int:
    ok = True

    for year in (2001, 2006, 2011, 2016):
        levels = await client.list_geography_levels(year)
        print(f"OK: list_geography_levels({year}) -> {len(levels.levels)} levels")
        ok &= len(levels.levels) > 0
        sample_level = min(levels.levels)
        link = await client.get_download_link(year, sample_level, "csv")
        ok &= await _check_url_serves_a_file(link.url)

    try:
        await client.list_geography_levels(1996)
        print("FAIL: expected InvalidInput for 1996")
        ok = False
    except InvalidInput:
        print("OK: 1996 raises InvalidInput as expected (no bulk-download page found)")

    try:
        await client.get_download_link(2016, "not_a_real_level", "csv")
        print("FAIL: expected InvalidInput for a bogus level")
        ok = False
    except InvalidInput:
        print("OK: bogus level raises InvalidInput as expected")

    print("\nSTATCAN CENSUS PROFILE ARCHIVE SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
