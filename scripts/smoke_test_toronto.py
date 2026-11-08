"""Live smoke test for the City of Toronto module (open.toronto.ca DataStore tables).

Every client function is called against the live portal; the checks are
ones the published tables should keep satisfying (140 neighbourhoods, 25
wards, scores between 0 and 100), not today's exact counts.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.toronto import client


async def main() -> int:
    failures = 0

    profile = await client.get_neighbourhood_profile("Annex", characteristic="Renter")
    renter = next((r for r in profile.rows if r.characteristic == "Renter"), None)
    print(f"OK: Annex ({profile.neighbourhood_number}) renters 2016: {renter}")
    failures += renter is None or renter.value_number is None or not profile.topics
    for year in (2011, 2006, 2001):
        older = await client.get_neighbourhood_profile("72", census_year=year, limit=1)
        print(f"OK: Regent Park {year}: {older.rows[0].characteristic} = {older.rows[0].value}")
        failures += older.neighbourhood != "Regent Park" or older.total_matched < 500

    every = await client.get_apartment_evaluations(latest_only=False, limit=1)
    latest = await client.get_apartment_evaluations(limit=3)
    print(
        f"OK: RentSafeTO {every.total_matched} evaluations, {latest.total_matched} buildings; "
        f"lowest {[(e.address, e.score) for e in latest.evaluations]}"
    )
    failures += not 0 < latest.total_matched < every.total_matched
    ward = await client.get_apartment_evaluations(ward="Scarborough Southwest", limit=1)
    failures += ward.total_matched == 0
    summary = await client.summarize_apartment_scores()
    print(f"OK: wards {len(summary.groups)}, city {summary.city}")
    failures += len(summary.groups) != 25 or summary.buildings != latest.total_matched
    failures += not 0 <= (summary.city.min_score or -1) <= (summary.city.max_score or 101) <= 100
    by_type = await client.summarize_apartment_scores(group_by="property_type")
    print(f"OK: property types {[(g.key, g.buildings) for g in by_type.groups]}")

    rentals = await client.summarize_short_term_rentals()
    print(f"OK: short-term rentals {rentals.registrations} in {len(rentals.groups)} wards")
    failures += rentals.registrations == 0 or len(rentals.groups) < 25
    fsa = await client.summarize_short_term_rentals(group_by="postal_code")
    print(f"OK: busiest FSAs {[(g.key, g.registrations) for g in fsa.groups[:3]]}")

    pizza = await client.search_dinesafe(establishment="pizza", address="queen", limit=2)
    closed = await client.search_dinesafe(status="Closed", limit=2)
    print(f"OK: DineSafe pizza on Queen {pizza.total_matched}, closures {closed.total_matched}")
    print(f"    latest closure {closed.inspections[0] if closed.inspections else None}")
    failures += pizza.total_matched == 0 or closed.total_matched == 0
    failures += any("None" in (i.address or "").split() for i in pizza.inspections)

    print("TORONTO SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
