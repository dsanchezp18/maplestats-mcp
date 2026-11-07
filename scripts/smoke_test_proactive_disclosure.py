"""Live smoke test for the proactive_disclosure module: every client function
against the real open.canada.ca DataStore, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_proactive_disclosure.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from _smoke_common import skip_outage, skip_reloading, verdict

from maplestats_mcp.modules.proactive_disclosure import client


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


async def main() -> int:
    ok = True
    try:
        listing = await client.list_datasets("en")
        for info in listing.datasets:
            print(
                f"OK: list_datasets {info.dataset}: {info.row_count:,} rows, "
                f"in package={info.resource_in_package}, modified {info.last_modified}"
            )
            ok &= info.resource_in_package
        # An empty table means open.canada.ca is reloading: the other tables can then hold
        # duplicate rows (contracts held each row twice on 2026-11-05), so nothing below
        # can be trusted until the reload ends.
        empty = [info.dataset for info in listing.datasets if not info.row_count]
        if empty:
            skip_reloading("open.canada.ca DataStore", ", ".join(empty))
            return verdict("PROACTIVE DISCLOSURE", ok)
        ok &= all((info.row_count or 0) > 10_000 for info in listing.datasets)
        french = await client.list_datasets("fr")
        ok &= french.datasets[0].dataset_url.startswith("https://open.canada.ca/data/fr/")

        started = time.monotonic()
        top = await client.summarize(
            dataset="contracts", group_by="department", fiscal_year="2024-2025", top=10
        )
        seconds = time.monotonic() - started
        print(
            f"\nOK: summarize contracts by department, FY 2024-2025 ({seconds:.0f} s): "
            f"{top.rows_scanned:,} rows, {top.total_count:,} contracts, "
            f"{_money(top.total_value)}"
        )
        for group in top.groups:
            print(f"   {group.label}: {group.count:,} contracts, {_money(group.total_value)}")
        ok &= top.rows_scanned > 50_000 and len(top.groups) == 10
        every_row = await client.summarize(
            dataset="contracts",
            group_by="fiscal_year",
            fiscal_year="2024-2025",
            owner_org="pwgsc-tpsgc",
            value_mode="all_rows",
        )
        latest = await client.summarize(
            dataset="contracts",
            group_by="fiscal_year",
            fiscal_year="2024-2025",
            owner_org="pwgsc-tpsgc",
        )
        print(
            f"OK: PSPC FY 2024-2025, all rows {_money(every_row.total_value)} "
            f"({every_row.total_count:,}) vs latest per contract {_money(latest.total_value)} "
            f"({latest.total_count:,})"
        )
        ok &= latest.total_count <= every_row.total_count

        vendors = await client.summarize(
            dataset="contracts", group_by="vendor", owner_org="pco-bcp", top=5
        )
        print("OK: top vendors, Privy Council Office:")
        for group in vendors.groups:
            print(f"   {group.label}: {group.count} contracts, {_money(group.total_value)}")

        contracts = await client.search_contracts(
            vendor="deloitte", fiscal_year="2024-2025", sort="value_desc", limit=3
        )
        print(
            f"\nOK: search_contracts Deloitte FY 2024-2025 by value: {contracts.total_matched} "
            f"matched, {contracts.rows_scanned} scanned"
        )
        for row in contracts.records:
            print(
                f"   {row.contract_date} {row.vendor_name} {_money(row.contract_value)} "
                f"{row.department.name} [{row.instrument_type_label}] {row.source.dataset_url}"
            )
        ok &= contracts.total_matched > 0 and all(
            "deloitte" in (row.vendor_name or "").lower() for row in contracts.records
        )
        big = await client.search_contracts(
            owner_org="pco-bcp",
            date_from="2025-04-01",
            date_to="2026-03-31",
            min_value=100_000,
            limit=3,
            lang="fr",
        )
        print(f"OK: search_contracts PCO >= $100k, 2025-26 (fr): {big.total_matched} matched")
        ok &= all((row.contract_value or 0) >= 100_000 for row in big.records)

        travel = await client.search_travel(
            name="David McGuinty", disclosure_group="ministers", fiscal_year="2025-2026", limit=5
        )
        print(f"\nOK: search_travel David McGuinty, FY 2025-2026: {travel.total_matched} trips")
        for trip in travel.records:
            print(
                f"   {trip.start_date} {trip.name} ({trip.title}) {trip.purpose} -> "
                f"{', '.join(trip.destinations)}: {_money(trip.total)}"
            )
        ok &= travel.total_matched > 0
        minister = await client.summarize(
            dataset="travel",
            group_by="fiscal_year",
            party="David McGuinty",
            title="Minister of National Defence",
            disclosure_group="ministers",
        )
        print("OK: summarize David McGuinty (Minister of National Defence) travel by fiscal year:")
        for group in minister.groups:
            print(f"   {group.key}: {group.count} trips, {_money(group.total_value)}")
        ministers = await client.summarize(
            dataset="travel",
            group_by="name",
            disclosure_group="ministers",
            title="Minister",
            fiscal_year="2025-2026",
            top=5,
        )
        print("OK: costliest travel, MPSES titles with 'Minister', FY 2025-2026:")
        for group in ministers.groups:
            print(f"   {group.label}: {group.count} trips, {_money(group.total_value)}")

        hospitality = await client.search_hospitality(
            disclosure_group="ministers", sort="value_desc", fiscal_year="2025-2026", limit=3
        )
        print(
            f"\nOK: search_hospitality ministers' events FY 2025-2026: {hospitality.total_matched}"
        )
        for event in hospitality.records:
            print(
                f"   {event.start_date} {event.name} ({event.title}) {event.description}: "
                f"{_money(event.total)}, {event.guest_attendees} guests"
            )
        ok &= hospitality.total_matched > 0

        grants = await client.search_grants(
            recipient="Carleton University", sort="value_desc", province="ON", limit=3
        )
        print(f"\nOK: search_grants Carleton University: {grants.total_matched} rows")
        for grant in grants.records:
            print(
                f"   {grant.agreement_start_date} {grant.program_name}: "
                f"{_money(grant.agreement_value)} (amendment {grant.amendment_number})"
            )
        ok &= grants.total_matched > 0
        provinces = await client.summarize(
            dataset="grants", group_by="province", owner_org="wage", top=5
        )
        print("OK: WAGE grants and contributions by province (latest per agreement):")
        for group in provinces.groups:
            print(f"   {group.key}: {group.count:,} agreements, {_money(group.total_value)}")
    except Exception as exc:  # noqa: BLE001 - only an outage is skipped
        skip_outage("open.canada.ca DataStore", exc)

    return verdict("PROACTIVE DISCLOSURE", ok)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
