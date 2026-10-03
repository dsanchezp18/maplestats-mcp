"""Live smoke test for the Ontario Energy Board module (every client function).

uv run python scripts/smoke_test_oeb.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.oeb import client


async def main() -> int:
    ok = True

    listing = await client.list_datasets()
    readable = sum(1 for d in listing.datasets if d.readable)
    print(f"OK: {listing.total} datasets, {readable} readable")
    # confirmed live 2026-10-03: 43 dataset pages + the 2021 yearbook; only the
    # service-area map zips are not read
    ok &= listing.total >= 44 and readable == listing.total - 1
    unread = [d.slug for d in listing.datasets if not d.readable]
    print(f"   not read: {unread}")

    french = await client.list_datasets("fiabilité", lang="fr")
    print(f"OK: fr 'fiabilité' -> {[d.title for d in french.datasets]}")
    ok &= any("2.1.4.2" in d.title for d in french.datasets)

    detail = await client.describe_dataset("system reliability")
    print(
        f"OK: reliability -> {detail.selected_file and detail.selected_file.name}, "
        f"{detail.record_count} records, years {detail.years[:2]}..{detail.years[-1:]}, "
        f"{detail.distributor_count} companies, {len(detail.files)} files"
    )
    ok &= (detail.record_count or 0) > 5000 and "2024" in detail.years

    saidi = await client.query_dataset(
        "electricity-reporting-record-keeping-requirements-rrr-section-2142-system-reliability",
        distributor="Hydro Ottawa",
        year=2024,
        fields=["Total SAIDI", "Total SAIFI", "Cause of Interruption"],
    )
    print(f"OK: Hydro Ottawa 2024 -> {saidi.total_matched} rows, {saidi.rows[:1]}")
    ok &= saidi.total_matched >= 5 and "Total SAIDI" in saidi.columns

    # confirmed live 2026-10-03: 2015-2023 use ten causes ("Tree Contacts"); 2024
    # splits them into 24 sub-causes ("Tree Contacts - Fallen Tree on Right-of-Way")
    # for 53 companies, while 5 companies still report the old ten.
    trees = await client.query_dataset(
        "2.1.4.2 system reliability",
        year=2023,
        where={"Cause of Interruption": "Tree Contacts"},
        max_rows=3,
    )
    print(f"OK: tree contacts 2023 -> {trees.total_matched}")
    ok &= trees.total_matched > 50

    archived = await client.query_dataset(
        "electricity-reporting-record-keeping-requirements-rrr-section-2151-labour",
        release="2022-09-29",
        distributor="Toronto Hydro",
    )
    print(f"OK: labour 2022 release -> {archived.file.name}, {archived.total_matched} rows")
    ok &= archived.file.release == "2022-09-29" and archived.total_matched >= 5

    licences = await client.query_dataset(
        "licensed-market-participants", where={"LICENCE TYPE": "Electricity Distributor"}
    )
    print(f"OK: licensed distributors -> {licences.total_matched}")
    ok &= licences.total_matched > 50

    rates_db = await client.query_dataset(
        "electricity-distribution-rates-databases", file="2025", distributor="Hydro One"
    )
    print(f"OK: 2025 rates database Hydro One -> {rates_db.total_matched}, {rates_db.columns[:4]}")
    ok &= rates_db.total_matched > 20

    costs = await client.describe_dataset("intervenor-cost-awards")
    print(f"OK: cost awards -> {len(costs.files)} files, {costs.record_count} records")
    ok &= len(costs.files) >= 10 and (costs.record_count or 0) > 10

    yearbook = await client.query_dataset(
        "yearbook-electricity-distributors-2021", file="System Reliability", distributor="Alectra"
    )
    print(f"OK: yearbook reliability Alectra -> {yearbook.total_matched}")
    ok &= yearbook.total_matched > 10

    big = await client.query_dataset(
        "electricity-reporting-record-keeping-requirements-rrr-section-217-trial-balance",
        file="2015-2019",
        distributor="Hydro Ottawa",
        year=2019,
        max_rows=5,
    )
    print(f"OK: 62 MB trial balance -> {big.file.name}, {big.total_matched} rows")
    ok &= big.total_matched > 100

    residential = await client.get_rates("electricity_residential", "Toronto Hydro")
    sc = next(f for f in residential.fields if f.name == "SC")
    print(f"OK: Toronto Hydro residential -> {residential.rows[0].get('SC')} ({sc.description})")
    ok &= residential.total_matched >= 1 and sc.description is not None

    gas = await client.get_rates("natural_gas_residential", lang="fr")
    print(f"OK: gas (fr) -> {gas.title}, {gas.total_matched} rows")
    ok &= gas.total_matched >= 3

    tou = await client.get_rates("rpp_time_of_use")
    print(f"OK: TOU history -> {tou.rows[0]}")
    ok &= tou.total_matched > 20

    print("\nOEB SMOKE TEST PASSED" if ok else "\nOEB SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
