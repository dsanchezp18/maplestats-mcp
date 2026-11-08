"""Live smoke test for the House of Commons open data module."""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

from maplestats_mcp.modules.ourcommons import client, expenditures
from maplestats_mcp.shared.errors import NotFound
from maplestats_mcp.shared.http import new_client


async def blocked_on_ci() -> bool:
    """True on a GitHub runner that ourcommons.ca answers with HTTP 403 (seen 2026-10-04).

    The same request succeeds from other networks, so this is a block on the
    runner's address range, not a fault in the module. Never skips off CI.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get("https://www.ourcommons.ca/members/en/search/xml")
    return response.status_code == 403


async def main() -> int:
    if await blocked_on_ci():
        print("SKIP: ourcommons.ca answers HTTP 403 to this GitHub runner")
        return 0
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

        # Members' expenditure reports: the top spender's detail CSVs must add up
        # to the quarter's summary, in English and in French.
        reports = await expenditures.list_expenditure_reports()
        latest = reports.reports[0]
        print(f"OK: {reports.total_reports} reports, latest {latest.fiscal_year} Q{latest.quarter}")
        failures += reports.total_reports < 20
        summary = await expenditures.get_member_expenditures(limit=500)
        print(f"OK: summary -> {summary.members_in_report} members, {summary.totals.total} $")
        failures += not 300 <= summary.members_in_report <= 500
        ndp = await expenditures.get_member_expenditures(caucus="NPD", limit=500, lang="fr")
        print(f"OK: NDP members in the French report -> {ndp.total_matches}")
        failures += ndp.total_matches == 0
        top = summary.members[0]
        for lang in ("en", "fr"):
            detail = await expenditures.get_member_expenditure_details(
                top.name, top.constituency, lang=lang
            )
            sums = (
                round(sum(t.total or 0.0 for t in detail.travel or []), 2),
                round(sum(h.amount or 0.0 for h in detail.hospitality or []), 2),
                round(sum(c.total or 0.0 for c in detail.contracts or []), 2),
            )
            expected = (top.travel, top.hospitality, top.contracts)
            ok = all(abs(a - (b or 0.0)) < 0.01 for a, b in zip(sums, expected, strict=True))
            print(f"{'OK' if ok else 'FAIL'}: {top.name} ({lang}) {sums} vs summary {expected}")
            failures += not ok
        try:
            await expenditures.get_member_expenditures(fiscal_year=2019, quarter=1)
            print("FAIL: a quarter before the reports did not raise")
            failures += 1
        except NotFound:
            print("OK: an unknown quarter raises NotFound")
    print("OURCOMMONS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
