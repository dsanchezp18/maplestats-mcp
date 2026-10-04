"""Live smoke test for cmhc.data_tables' client.py: calls every exported
function directly against the real www.cmhc-schl.gc.ca "Data Tables"
catalogue (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" - a clean mocked pytest run only proves the code
matches assumptions the tests share with it, not that those assumptions
are correct.

Usage:
    uv run python scripts/smoke_test_cmhc_data_tables.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.cmhc.data_tables import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ok = True

    rental = await client.list_tables("rental-market")
    print(f"OK: list_tables(rental-market) -> {rental.total_count} tables")
    ok &= rental.total_count > 10

    household = await client.list_tables("household-characteristics")
    print(f"OK: list_tables(household-characteristics) -> {household.total_count} tables")
    ok &= household.total_count > 10

    chs = await client.list_tables("canadian-housing-survey-data-tables")
    print(f"  list_tables(canadian-housing-survey-data-tables) -> {chs.total_count} (expected 0)")

    slug = "urban-rental-market-survey-data-vacancy-rates"
    ok &= await _check(
        "get_table(rental-market, vacancy rates)", client.get_table("rental-market", slug)
    )
    table = await client.get_table("rental-market", slug)
    print(f"  title={table.title!r}")
    print(f"  {len(table.geographies)} geographies, {len(table.editions)} editions")
    ok &= len(table.editions) > 5
    ok &= table.default_download_url is not None

    ok &= await _check("get_download_url(default)", client.get_download_url("rental-market", slug))
    default_link = await client.get_download_url("rental-market", slug)
    print(f"  {default_link.document_url}")
    ok &= default_link.document_url.startswith("https://assets.cmhc-schl.gc.ca/")

    if len(table.editions) > 2:
        older_edition = table.editions[2]
        ok &= await _check(
            f"get_download_url({older_edition.label})",
            client.get_download_url("rental-market", slug, edition_id=older_edition.id),
        )
        older_link = await client.get_download_url(
            "rental-market", slug, edition_id=older_edition.id
        )
        print(f"  {older_link.document_url}")
        ok &= older_link.document_url != default_link.document_url

    # Every listed table must resolve a download. Checking one edition-type
    # table hid that 52 of the 72 (single-file report pages) failed.
    for listing in (rental, household):
        failed = []
        for i, summary in enumerate(listing.tables):
            lang = "fr" if i % 5 == 0 else "en"
            try:
                link = await client.get_download_url(listing.category, summary.slug, lang=lang)
                if not link.document_url.startswith("https://"):
                    failed.append(summary.slug)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{summary.slug} ({type(exc).__name__}: {exc})")
        print(
            f"{'OK' if not failed else 'FAIL'}: {listing.category}: "
            f"{len(listing.tables) - len(failed)} of {len(listing.tables)} tables resolve"
        )
        for item in failed:
            print(f"  FAIL {item}")
        ok &= not failed

    french = await client.get_table(
        "household-characteristics", "home-equity-net-worth-tenure-canada-provinces", lang="fr"
    )
    print(f"  fr title={french.title!r}")
    ok &= french.title.startswith("Avoir")
    # The French page has its own document id: the English one gave the
    # English file under lang="fr".
    ok &= "_fr_" in (french.default_download_url or "")

    # French listings: every table paired with its French twin through
    # CMHC's own language links (72 of 72 on 2026-10-03), and a French slug
    # resolves the French file.
    for category in ("rental-market", "household-characteristics"):
        listing = await client.list_tables(category, lang="fr")
        unpaired = [t.slug for t in listing.tables if t.note]
        print(
            f"{'OK' if not unpaired else 'NOTE'}: list_tables({category}, fr) -> "
            f"{listing.total_count - len(unpaired)} of {listing.total_count} French twins"
        )
        ok &= listing.total_count > 10 and len(unpaired) < listing.total_count // 10
        first = listing.tables[0]
        link = await client.get_download_url(category, first.slug, lang="fr")
        print(f"  {first.slug} (fr) -> {link.file_name}")
        ok &= first.english_slug is not None and bool(link.file_name)

    # Error-path checks: must raise typed errors, not a raw httpx exception.
    try:
        await client.list_tables("not-a-real-category")
        print("FAIL: list_tables(unknown category) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: list_tables(unknown category) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: list_tables(unknown category) raised {type(exc).__name__}: {exc}")
        ok = False

    try:
        await client.get_table("rental-market", "not-a-real-table-slug-xyz")
        print("FAIL: get_table(unknown slug) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_table(unknown slug) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_table(unknown slug) raised {type(exc).__name__} instead of NotFound: {exc}"
        )
        ok = False

    try:
        await client.get_download_url("rental-market", slug, edition_id="{NOT-A-REAL-EDITION}")
        print("FAIL: get_download_url(bad edition_id) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: get_download_url(bad edition_id) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_download_url(bad edition_id) raised {type(exc).__name__} "
            f"instead of InvalidInput: {exc}"
        )
        ok = False

    print()
    print("CMHC DATA TABLES SMOKE TEST PASSED" if ok else "CMHC DATA TABLES SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
