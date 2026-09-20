"""Live smoke test for the ised.cipo module's client.py: calls the real
Canadian Trademarks Database search API (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module" -- a clean mocked pytest run
only proves the code matches assumptions the tests share with it, not
that those assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ised_cipo.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ised.cipo import client
from maple_data_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    result = await client.search_trademarks("all", "maple", max_return=5)
    print(
        f"OK: search_trademarks(all, 'maple') -> {result.returned_count} of {result.total_matched}"
    )
    ok &= result.total_matched > 20000  # confirmed live: 24651
    ok &= result.returned_count == 5
    sample = result.records[0]
    print("  sample:", sample.model_dump())

    empty = await client.search_trademarks("all", "", max_return=1)
    print(f"OK: search_trademarks(all, '') match-all -> total_matched={empty.total_matched}")
    ok &= empty.total_matched > 1_000_000  # confirmed live: 2,185,568

    by_owner = await client.search_trademarks("owner_name", "canada", max_return=3)
    print(f"OK: search_trademarks(owner_name, 'canada') -> total_matched={by_owner.total_matched}")
    ok &= by_owner.total_matched > 0

    by_appnum = await client.search_trademarks("application_number", "1137536", max_return=3)
    print(
        f"OK: search_trademarks(application_number, '1137536') -> total_matched={by_appnum.total_matched}"
    )
    ok &= by_appnum.total_matched == 1
    ok &= by_appnum.records[0].application_number == "1137536"

    try:
        await client.search_trademarks("not_a_real_field", "maple")
        print("FAIL: expected InvalidInput for a bogus search_field")
        ok = False
    except InvalidInput:
        print("OK: bogus search_field raises InvalidInput as expected")

    try:
        await client.search_trademarks("all", "maple", max_return=0)
        print("FAIL: expected InvalidInput for max_return=0")
        ok = False
    except InvalidInput:
        print("OK: max_return=0 raises InvalidInput as expected")

    print("\nISED CIPO SMOKE TEST PASSED" if ok else "\nISED CIPO SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
