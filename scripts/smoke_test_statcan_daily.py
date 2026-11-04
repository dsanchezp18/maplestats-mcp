"""Live smoke test for the statcan.daily module's client.py: calls the real
Daily Atom feeds (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" -- a clean mocked pytest run only proves the code matches
assumptions the tests share with it, not that those assumptions are
correct.

Usage:
    uv run python scripts/smoke_test_statcan_daily.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.daily import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    all_releases = await client.get_releases("all", limit=10)
    print(f"OK: get_releases(all) -> {all_releases.returned_count} releases")
    ok &= all_releases.returned_count > 0
    sample = all_releases.releases[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.title)
    ok &= sample.url.startswith("http")

    housing = await client.get_releases("housing", limit=5)
    print(f"OK: get_releases(housing) -> {housing.returned_count} releases")
    ok &= housing.returned_count > 0

    fr = await client.get_releases("housing", lang="fr", limit=1)
    print(f"OK: get_releases(housing, lang=fr) -> {fr.returned_count} releases")
    ok &= fr.returned_count > 0
    if fr.releases:
        print("  sample fr:", fr.releases[0].model_dump())

    try:
        await client.get_releases("not_a_real_subject")
        print("FAIL: expected InvalidInput for a bogus subject")
        ok = False
    except InvalidInput:
        print("OK: bogus subject raises InvalidInput as expected")

    archive = await client.search_archive("labour force survey", start_date="2012-01-01")
    print(f"OK: search_archive('labour force survey') -> {archive.total_matched} matches")
    ok &= archive.total_matched > 50  # confirmed live: released monthly since well before 2012
    print(f"  most recent in page: {archive.entries[0].release_date if archive.entries else None}")
    ok &= all(
        e.release_date >= e2.release_date
        for e, e2 in zip(archive.entries, archive.entries[1:], strict=False)
    )

    ranged = await client.search_archive("", start_date="2012-03-01", end_date="2012-03-31")
    print(f"OK: search_archive('', 2012-03) -> {ranged.total_matched} matches")
    ok &= ranged.total_matched > 0
    ok &= all(e.release_date.month == 3 and e.release_date.year == 2012 for e in ranged.entries)

    try:
        await client.search_archive("", start_date="not-a-date")
        print("FAIL: expected InvalidInput for a bogus start_date")
        ok = False
    except InvalidInput:
        print("OK: bogus start_date raises InvalidInput as expected")

    upcoming = await client.get_release_calendar("labour force survey", limit=3)
    print(
        f"OK: get_release_calendar('labour force survey') -> {upcoming.total_matched} upcoming, "
        f"schedule reaches {upcoming.latest_scheduled_date}"
    )
    ok &= upcoming.total_matched > 0
    ok &= all(e.scheduled and e.url is None for e in upcoming.entries)
    ok &= upcoming.entries == sorted(upcoming.entries, key=lambda e: e.release_date)
    print("  next:", upcoming.entries[0].model_dump(mode="json") if upcoming.entries else None)

    fr_cal = await client.get_release_calendar("population active", lang="fr", limit=1)
    print(f"OK: get_release_calendar('population active', fr) -> {fr_cal.total_matched}")
    ok &= fr_cal.total_matched > 0

    products = await client.get_release_calendar(
        "62-013-X", kind="products", upcoming_only=False, limit=2
    )
    print(f"OK: get_release_calendar('62-013-X', products) -> {products.total_matched} releases")
    ok &= products.total_matched > 0 and all(e.catalogue_number for e in products.entries)

    # The newest Daily article in the feed, read in full in both languages.
    article_url = next((r.url for r in all_releases.releases if "/daily-quotidien/" in r.url), None)
    ok &= article_url is not None
    if article_url:
        for lang in ("en", "fr"):
            article = await client.get_article(article_url, lang=lang)
            print(
                f"OK: get_article({article.article_id}, {lang}) -> {len(article.sections)} "
                f"sections, {article.word_count} words, pdf={article.pdf_url}"
            )
            ok &= bool(article.title) and article.word_count > 50
            ok &= bool(article.pdf_url) and article.release_date is not None
    try:
        await client.get_article("dq991231z")
        print("FAIL: expected NotFound for a made-up article id")
        ok = False
    except NotFound:
        print("OK: made-up article id raises NotFound as expected")

    for lang in ("en", "fr"):
        upcoming_list = await client.get_upcoming_releases(lang=lang)
        print(
            f"OK: get_upcoming_releases({lang}) -> {upcoming_list.period}: "
            f"{upcoming_list.total_in_window} releases, annual PDF "
            f"{upcoming_list.annual_schedule_pdf_url} ({upcoming_list.annual_schedule_label})"
        )
        ok &= upcoming_list.total_in_window > 0 and upcoming_list.start_date is not None
        ok &= any(r.lockup for r in upcoming_list.releases)
        ok &= bool(upcoming_list.pdf_url) and bool(upcoming_list.annual_schedule_pdf_url)
        ok &= len(upcoming_list.major_indicators) > 10

    # A current release with its tabs, walked back two releases.
    files = await client.get_release_files("dq261030a", previous=2)
    print(f"OK: get_release_files(dq261030a, previous=2) -> {files.returned_count} releases")
    ok &= files.returned_count == 3
    for release in files.releases:
        print(f"  {release.article_id}: {len(release.tables)} tables, pdf={release.pdf_url}")
        ok &= bool(release.pdf_url) and any(t.product_id for t in release.tables)
        ok &= any(s.sdds for s in release.surveys)
    # 2015 (Tables tab with old CANSIM numbers) and 2012 (no tabs, no <main>).
    for old in ("dq150130a", "dq120601a"):
        old_files = (await client.get_release_files(old)).releases[0]
        mapped = sum(1 for t in old_files.tables if t.legacy_cansim_id and t.product_id)
        print(f"OK: get_release_files({old}) -> {len(old_files.tables)} tables, {mapped} mapped")
        ok &= mapped > 0 and bool(old_files.pdf_url)

    print("\nSTATCAN DAILY SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
