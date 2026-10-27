"""Live smoke test for the NWT Bureau of Statistics module (statsnwt.ca)."""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage

from maplestats_mcp.modules.nwt_stats import client, constants
from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client

SOURCE = "statsnwt.ca"


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


async def main() -> int:
    failures = 0
    try:
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
            # About 375 files on 2026-10-26, after the site's relaunch.
            if sum(counts.values()) < 340 or empty:
                failures += fail("expected 340+ files and every topic filled")
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

            # The page offers an export of the table it shows, with no file extension.
            export = next((f for f in gdp.files if "/download-xlsx/" in f.url), None)
            if export is None:
                failures += fail("no table export on the GDP page")
            else:
                data = await client.read_file(export.url, limit=3)
                print(f"OK: export {export.title[:50]!r} -> {data.total_rows} rows")
                if not data.rows:
                    failures += fail("GDP table export has no rows")

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

            census = await client.list_files(
                topic="census", limit=constants.FILES_LIMIT_MAX, lang="fr"
            )
            years = {f.section.split(" > ")[0] for f in census.files if f.section}
            print(f"OK: census -> {census.total_files} files, blocks {sorted(years)}")
            if census.total_files < 90 or len(years) != 6:
                failures += fail("census page should list 90+ files in six census-year blocks")
            # The page links its files on a staging host; they are read from statsnwt.ca.
            age = next((f for f in census.files if "Age-gender" in f.url), None)
            if age is None:
                failures += fail("no 2021 census age file")
            else:
                data = await client.read_file(age.url, sheet="Age & Gender", limit=3)
                print(f"OK: census age {age.url} -> {data.total_rows} rows")
                if not data.rows:
                    failures += fail("census age file has no rows")
    except (UpstreamError, UpstreamUnavailable) as exc:
        skip_outage(SOURCE, exc)
    print("NWT STATS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
