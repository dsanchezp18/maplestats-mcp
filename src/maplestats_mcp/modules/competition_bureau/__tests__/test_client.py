"""Tests on rows trimmed from the live report pages (2026-09-25)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.modules.competition_bureau import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_HERE = Path(__file__).parent
_CURRENT = (_HERE / "current.html").read_text(encoding="utf-8")
_ARCHIVE = (_HERE / "archive.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def pages(httpx_mock):
    httpx_mock.add_response(url=constants.CURRENT_URL, text=_CURRENT, is_reusable=True)
    httpx_mock.add_response(url=constants.ARCHIVE_URL, text=_ARCHIVE, is_reusable=True)


def test_current_report_reads_dates_and_ongoing():
    reviews = client.parse_current(_CURRENT)
    assert len(reviews) == 9  # header and footnote rows skipped
    ongoing = reviews[0]
    assert ongoing.outcome == "Ongoing" and ongoing.concluded is None
    assert ongoing.opened == date(2026, 8, 10)
    done = next(r for r in reviews if r.parties.startswith("Tamarack"))
    assert done.concluded == date(2026, 9, 21) and done.concluded_month == "2026-09"
    assert done.naics == "2111" and done.outcome == "ARC"


def test_archive_has_months_only():
    reviews = client.parse_archive(_ARCHIVE)
    assert len(reviews) == 5
    assert reviews[0].concluded_month == "2023-04" and reviews[0].opened is None
    assert all(r.report == "archive" for r in reviews)


async def test_search_combines_reports_newest_first(pages):
    result = await client.search_mergers(naics="2111")
    assert [r.parties.split(" /")[0] for r in result.reviews] == [
        "Tamarack Valley Energy Ltd",
        "Crescent Point Resources Partnership",
    ]
    assert result.outcome_counts == {"ARC": 2}


async def test_filters(pages):
    assert (await client.search_mergers("sony tcl")).total_matched == 1  # every word
    assert (await client.search_mergers(outcome="NAL")).total_matched == 2
    ranged = await client.search_mergers(concluded_from="2025-10", concluded_to="2025-10-31")
    assert ranged.total_matched == 3  # a day in a bound is ignored
    closed = await client.search_mergers(include_ongoing=False)
    assert "Ongoing" not in closed.outcome_counts


async def test_french_labels(pages):
    result = await client.search_mergers(outcome="NAL", lang="fr")
    assert result.reviews[0].outcome_label == "Lettre de non-intervention"
    assert result.outcome_legend["ARC"].startswith("Certificat")


async def test_bad_input_and_missing_table(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_mergers(outcome="merged")
    with pytest.raises(InvalidInput):
        await client.search_mergers(concluded_from="2020")
    httpx_mock.add_response(url=constants.CURRENT_URL, text="<html></html>")
    httpx_mock.add_response(url=constants.ARCHIVE_URL, text=_ARCHIVE)
    with pytest.raises(UpstreamError, match="no longer has its table"):
        await client.search_mergers()
