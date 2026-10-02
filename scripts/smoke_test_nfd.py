"""Live smoke test for the National Forestry Database module, per AGENTS.md.

Calls every client function against nfdp.ccfm.org. Reference values were
read from the NFD's own files on 2026-10-02: 25 tables; area burned in
2023 by cause (Canada summed over the 12 jurisdictions reporting: about
17.3 million hectares); layouts that differ (property losses has six
columns, scarification codes Yukon "YK", rates and totals share a table).
Past years do not change, except through the NFD's own revisions, so
ranges are loose.

Usage:
    uv run python scripts/smoke_test_nfd.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.nfd import client


def check(ok: bool, label: str) -> bool:
    print(("OK:   " if ok else "FAIL: ") + label)
    return ok


async def main() -> int:
    ok = True

    listing = await client.list_tables()
    ids = [t.table_id for t in listing.tables]
    ok &= check(
        listing.count >= 25 and {"2", "3.2.1", "5.1", "6.4", "7", "8.2.3"} <= set(ids),
        f"list: {listing.count} tables, sections {listing.sections}",
    )
    french = await client.list_tables("incendies", lang="fr")
    ok &= check(
        french.count >= 6 and "3.2.1" in [t.table_id for t in french.tables],
        f"fr section filter: {[t.title for t in french.tables][:2]}",
    )

    # Every table: describe (CSV + dictionary) and one query.
    for table_id in ids:
        described = await client.describe_table(table_id)
        queried = await client.query_table(table_id, province="BC", year_from=2015, limit=5)
        ok &= check(
            described.n_rows > 500
            and described.last_year >= 2024
            and described.provenance.url.startswith("http")
            and queried.matched_count > 0
            and described.dictionary_title is not None
            and described.last_updated is not None,
            f"{table_id} {described.title[:50]!r}: {described.first_year}-{described.last_year}, "
            f"{described.n_rows} rows, unit {described.unit}, BC rows {queried.matched_count}",
        )

    by_cause = await client.query_table(
        "3.2.1", year_from=2023, year_to=2023, group_by=["year", "cause"]
    )
    total = sum(r.value or 0 for r in by_cause.rows)
    ok &= check(
        15_000_000 < total < 20_000_000,
        f"area burned 2023, Canada sum over causes: {total:,.0f} ha",
    )
    bc = await client.query_table(
        "3.2.1", province="British Columbia", year_from=2023, year_to=2023, group_by=["year"]
    )
    ok &= check(
        len(bc.rows) == 1 and 1_000_000 < (bc.rows[0].value or 0) < 3_000_000,
        f"BC 2023 area burned: {[r.value for r in bc.rows]}",
    )
    fr = await client.query_table(
        "3.1.2", province="QC", year_from=2023, year_to=2023, filters={"mois": "août"}, lang="fr"
    )
    ok &= check(
        len(fr.rows) == 1 and fr.rows[0].dimensions["month"] == "Août" and fr.unit is not None,
        f"fr fires in Quebec, August 2023: {[(r.dimensions, r.value) for r in fr.rows]}",
    )

    scarification = await client.query_table("6.2", province="YT", limit=1)
    ok &= check(
        scarification.matched_count > 30 and {r.iso for r in scarification.rows} == {"YT"},
        f"Yukon scarification rows (YK and YT coded): {scarification.matched_count}",
    )
    blank = await client.query_table("2", province="AB", year_from=1990, year_to=1990)
    ok &= check(
        any(r.value is None and r.qualifiers == ["u"] for r in blank.rows),
        "wood supply: blank values stay null with their code",
    )
    losses = await client.query_table("3.3", province="NP", limit=2)
    ok &= check(
        losses.matched_count > 0, f"property losses, national parks: {losses.matched_count}"
    )

    rates = await client.query_table(
        "8.2.3", filters={"unit_of_measure": "Total applied (kg)"}, group_by=["year"]
    )
    ok &= check(len(rates.rows) > 20, f"herbicide totals by year: {len(rates.rows)} years")

    comments = await client.table_comments("5.1", province="BC", limit=5)
    ok &= check(
        comments.matched_count > 0 and bool(comments.comments[0].comment),
        f"5.1 comments for BC: {comments.matched_count}",
    )
    none = await client.table_comments("3.2.1")
    ok &= check(none.matched_count == 0, f"3.2.1 has no comments: {none.notes[0][:60]}")
    fr_comments = await client.table_comments("2", province="AB", limit=1, lang="fr")
    ok &= check(fr_comments.matched_count > 0, "fr comments read")

    print("\nNFD SMOKE TEST PASSED" if ok else "\nNFD SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
