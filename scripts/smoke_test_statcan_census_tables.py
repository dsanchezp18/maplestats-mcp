"""Live smoke test for statcan/census_tables (2 tools).

Same situation as smoke_test_statcan_census_profile_2016.py: these tables are on
www12.statcan.gc.ca, behind a Cloudflare managed challenge since at least
2026-10-02. Nothing here tries to pass it. The script checks whichever state it
finds:

- blocked: search and get_downloads must raise the "unavailable" error that
  names the alternatives (not a misleading NotFound), and the archive tools
  must say so in provenance.limits;
- reachable: search must find a table and get_downloads must list its files.

Usage:
    uv run python scripts/smoke_test_statcan_census_tables.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.census_profile_archive import client as archive
from maplestats_mcp.modules.statcan.census_tables import client
from maplestats_mcp.shared.errors import CloudflareChallenge, NotFound


def check(ok: bool, label: str, detail: object = "") -> bool:
    print(f"{'OK  ' if ok else 'FAIL'}: {label}" + (f" -> {detail}" if detail != "" else ""))
    return ok


async def main() -> int:
    ok = True
    link = await archive.get_download_link(2016, "canada_provinces_territories", "csv")
    try:
        found = await client.search("income", release="2016", limit=3)
    except CloudflareChallenge as exc:
        print("www12 is behind the Cloudflare challenge: checking blocked-detection.")
        ok &= check(
            "Cloudflare" in str(exc) and "borealis_search_ivt" in str(exc),
            "search reports the block",
            str(exc)[:120],
        )
        try:
            await client.get_downloads("110192", release="2016")
            ok &= check(False, "get_downloads must not succeed while blocked")
        except CloudflareChallenge:
            ok &= check(True, "get_downloads reports the block, not NotFound")
        except NotFound:
            ok &= check(False, "get_downloads must not say NotFound while blocked")
        ok &= check(
            link.provenance.limits is not None and "Cloudflare" in link.provenance.limits,
            "archive download link carries the block note",
        )
    else:
        print("www12 answered: the block is lifted, checking real data.")
        ok &= check(found.total_matched > 0, "search finds tables", found.total_matched)
        downloads = await client.get_downloads(found.tables[0].pid, release="2016")
        ok &= check(any(d.available for d in downloads.downloads), "get_downloads lists files")
        ok &= check(link.provenance.limits is None, "archive link has no block note")

    print("\nSTATCAN CENSUS TABLES SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
