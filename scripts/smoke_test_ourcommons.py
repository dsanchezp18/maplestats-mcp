"""Live smoke test for the House of Commons open data module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.ourcommons import client
from maplestats_mcp.shared.http import new_client


async def main() -> int:
    failures = 0
    async with new_client():
        members = await client.list_members(limit=400)
        print(f"OK: list_members -> {members.total_members} sitting members")
        if not 300 <= members.total_members <= 343:
            print("FAIL: expected 300 to 343 sitting members")
            failures += 1

        standings = await client.get_party_standings()
        sitting = sum(t.seats for t in standings.by_party if t.party != "Vacant")
        print(f"OK: party standings -> {standings.total_seats} seats, {sitting} filled")
        if standings.total_seats < 338 or sitting != members.total_members:
            print("FAIL: standings do not match the member list")
            failures += 1

        roles = await client.get_member_roles(members.members[0].person_id)
        if not roles.seats or not roles.election_history:
            print("FAIL: member roles have no seat or election history")
            failures += 1
        else:
            print(f"OK: roles of {roles.last_name} -> {len(roles.election_history)} elections")

        former = await client.get_member_roles(9, lang="fr")
        if former.last_name != "Baker" or len(former.seats) < 2:
            print("FAIL: former member 9 did not come back as Baker with two seats")
            failures += 1
        else:
            print("OK: a former member's history (French feed)")

        ministry = await client.get_ministry()
        if not ministry.ministers or ministry.ministers[0].title != "Prime Minister":
            print("FAIL: the Ministry does not start with the Prime Minister")
            failures += 1
        else:
            print(f"OK: Ministry -> {len(ministry.ministers)} ministers")
    print("OURCOMMONS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
