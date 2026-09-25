"""Live smoke test for the ised.ip_horizons module's client.py: calls the
real open.canada.ca CKAN API and downloads the real CIPO data
dictionaries (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module".

Usage:
    uv run python scripts/smoke_test_ised_ip_horizons.py
"""

from __future__ import annotations

import asyncio
import sys

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

    print("\nISED IP HORIZONS SMOKE TEST PASSED" if ok else "\nISED IP HORIZONS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
