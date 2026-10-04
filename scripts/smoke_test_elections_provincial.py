"""Live smoke test for provincial general election results (QC, AB, BC, SK, MB).

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
    ("sk", "2024-10-28"): {"Saskatchewan Party": 34, "New Democratic": 27},
    ("sk", "2020-10-26"): {"Saskatchewan Party": 48, "New Democratic": 13},
    ("sk", "2016-04-04"): {"Saskatchewan Party": 51, "New Democratic": 10},
    ("sk", "2011-11-07"): {"Saskatchewan Party": 49, "New Democratic": 9},
    ("mb", "2023-10-03"): {"New Democratic": 34, "Progressive Conservative": 22, "Liberal": 1},
    ("mb", "2019-09-10"): {"Progressive Conservative": 36, "New Democratic": 18, "Liberal": 3},
    ("mb", "2016-04-19"): {"Progressive Conservative": 40, "New Democratic": 14, "Liberal": 3},
    ("mb", "2011-10-04"): {"New Democratic": 37, "Progressive Conservative": 19, "Liberal": 1},
    ("mb", "2007-05-22"): {"New Democratic": 36, "Progressive Conservative": 19, "Liberal": 2},
    ("mb", "2003-06-03"): {"New Democratic": 35, "Progressive Conservative": 20, "Liberal": 2},
    ("mb", "1999-09-21"): {"New Democratic": 32, "Progressive Conservative": 24, "Liberal": 1},
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

        if "sk" in provinces:
            # Split polls and the 2011 workbook's misspelled sheet must come through.
            result = await client.get_results("sk", "2011", district="nutana", winners_only=True)
            if not result.rows or result.rows[0].district != "Saskatoon Nutana":
                print(f"FAIL: 2011 Saskatoon Nutana found {result.rows[:1]}")
                failures += 1
            else:
                print(
                    f"OK: 2011 nutana -> {result.rows[0].candidate} ({result.rows[0].party_code})"
                )

        if "mb" in provinces:
            # One single-workbook election (1999) and one zip of per-division workbooks
            # (2023), read by range; both divisions add up to the official totals.
            for year, district in (("1999", "Brandon West"), ("2023", "Fort Rouge")):
                areas = await client.get_voting_areas("mb", district, year)
                if not areas.areas or areas.areas_valid_votes != areas.district_valid_votes:
                    print(
                        f"FAIL: mb {year} {district} voting areas sum to "
                        f"{areas.areas_valid_votes}, official {areas.district_valid_votes}"
                    )
                    failures += 1
                else:
                    print(
                        f"OK: mb {year} {district} -> {len(areas.areas)} voting areas, "
                        f"{areas.areas_valid_votes} valid votes"
                    )

        blocked = client.list_elections()
        if not any(b.province == "on" for b in blocked.blocked):
            print("FAIL: Ontario is not listed as blocked")
            failures += 1
    print("ELECTIONS PROVINCIAL SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
