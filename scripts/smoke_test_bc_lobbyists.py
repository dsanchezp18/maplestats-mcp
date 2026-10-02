"""Live smoke test for the BC lobbyists module (every client function).

uv run python scripts/smoke_test_bc_lobbyists.py

Downloads the registrations zip (28 MB) and the activity reports zip (5.5 MB)
once each; the module caches the parsed result for the run.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.bc_lobbyists import client
from maplestats_mcp.shared.errors import NotFound


async def main() -> int:
    ok = True

    # Counts confirmed live 2026-10-02: 6,661 current registrations of 26,925 versions.
    health = await client.search_registrations(subject_matter="Health", status="active", limit=5)
    print(f"OK: active Health registrations -> {health.total_matched}, {health.by_kind}")
    ok &= health.total_matched >= 100 and health.returned_count == 5
    ok &= all(r.status == "active" for r in health.registrations)

    dental = await client.search_registrations(client="BC Dental Association")
    print(f"OK: BC Dental Association -> {[r.registration_number for r in dental.registrations]}")
    ok &= dental.total_matched >= 1 and dental.registrations[0].lobbyist_count >= 1

    consultant = await client.search_registrations(
        kind="consultant", firm="Strategies 360", limit=3
    )
    print(f"OK: consultant firm 'Strategies 360' -> {consultant.total_matched}")
    ok &= consultant.total_matched >= 10

    period = await client.search_registrations(
        query="forest", date_from="2021-01-01", date_to="2021-12-31", limit=3
    )
    print(f"OK: 'forest' active in 2021 -> {period.total_matched}")
    ok &= period.total_matched >= 5

    first = health.registrations[0]
    detail = await client.get_registration(first.registration_number)
    print(f"OK: get {first.registration_number} -> {len(detail.registrations[0].topics)} topics")
    ok &= detail.registrations[0].registration_id == first.registration_id
    pair = "-".join(first.registration_number.split("-")[:2])
    by_pair = await client.get_registration(pair, lang="fr")
    ok &= by_pair.registrations[0].registration_id == first.registration_id
    try:
        await client.get_registration("0-0-0")
        ok = False
    except NotFound:
        print("OK: unknown registration number -> NotFound")

    reports = await client.search_activity_reports(agency="Health", date_from="2025-01-01", limit=5)
    print(
        f"OK: Health meetings since 2025 -> {reports.total_matched}, "
        f"{reports.first_meeting}..{reports.last_meeting}"
    )
    ok &= reports.total_matched >= 100 and reports.returned_count == 5
    ok &= all(r.office_holders for r in reports.reports)

    holder = await client.search_activity_reports(office_holder="Deputy Minister", limit=3)
    print(f"OK: Deputy Minister reports -> {holder.total_matched}")
    ok &= holder.total_matched >= 1000

    by_ministry = await client.summarize_activity("ministry", top=5)
    print(f"OK: top ministries -> {[(r.key, r.reports) for r in by_ministry.rows]}")
    ok &= by_ministry.total_reports >= 45000 and by_ministry.rows[0].reports > 1000

    by_month = await client.summarize_activity("month", client="Suzuki", top=6)
    print(f"OK: Suzuki by month -> {[(r.key, r.reports) for r in by_month.rows]}")
    ok &= len(by_month.rows) >= 1

    by_subject = await client.summarize_activity("subject_matter", agency="Forests", top=5)
    print(f"OK: Forests ministry by subject -> {[(r.key, r.reports) for r in by_subject.rows]}")
    ok &= len(by_subject.rows) >= 1

    for group in ("client", "office_holder", "lobbyist", "year"):
        summary = await client.summarize_activity(group, top=3)  # type: ignore[arg-type]
        print(f"OK: group_by {group} -> {[(r.key, r.reports) for r in summary.rows]}")
        ok &= bool(summary.rows)

    subjects = await client.list_codes("subject_matters", query="health")
    outcomes = await client.list_codes("intended_outcomes")
    ministries = await client.list_codes("ministries", query="premier")
    print(
        f"OK: codes -> {[c.name for c in subjects.codes]}, "
        f"{outcomes.total} outcomes, {[(c.name, c.reports) for c in ministries.codes]}"
    )
    ok &= subjects.total >= 1 and outcomes.total >= 13 and ministries.total >= 1

    print("\nBC LOBBYISTS SMOKE TEST PASSED" if ok else "\nBC LOBBYISTS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
