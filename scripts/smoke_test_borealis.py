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

    print("\nBOREALIS SMOKE TEST PASSED" if ok else "\nBOREALIS SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
