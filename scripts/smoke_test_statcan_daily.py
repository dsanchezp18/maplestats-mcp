"""Live smoke test for the statcan.daily module's client.py: calls the real
Daily Atom feeds (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" -- a clean mocked pytest run only proves the code matches
assumptions the tests share with it, not that those assumptions are
correct.

Usage:
    uv run python scripts/smoke_test_statcan_daily.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.daily import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    all_releases = await client.get_releases("all", limit=10)
    print(f"OK: get_releases(all) -> {all_releases.returned_count} releases")
    ok &= all_releases.returned_count > 0
    sample = all_releases.releases[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.title)
    ok &= sample.url.startswith("http")

    housing = await client.get_releases("housing", limit=5)
    print(f"OK: get_releases(housing) -> {housing.returned_count} releases")
    ok &= housing.returned_count > 0

    fr = await client.get_releases("housing", lang="fr", limit=1)
    print(f"OK: get_releases(housing, lang=fr) -> {fr.returned_count} releases")
    ok &= fr.returned_count > 0
    if fr.releases:
        print("  sample fr:", fr.releases[0].model_dump())

    try:
        await client.get_releases("not_a_real_subject")
        print("FAIL: expected InvalidInput for a bogus subject")
        ok = False
    except InvalidInput:
        print("OK: bogus subject raises InvalidInput as expected")

    archive = await client.search_archive("labour force survey", start_date="2012-01-01")
    print(f"OK: search_archive('labour force survey') -> {archive.total_matched} matches")
    ok &= archive.total_matched > 50  # confirmed live: released monthly since well before 2012
    print(f"  most recent in page: {archive.entries[0].release_date if archive.entries else None}")
    ok &= all(
        e.release_date >= e2.release_date
        for e, e2 in zip(archive.entries, archive.entries[1:], strict=False)
    )

    ranged = await client.search_archive("", start_date="2012-03-01", end_date="2012-03-31")
    print(f"OK: search_archive('', 2012-03) -> {ranged.total_matched} matches")
    ok &= ranged.total_matched > 0
    ok &= all(e.release_date.month == 3 and e.release_date.year == 2012 for e in ranged.entries)

    try:
        await client.search_archive("", start_date="not-a-date")
        print("FAIL: expected InvalidInput for a bogus start_date")
        ok = False
    except InvalidInput:
        print("OK: bogus start_date raises InvalidInput as expected")

    print("\nSTATCAN DAILY SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
