"""Live smoke test for the statcan.delta module's client.py: calls the real
Delta File archive (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_delta.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from maplestats_mcp.modules.statcan.delta import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    # A recent weekday almost certainly has a Delta File; a Sunday
    # almost certainly does not -- both are checked below.
    today = datetime.now(UTC).date()
    recent_weekday = today - timedelta(days=3)
    while recent_weekday.weekday() >= 5:
        recent_weekday -= timedelta(days=1)

    existing = await client.get_file_link(recent_weekday.isoformat())
    print(f"OK: get_file_link({recent_weekday}) -> exists={existing.exists} url={existing.url}")
    ok &= existing.exists
    ok &= existing.size_bytes is not None and existing.size_bytes > 0

    sunday = today - timedelta(days=(today.weekday() - 6) % 7 + 7)
    missing = await client.get_file_link(sunday.isoformat())
    print(f"OK: get_file_link({sunday}, a Sunday) -> exists={missing.exists}")
    ok &= not missing.exists
    ok &= missing.size_bytes is None

    try:
        await client.get_file_link("not-a-date")
        print("FAIL: expected InvalidInput for a bogus date")
        ok = False
    except InvalidInput:
        print("OK: bogus date raises InvalidInput as expected")

    print("\nSTATCAN DELTA SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
