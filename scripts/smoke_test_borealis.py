"""Live smoke test for the borealis module's client.py: calls the real
Borealis Dataverse search API (not mocks), per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_borealis.py
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from maplestats_mcp.modules.borealis import client


async def main() -> int:
    ok = True

    everything = await client.search_ivt("", limit=3)
    print(f"OK: search_ivt('') -> {everything.returned_count} IVT files")
    ok &= everything.returned_count == 3

    patterns = await client.search_ivt("business patterns", limit=5)
    print(
        f"OK: search_ivt('business patterns') -> {patterns.returned_count} files "
        f"from {patterns.datasets_matched} datasets"
    )
    ok &= patterns.returned_count > 0
    ok &= all(f.file_name.lower().endswith(".ivt") for f in patterns.files)
    print("  sample:", patterns.files[0].model_dump(exclude={"r_snippet"}))

    labour = await client.search_ivt("labour force historical review", limit=3)
    print(f"OK: search_ivt('labour force historical review') -> {labour.returned_count} files")
    # Found only through the dataset title (checked live 2026-09-25).
    ok &= labour.returned_count == 3 and "Labour Force" in labour.files[0].dataset

    # The download URL must answer without a login for an unrestricted file.
    open_file = next(f for f in patterns.files if not f.restricted)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as http:
        response = await http.get(open_file.download_url, headers={"Range": "bytes=0-15"})
    print(f"OK: download {open_file.download_url} -> HTTP {response.status_code}")
    ok &= response.status_code in (200, 206)

    # ODESI collection: search, then DDI detail, then variables (checked live 2026-10-02).
    lfs = await client.search_odesi_datasets("labour force survey", collection="pumfs", limit=3)
    print(f"OK: search_odesi_datasets('labour force survey') -> {lfs.total_matched} datasets")
    ok &= lfs.total_matched > 50 and lfs.returned_count == 3
    polls = await client.search_odesi_datasets("environics focus canada", collection="polls")
    ok &= polls.total_matched > 0
    everything = await client.search_odesi_datasets("", limit=1)
    print(f"OK: search_odesi_datasets('') all public -> {everything.total_matched}")
    ok &= everything.total_matched > 4000  # 5,350 under odesi minus 414 DLI

    detail = await client.get_odesi_dataset(lfs.datasets[0].persistent_id)
    print(f"OK: get_odesi_dataset -> {detail.title}: {detail.access_summary}")
    ok &= bool(detail.title) and bool(detail.abstract) and len(detail.public_files) > 0
    data_file = next((f for f in detail.public_files if f.name.endswith((".tab", ".zip"))), None)
    if data_file is not None:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as http:
            response = await http.get(data_file.download_url, headers={"Range": "bytes=0-15"})
        print(f"OK: public file {data_file.name} -> HTTP {response.status_code}")
        ok &= response.status_code in (200, 206)

    variables = await client.search_odesi_variables(detail.persistent_id, "labour force")
    print(f"OK: search_odesi_variables -> {variables.total_matched} of {variables.total_variables}")
    ok &= variables.total_variables > 0 or variables.note is not None

    # A dataset without variable-level DDI must come back as a note (HTTP 403 upstream).
    poll = await client.search_odesi_variables("doi:10.5683/SP3/TDQHW1")  # Focus Canada 1989-2
    print(f"OK: poll variables -> {poll.total_variables} variables, note={poll.note is not None}")
    ok &= poll.total_variables == 0 and poll.note is not None

    # The DLI-licensed collection holds restricted files: the detail must say so, with no links.
    pccf = await client.get_odesi_dataset("doi:10.5683/SP3/EE9MF5")
    print(f"OK: DLI dataset -> {pccf.access_summary}")
    ok &= len(pccf.restricted_file_names) > 0 and all(
        not f.name.endswith((".tab", ".txt", ".zip")) for f in pccf.public_files
    )

    print("\nBOREALIS SMOKE TEST PASSED" if ok else "\nBOREALIS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
