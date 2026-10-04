"""Live smoke test for the Finance Canada module (FRT and Fiscal Monitor, EN and FR).

uv run python scripts/smoke_test_finance_canada.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.finance_canada import client, monitor


async def main() -> int:
    ok = True

    listing = await client.list_frt_tables()
    editions = [e.edition for e in listing.editions]
    print(f"OK: FRT editions {editions}; {listing.edition} has {listing.total_matched} tables")
    # confirmed live 2026-10-03: editions 2019-2025, 55 tables each
    ok &= editions[-1] == 2019 and listing.total_matched >= 50

    for edition, lang in ((None, "en"), (2025, "fr"), (2019, "en")):
        table = await client.get_frt_table(1, edition=edition, last=1, lang=lang)
        row = table.rows[0]
        print(f"OK: FRT {table.edition.edition} {lang} table 1 -> {table.info.title}; {row}")
        ok &= len(table.info.columns) >= 10 and isinstance(list(row.values())[1], int)

    alberta = await client.get_frt_table(26)
    print(f"OK: Alberta -> {alberta.info.row_count} rows, {alberta.info.columns}")
    ok &= alberta.info.title == "Alberta" and alberta.info.row_count >= 30

    balance = await client.get_frt_table(47, lang="fr")
    print(f"OK: table 47 (fr) -> {balance.rows[0]}")
    ok &= "section" in balance.rows[0] and len(balance.info.columns) > 20

    issues = await monitor.list_issues()
    print(f"OK: Fiscal Monitor issues {issues.issues[0].period} back to {issues.issues[-1].period}")
    ok &= len(issues.issues) >= 50

    latest = await monitor.get_tables(table="2")
    revenues = latest.tables[0]
    print(f"OK: {latest.issue.title} {revenues.label} -> {revenues.columns}")
    ok &= len(revenues.columns) == 7 and isinstance(revenues.rows[0][revenues.columns[1]], int)

    two_month = await monitor.get_tables("2026-04", table="1", lang="fr")
    print(f"OK: {two_month.issue.title} -> {two_month.tables[0].columns}")
    ok &= len(two_month.tables[0].columns) == 7

    old = await monitor.get_tables("2023-06", lang="fr")
    print(f"OK: 2023-06 (fr) -> {[(t.label[:25], t.columns[0]) for t in old.tables]}")
    ok &= all(t.columns[0] in ("row", "Mois") for t in old.tables)

    print("\nFINANCE CANADA SMOKE TEST PASSED" if ok else "\nFINANCE CANADA SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
