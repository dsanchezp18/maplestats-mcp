"""Live smoke test for the NWT Bureau of Statistics module (statsnwt.ca)."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.nwt_stats import client, constants
from maplestats_mcp.shared.http import new_client


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


async def main() -> int:
    failures = 0
    async with new_client():
        topics = await client.list_files()
        print(f"OK: list_files() -> {len(topics.topics)} topics, {topics.total_files} files")
        if len(topics.topics) != len(constants.TOPICS) or topics.files:
            failures += fail("topic list should hold every topic and no files")

        # Every topic page must still link at least one Excel file.
        counts: dict[str, int] = {}
        for topic in constants.TOPICS:
            listed = await client.list_files(topic=topic, limit=constants.FILES_LIMIT_MAX)
            counts[topic] = listed.total_files
        empty = [t for t, n in counts.items() if n == 0]
        print(f"OK: {sum(counts.values())} files in {len(counts)} topics; empty {empty}")
        if sum(counts.values()) < 600 or empty:
            failures += fail("expected 600+ files and every topic filled")
        everything = await client.search_files("xls", limit=constants.FILES_LIMIT_MAX)

        gdp = await client.list_files(topic="gdp")
        print(f"OK: list_files(gdp) -> {[f.title for f in gdp.files][:3]}")
        industry = next((f for f in gdp.files if "Industry" in f.title), None)
        if industry is None:
            failures += fail("no GDP by industry file")
        else:
            data = await client.read_file(industry.url, contains="All industries", limit=1)
            print(f"OK: GDP header {data.header_row} {data.all_columns[:4]} -> {data.rows[:1]}")
            if not data.rows or "1999" not in data.all_columns:
                failures += fail("GDP by industry should have years as columns from 1999")

        profiles = await client.search_files("aklavik profile", topic="community-data")
        print(f"OK: search aklavik -> {[(f.section, f.title) for f in profiles.files]}")
        if not profiles.files:
            failures += fail("no Aklavik community profile")
        else:
            data = await client.read_file(profiles.files[0].url, limit=3)
            print(f"OK: Aklavik profile sheet {data.sheet!r}, {data.total_rows} rows")
            if not data.rows:
                failures += fail("Aklavik profile has no rows")

        xls = next((f for f in everything.files if f.format == "xls"), None)
        if xls is None:
            failures += fail("no legacy .xls file listed")
        else:
            data = await client.read_file(xls.url, limit=3)
            print(f"OK: xls {xls.title[:50]!r} -> sheets {[s.name for s in data.sheets][:4]}")
            if not data.sheets:
                failures += fail(".xls file has no sheets")

        # A workbook of comparable sheets returns the sheet list, then reads one.
        lfs = await client.search_files("LFS100", topic="labour-force")
        if not lfs.files:
            failures += fail("no LFS100 labour force workbook")
        else:
            listing = await client.read_file(lfs.files[0].url)
            data = await client.read_file(lfs.files[0].url, sheet="Age", header_rows=2, limit=3)
            print(
                f"OK: LFS100 chosen_by={listing.sheet_chosen_by} sheets="
                f"{[s.name for s in listing.sheets]}; Age columns {data.all_columns[:4]}"
            )
            if listing.sheet is not None or not data.rows:
                failures += fail("LFS100 should list its sheets, then read 'Age'")

        census = await client.list_files(topic="census-2021", lang="fr")
        print(f"OK: census-2021 -> {census.total_files} files; licence {census.licence[:40]!r}")
        if census.total_files < 20:
            failures += fail("2021 Census page should list 20+ files")
    print("NWT STATS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
