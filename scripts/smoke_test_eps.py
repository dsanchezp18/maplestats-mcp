"""Live smoke test for the Edmonton Police Service occurrences module."""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.eps import client
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    failures = 0
    load = await client.get_last_load_date()
    print(f"OK: get_last_load_date -> {load.last_load_date} ({load.raw_value!r})")
    failures += load.last_load_date is None

    for dataset in ("current", "2023"):
        listing = await client.list_occurrences(dataset, limit=3)  # type: ignore[arg-type]
        first = listing.occurrences[0] if listing.occurrences else None
        print(f"OK: list_occurrences({dataset}) total={listing.total_matches} first={first}")
        failures += not listing.occurrences or first is None or first.latitude is None

    filtered = await client.list_occurrences(
        category="Violent", intersection_contains="jasper av", limit=2
    )
    print(f"OK: filtered list total={filtered.total_matches}")
    failures += filtered.total_matches == 0

    for group_by in ("category", "group", "type", "month", "intersection"):
        summary = await client.summarize_occurrences(group_by=group_by, top=5)  # type: ignore[arg-type]
        top_group = summary.groups[0] if summary.groups else None
        print(f"OK: summarize({group_by}) total={summary.total_matches} top={top_group}")
        failures += not summary.groups

    dated = await client.summarize_occurrences(
        dataset="2023", group_by="month", start_date="2023-03-01", end_date="2023-03-31"
    )
    print(f"OK: 2023 March by month -> {[(g.keys, g.count) for g in dated.groups]}")
    failures += len(dated.groups) != 1 or dated.groups[0].count != dated.total_matches

    try:
        await client.list_occurrences(start_date="not-a-date")
        print("FAIL: bad date did not raise")
        failures += 1
    except InvalidInput:
        print("OK: bad date raises InvalidInput")

    print("EPS SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
