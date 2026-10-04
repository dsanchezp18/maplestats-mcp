"""Tests for crea/client.py, shaped around the zip naming confirmed live
2026-10-03 (see the module docstring): short and full month spellings,
404 for a missing month, and no request other than HEAD.
"""

from __future__ import annotations

from datetime import date

import httpx

from maplestats_mcp.modules.crea import client

_SEPT = "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_Sept_2026.zip"
_SEPTEMBER = "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_September_2026.zip"
_APR = "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_Apr_2026.zip"
_APRIL = "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_April_2026.zip"


def test_release_month_waits_for_the_mid_month_release():
    assert client.release_month(date(2026, 10, 3)) == (2026, 9)
    assert client.release_month(date(2026, 10, 19)) == (2026, 9)
    assert client.release_month(date(2026, 10, 20)) == (2026, 10)
    assert client.release_month(date(2026, 1, 5)) == (2025, 12)


def test_candidate_urls_try_short_then_full_spelling():
    assert client.candidate_urls(2026, 9) == [_SEPT, _SEPTEMBER]
    # May has one spelling, so one HEAD.
    assert client.candidate_urls(2026, 5) == [
        "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_May_2026.zip"
    ]


async def test_confirmed_zip_returns_links_and_terms_without_values(httpx_mock):
    httpx_mock.add_response(
        method="HEAD",
        url=_SEPT,
        headers={"Content-Length": "3204582", "Last-Modified": "Mon, 14 Sep 2026 22:15:52 GMT"},
    )
    result = await client.get_hpi_links(today=date(2026, 10, 3))
    assert result.release_month == "2026-09"
    assert result.zip_confirmed is True
    assert result.zip_url == _SEPT
    assert result.download_from == _SEPT
    assert result.zip_size_bytes == 3204582
    assert result.attribution == (
        "Source: The Canadian Real Estate Association (CREA), MLS® Home Price Index"
    )
    assert {page.key for page in result.pages} >= {"hpi_tool", "national_statistics", "terms"}
    assert [alt.table_id for alt in result.open_alternatives][:2] == [
        "18-10-0205-01",
        "46-10-0030-01",
    ]
    assert "written consent" in (result.provenance.limits or "")
    assert result.provenance.url == _SEPT
    # Only the one HEAD: the zip is never downloaded and no stats page is fetched.
    requests = httpx_mock.get_requests()
    assert [(r.method, str(r.url)) for r in requests] == [("HEAD", _SEPT)]


async def test_full_month_spelling_is_tried_after_a_404(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_APR, status_code=404)
    httpx_mock.add_response(method="HEAD", url=_APRIL, headers={"Content-Length": "10"})
    result = await client.get_hpi_links(today=date(2026, 5, 2))
    assert result.zip_url == _APRIL
    assert result.zip_confirmed is True


async def test_missing_zip_falls_back_to_the_hpi_tool_page(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_SEPT, status_code=404)
    httpx_mock.add_response(method="HEAD", url=_SEPTEMBER, status_code=404)
    result = await client.get_hpi_links(today=date(2026, 10, 3), lang="fr")
    assert result.zip_url is None
    assert result.zip_confirmed is False
    assert "essayez-loutil-ipp-mls" in result.download_from
    assert result.attribution.startswith("Source : L'Association canadienne de l'immeuble")
    assert result.provenance.url == result.download_from


async def test_network_failure_falls_back_instead_of_raising(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectTimeout("timed out"), method="HEAD", url=_SEPT)
    httpx_mock.add_exception(httpx.ConnectTimeout("timed out"), method="HEAD", url=_SEPT)
    httpx_mock.add_exception(httpx.ConnectTimeout("timed out"), method="HEAD", url=_SEPT)
    result = await client.get_hpi_links(today=date(2026, 10, 3))
    assert result.zip_confirmed is False
    assert result.download_from.endswith("/hpi-tool/")


async def test_result_is_cached_for_the_release_month(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_SEPT)
    first = await client.get_hpi_links(today=date(2026, 10, 3))
    second = await client.get_hpi_links(today=date(2026, 10, 4))
    assert first.provenance.cached is False
    assert second.provenance.cached is True
    assert len(httpx_mock.get_requests()) == 1
