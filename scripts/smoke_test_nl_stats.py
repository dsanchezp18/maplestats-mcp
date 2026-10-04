"""Live smoke test for the Newfoundland and Labrador Statistics Agency module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.nl_stats import client, constants
from maplestats_mcp.shared.http import new_client


async def main() -> int:
    failures = 0
    async with new_client():
        first = await client.list_files()
        second = await client.list_files(offset=len(first.files))
        if not (
            first.truncated
            and len(first.files) == constants.FILES_LIMIT_DEFAULT
            and second.offset == len(first.files)
            and {f.url for f in first.files}.isdisjoint(f.url for f in second.files)
        ):
            print("FAIL: default listing is not one compact page followed by a distinct page")
            failures += 1
        else:
            print(f"OK: list_files pages {len(first.files)} of {first.total_files}, then offset")
        listing = await client.list_files(limit=constants.FILES_LIMIT_MAX)
        print(f"OK: list_files -> {listing.total_files} files in {len(listing.topics)} topics")
        by_topic = {t: 0 for t in constants.TOPICS}
        for entry in listing.files:
            by_topic[entry.topic] += 1
        empty = [t for t, n in by_topic.items() if n == 0]
        if listing.total_files < 100 or empty:
            print(f"FAIL: expected 100+ files and every topic filled; empty topics: {empty}")
            failures += 1

        # One .xlsx and one legacy .xls, to exercise both readers.
        for fmt in ("xlsx", "xls"):
            entry = next((f for f in listing.files if f.format == fmt), None)
            if entry is None:
                print(f"FAIL: no .{fmt} file listed")
                failures += 1
                continue
            data = await client.read_file(entry.url, limit=5)
            if not data.rows or data.header_row is None:
                print(f"FAIL: {entry.url} returned no rows or header")
                failures += 1
            else:
                print(
                    f"OK: {fmt} {entry.title[:50]!r} -> {data.total_rows} rows, {data.header[:4]}"
                )

        population = await client.list_files(topic="population", query="quarterly population")
        data = await client.read_file(population.files[0].url, contains="1971", limit=1)
        if not data.rows or data.rows[0][0] != "1971":
            print("FAIL: quarterly population does not start in 1971")
            failures += 1
        else:
            print(f"OK: quarterly population first row {data.rows[0][:4]}")
    print("NL STATS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
