"""Live smoke test for federal election results (38th to 45th general elections)."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.elections_results import client, constants
from maplestats_mcp.shared.http import new_client


async def check_election(number: int) -> int:
    print(f"--- general election {number}")
    failures = 0
    for table in constants.TABLES:
        result = await client.get_table(number, table, limit=1)  # type: ignore[arg-type]
        if result.total_rows < 1:
            print(f"FAIL: {table} returned no rows")
            failures += 1
        else:
            print(f"OK: {table} -> {result.total_rows} rows, {len(result.columns)} columns")

    winners = await client.get_table(number, "candidates", winners_only=True, limit=1000)
    expected = {45: 343, 44: 338, 43: 338, 42: 338, 41: 308, 40: 308, 39: 308, 38: 308}[number]
    if winners.total_rows != expected:
        print(f"FAIL: {winners.total_rows} winners, expected {expected} seats")
        failures += 1
    else:
        print(f"OK: {winners.total_rows} winners = {expected} seats")

    alberta = await client.get_table(number, "district_results", province="Alberta", limit=100)
    print(f"OK: Alberta ridings -> {alberta.total_rows}")
    if alberta.total_rows < 20:
        failures += 1
    return failures


async def main() -> int:
    numbers = [int(a) for a in sys.argv[1:]] or sorted(constants.ELECTIONS)
    failures = 0
    async with new_client():
        for number in numbers:
            failures += await check_election(number)
    print("ELECTIONS RESULTS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
