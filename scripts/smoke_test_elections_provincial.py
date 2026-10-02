"""Live smoke test for provincial general election results (Quebec, Alberta, BC).

Every general election must reconcile with the legislature's seat count and, for
the newest of each province, with the known seats by party.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.elections_provincial import client, constants
from maplestats_mcp.shared.http import new_client

# Known seats by party in the newest election of each province.
KNOWN_SEATS: dict[tuple[str, str], dict[str, int]] = {
    ("qc", "2022-10-03"): {"Coalition": 90, "libéral": 21, "solidaire": 11, "québécois": 3},
    ("ab", "2023-05-29"): {"UNITED CONSERVATIVE": 49, "NDP": 38},
    ("bc", "2024-10-19"): {"NDP": 47, "Conservative": 44, "Green": 2},
}


async def check_election(election: constants.Election) -> int:
    label = f"{election.province} {election.date}"
    failures = 0
    summary = await client.get_seats(election.province, election.date)
    if summary.seats_contested != election.seats or summary.seats_decided != election.seats:
        print(
            f"FAIL: {label} has {summary.seats_contested} districts and "
            f"{summary.seats_decided} winners, expected {election.seats}"
        )
        failures += 1
    else:
        print(f"OK: {label} -> {election.seats} winners, {summary.total_valid_votes} valid votes")
    if sum(p.seats for p in summary.parties) != election.seats:
        print(f"FAIL: {label} party seats do not add up to {election.seats}")
        failures += 1

    known = KNOWN_SEATS.get((election.province, election.date), {})
    for fragment, seats in known.items():
        found = [p for p in summary.parties if fragment.lower() in p.party.lower()]
        if not found or found[0].seats != seats:
            print(f"FAIL: {label} {fragment} has {found[0].seats if found else None}, want {seats}")
            failures += 1
    if known:
        print(f"OK: {label} seats by party match {known}")

    winners = await client.get_results(
        election.province, election.date, winners_only=True, limit=1000
    )
    if winners.total_rows != election.seats:
        print(f"FAIL: {label} winners_only returned {winners.total_rows}")
        failures += 1
    return failures


async def main() -> int:
    failures = 0
    provinces = set(sys.argv[1:]) or set(constants.PROVINCES)
    async with new_client():
        for election in constants.ELECTIONS:
            if election.province in provinces:
                failures += await check_election(election)

        if "qc" in provinces:
            # Accent-insensitive filter: a Quebec riding with an accent in its name.
            result = await client.get_results("qc", "2022", district="gaspe", winners_only=True)
            if not result.rows or "Gaspé" not in result.rows[0].district:
                print(f"FAIL: accent-insensitive district filter found {result.rows[:1]}")
                failures += 1
            else:
                print(f"OK: 'gaspe' -> {result.rows[0].district}, {result.rows[0].candidate}")

        blocked = client.list_elections()
        if not any(b.province == "on" for b in blocked.blocked):
            print("FAIL: Ontario is not listed as blocked")
            failures += 1
    print("ELECTIONS PROVINCIAL SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
