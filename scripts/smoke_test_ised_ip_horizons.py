"""Live smoke test for the ised.ip_horizons module's client.py: calls the
real open.canada.ca CKAN API and downloads the real CIPO data
dictionaries (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module".

The patent lookup and search steps download the main and party tables
(~240 MB) into MAPLE_IP_HORIZONS_CACHE_DIR on the first run; pass --ipc
to also test IPC search, which downloads ~740 MB and unzips ~2.6 GB of
CSV while converting.

Usage:
    uv run python scripts/smoke_test_ised_ip_horizons.py [--ipc]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from maplestats_mcp.modules.ised.ip_horizons import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    patents = await client.list_files("patent")
    print(f"OK: list_files(patent) -> {patents.returned_count} files, tables={patents.tables}")
    ok &= "main" in patents.tables and "claim" in patents.tables
    main_files = [f for f in patents.files if f.table == "main"]
    # confirmed live 2026-09-25: two files, 1-2,000,000 and 2,000,001-4,000,000
    ok &= len(main_files) >= 2 and all(f.number_from for f in main_files)
    print("  sample:", main_files[0].model_dump(mode="json"))

    everything = await client.list_files("patent", latest_only=False)
    print(f"OK: list_files(patent, latest_only=False) -> {everything.returned_count} files")
    ok &= everything.returned_count > patents.returned_count

    for ip_type in ("industrial_design", "trademark"):
        result = await client.list_files(ip_type)
        print(f"OK: list_files({ip_type}) -> {result.returned_count} files, {result.tables}")
        ok &= result.returned_count > 0
        # folder names like ID_CSV_2024_03_07 once leaked into table names
        ok &= "application_main" in result.tables
        ok &= all("/" not in name and "csv" not in name for name in result.tables)

    claims = await client.list_files("patent", table="claim")
    print(f"OK: list_files(patent, table=claim) -> {claims.returned_count} files")
    ok &= claims.returned_count > 1

    for ip_type in ("patent", "industrial_design"):
        dictionary = await client.get_dictionary(ip_type)
        print(
            f"OK: get_dictionary({ip_type}) -> {len(dictionary.fields)} fields, "
            f"tables={dictionary.tables}, notes={len(dictionary.notes)}"
        )
        ok &= len(dictionary.fields) > 50 and bool(dictionary.notes)

    main_fields = await client.get_dictionary("patent", table="main")
    print(f"OK: get_dictionary(patent, main) -> {[f.name_en for f in main_fields.fields][:5]}")
    ok &= main_fields.fields[0].name_en == "Patent Number"

    try:
        await client.get_dictionary("trademark")
        print("FAIL: expected InvalidInput for the trademark dictionary")
        ok = False
    except InvalidInput:
        print("OK: trademark dictionary raises InvalidInput as expected")

    record = await client.get_patent(2000001)
    print(f"OK: get_patent(2000001) -> {record.patent.title_en}, {len(record.parties)} parties")
    # confirmed live 2026-09-25: filed 1989-10-02, owner PANAMETRICS, INC.
    ok &= record.patent.filing_date == "1989-10-02"
    ok &= any(p.name == "PANAMETRICS, INC." for p in record.parties)

    old = await client.get_patent(1000000)
    print(f"OK: get_patent(1000000) -> {old.patent.title_en}, filed {old.patent.filing_date}")

    owners = await client.search_patents(party_name="ballard power", party_type="owner", limit=5)
    print(f"OK: search_patents(owner 'ballard power') -> {owners.total_matched} matches")
    ok &= owners.total_matched > 50

    recent = await client.search_patents(title="hydrogen", filed_from=date(2020, 1, 1), limit=3)
    print(f"OK: search_patents(title hydrogen, 2020+) -> {recent.total_matched} matches")
    ok &= recent.total_matched > 0
    ok &= all((p.filing_date or "") >= "2020-01-01" for p in recent.patents)

    if "--ipc" in sys.argv:
        classed = await client.get_patent(2000001, include_classifications=True)
        print(f"OK: get_patent classes -> {[c.symbol for c in classed.classifications]}")
        ok &= bool(classed.classifications)
        fuel = await client.search_patents(ipc="H01M 8", filed_from=date(2015, 1, 1), limit=3)
        print(f"OK: search_patents(ipc H01M 8, 2015+) -> {fuel.total_matched} matches")
        ok &= fuel.total_matched > 100

    print("\nISED IP HORIZONS SMOKE TEST PASSED" if ok else "\nISED IP HORIZONS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
