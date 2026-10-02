"""Live smoke test for federal election results (38th to 45th general elections)."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.elections_results import (
    candidates,
    client,
    constants,
    historical,
)
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

        # Historical ridings (1867 to 2015): leading parties must match known seat counts.
        expected = {42: {"Lib": 184, "C": 99, "NDP": 44, "BQ": 10}, 41: {"C": 166, "NDP": 103}}
        for number, seats in expected.items():
            result = await historical.get_historical(election=number, limit=500)
            leaders: dict[str, int] = {}
            for riding in result.ridings:
                leaders[riding.leading_party or ""] = leaders.get(riding.leading_party or "", 0) + 1
            for party, count in seats.items():
                if leaders.get(party) != count:
                    print(
                        f"FAIL: election {number} {party} leads {leaders.get(party)}, want {count}"
                    )
                    failures += 1
        first = await historical.get_historical(election=1, limit=1)
        if first.total_ridings < 150:
            print("FAIL: first general election has too few ridings")
            failures += 1
        print("OK: historical ridings reconcile with seat counts (41st, 42nd)")

        # Candidate names before 2004: winners must match the seats of each election.
        for number, seats in {35: 295, 36: 301, 37: 301, 38: 308}.items():
            winners = await candidates.get_candidates(election=number, winners_only=True, limit=1)
            if winners.total_candidates != seats:
                print(
                    f"FAIL: election {number} has {winners.total_candidates} winners, want {seats}"
                )
                failures += 1
        named = await candidates.get_candidates(election=37, riding="st. john's", limit=50)
        if named.total_candidates < 4 or not all(c.candidate_name for c in named.candidates):
            print("FAIL: 2000 candidates for St. John's are missing")
            failures += 1
        print("OK: candidate names reconcile with seats (35th to 38th)")
    print("ELECTIONS RESULTS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
