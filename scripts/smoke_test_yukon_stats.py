"""Live smoke test for the Yukon Bureau of Statistics module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.yukon_stats import client
from maplestats_mcp.shared.http import new_client


async def main() -> int:
    failures = 0
    async with new_client():
        listing = await client.list_tables()
        datasets = {t.dataset for t in listing.tables}
        print(f"OK: list_tables -> {listing.total_tables} tables in {len(datasets)} datasets")
        if listing.total_tables < 50 or len(datasets) < 8:
            print("FAIL: expected 50+ tables in 8+ datasets")
            failures += 1

        rent = (await client.list_tables(query="rent vacancy")).tables
        if not rent:
            print("FAIL: no rent and vacancy table")
            return 1
        data = await client.query_table(rent[0].url, filters={"region": "Yukon"}, limit=3)
        if not data.rows or "footnotes" in data.all_columns:
            print("FAIL: rent table returned no rows or kept the footnotes column")
            failures += 1
        else:
            print(f"OK: rent -> {data.total_rows} Yukon rows, first {data.rows[0]['median_rent']}")

        population = (await client.list_tables(query="population estimates age")).tables
        data = await client.query_table(
            population[0].url,
            filters={"region": "Whitehorse - City", "sex": "Total"},
            columns=["year", "month", "region", "all_ages"],
            limit=1,
        )
        if not data.rows or not data.rows[0]["all_ages"].isdigit():
            print("FAIL: Whitehorse population not found")
            failures += 1
        else:
            print(f"OK: Whitehorse population -> {data.rows[0]}")
    print("YUKON STATS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
