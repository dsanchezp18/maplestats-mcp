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

from maplestats_mcp.modules.statcan.delta import archive, client, realtime
from maplestats_mcp.shared.errors import InvalidInput, NotFound


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

    # Range reads only: the listing, the metadata member of one day and one
    # table's rows from a small file. The multi-gigabyte days are never
    # streamed here; list_tables on one costs about 1 MB.
    files = await archive.list_files(date=sunday.isoformat(), include_sizes=True)
    print(f"OK: list_files -> {files.count} files, {files.oldest} to {files.newest}")
    ok &= files.count >= 20 and files.newest is not None
    ok &= files.requested_status is not None and files.requested_status.startswith("no release")
    ok &= all(f.size_bytes for f in files.files)
    small = min(files.files[:6], key=lambda f: f.size_bytes or 0)
    tables = await archive.list_tables(small.date)
    print(
        f"OK: list_tables({small.date}) -> {tables.table_count} tables, {small.size_bytes:,} bytes"
    )
    ok &= tables.table_count > 0 and tables.tables[0].title_en is not None
    ok &= small.size_bytes is not None and small.size_bytes < 60_000_000
    first = tables.tables[0]
    data = await archive.read_table(small.date, first.product_id, max_rows=5)
    print(
        f"OK: read_table({small.date}, {first.product_id}) -> {data.row_count} rows, "
        f"{data.compressed_bytes_scanned:,} bytes scanned"
    )
    ok &= data.row_count > 0 and data.legend.scalar_factors != {}
    big = max(files.files[:6], key=lambda f: f.size_bytes or 0)
    big_tables = await archive.list_tables(big.date)
    print(
        f"OK: list_tables({big.date}, {big.size_bytes:,} bytes) -> {big_tables.table_count} tables"
    )
    ok &= big_tables.table_count > 0
    try:
        await archive.read_table(small.date, 99999999)
        print("FAIL: expected NotFound for a table not in the release")
        ok = False
    except NotFound:
        print("OK: a table outside the release raises NotFound")
    ok &= realtime.list_real_time_tables().count == 19

    print("\nSTATCAN DELTA SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
