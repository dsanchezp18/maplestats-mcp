"""Live smoke test for the statcan.reference module's client.py: calls the
real "Reference resources" catalogue search (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module" -- a clean mocked pytest run only
proves the code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_statcan_reference.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.statcan.reference import client
from maple_data_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    result = await client.search_documents("housing")
    print(f"OK: search_documents('housing') -> {result.returned_count} of {result.total_matched}")
    ok &= result.total_matched > 50
    ok &= result.returned_count > 0
    sample = result.documents[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.title)
    ok &= sample.url.startswith("http")

    empty = await client.search_documents("")
    print(f"OK: search_documents('') -> total_matched={empty.total_matched}")
    ok &= empty.total_matched > 1500  # confirmed live: 2,031

    fr = await client.search_documents("logement", lang="fr", count=5)
    print(f"OK: search_documents('logement', lang=fr) -> {fr.returned_count} of {fr.total_matched}")
    ok &= fr.total_matched > 0

    page2 = await client.search_documents("housing", page=2, count=5)
    print(f"OK: search_documents('housing', page=2) -> {page2.returned_count} results")
    ok &= page2.returned_count > 0
    ok &= page2.documents[0].title != result.documents[0].title

    try:
        await client.search_documents("housing", lang="de")
        print("FAIL: expected InvalidInput for a bogus lang")
        ok = False
    except InvalidInput:
        print("OK: bogus lang raises InvalidInput as expected")

    print("\nSTATCAN REFERENCE SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
