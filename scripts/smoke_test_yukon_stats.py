"""Live smoke test for the Yukon Bureau of Statistics module."""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_outage, verdict

from maplestats_mcp.modules.yukon_stats import client
from maplestats_mcp.shared.http import new_client


async def main() -> int:
    failures = 0
    async with new_client():
        try:
            failures = await _checks()
        # open.yukon.ca has answered automated clients with a Cloudflare challenge
        # since 2026-11-10: an outage to report as a skip, not a regression.
        except Exception as exc:  # noqa: BLE001 - only an outage is skipped
            skip_outage("open.yukon.ca", exc)
    return verdict("YUKON STATS", not failures)


async def _checks() -> int:
    failures = 0
    listing = await client.list_tables(limit=200)
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
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
