"""Tests for aer/client.py, shaped around real AER quirks confirmed live
2026-09-22 (see client.py's module docstring): the static.aer.ca bypass
for ST1 .TXT files, real HTTP 303 redirects for ST3/.zip files, and the
2023/2024 archive-URL path-prefix boundary.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.aer import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)

_SAMPLE_DAILY_TEXT = """                                        ALBERTA ENERGY REGULATOR

                                   WELL LICENCES ISSUED  DAILY LIST

    DATE:  15 September 2026

    CVE N23P05 FISHER 7-5-71-4           0510289   ALBERTA CROWN        669.50M
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


async def test_get_well_licences_daily_parses_report_date(httpx_mock):
    httpx_mock.add_response(
        url=constants.WELL_LICENCE_DAILY_URL.format(day_code="TUE"), text=_SAMPLE_DAILY_TEXT
    )
    result = await client.get_well_licences_daily("tuesday")
    assert result.day == "tuesday"
    assert result.report_date is not None
    assert result.report_date.isoformat() == "2026-09-15"
    assert "FISHER" in result.raw_text


async def test_get_well_licences_daily_invalid_day_raises():
    with pytest.raises(InvalidInput):
        await client.get_well_licences_daily("someday")


async def test_get_well_licences_daily_default_day_is_valid(httpx_mock):
    httpx_mock.add_response(text=_SAMPLE_DAILY_TEXT)
    result = await client.get_well_licences_daily()
    assert result.day in constants.DAY_CODES


async def test_get_well_licences_daily_missing_date_line_returns_none(httpx_mock):
    httpx_mock.add_response(
        url=constants.WELL_LICENCE_DAILY_URL.format(day_code="MON"), text="no date line here"
    )
    result = await client.get_well_licences_daily("monday")
    assert result.report_date is None


async def test_get_well_licence_archive_link_current_year_month(httpx_mock):
    url = constants.WELL_LICENCE_MONTHLY_ZIP_URL.format(year=2026, month=3)
    # Live, static.aer.ca sends Content-Length on HEAD only when the request
    # asks for identity encoding; with gzip it sends none (2026-10-03).
    httpx_mock.add_response(
        url=url,
        headers={"content-length": "123456"},
        match_headers={"Accept-Encoding": "identity"},
    )
    result = await client.get_well_licence_archive_link(2026, 3)
    assert result.url == url
    assert result.exists is True
    assert result.size_bytes == 123456


async def test_get_well_licence_archive_link_recent_year_no_month(httpx_mock):
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_NEW.format(year=2025)
    httpx_mock.add_response(url=url)
    result = await client.get_well_licence_archive_link(2025)
    assert result.url == url


async def test_get_well_licence_archive_link_old_year_uses_pre_prd_path(httpx_mock):
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=2023)
    httpx_mock.add_response(url=url)
    result = await client.get_well_licence_archive_link(2023)
    assert result.url == url
    assert "prd" not in result.url


async def test_get_well_licence_archive_link_missing_reports_not_exists(httpx_mock):
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=2018)
    httpx_mock.add_response(url=url, status_code=404)
    result = await client.get_well_licence_archive_link(2018)
    assert result.exists is False
    assert result.size_bytes is None
    assert result.note is not None


async def test_archive_link_blocked_head_is_an_error_not_a_missing_file(httpx_mock):
    # A 403 or a 5xx says nothing about the file: it must not read as "no
    # file at this address", and must not be cached as one.
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=2018)
    httpx_mock.add_response(url=url, method="HEAD", status_code=403)
    with pytest.raises(UpstreamError, match="HTTP 403"):
        await client.get_well_licence_archive_link(2018)
    for _ in range(3):
        httpx_mock.add_response(url=url, method="HEAD", status_code=503)
    with pytest.raises(UpstreamUnavailable, match="HTTP 503"):
        await client.get_well_licence_archive_link(2018)
    httpx_mock.add_response(url=url, method="HEAD", headers={"content-length": "10"})
    assert (await client.get_well_licence_archive_link(2018)).exists is True


async def test_get_well_licence_archive_link_year_outside_archive_raises():
    with pytest.raises(InvalidInput, match="2017"):
        await client.get_well_licence_archive_link(1850)
    with pytest.raises(InvalidInput):
        await client.get_well_licence_archive_link(2999)


def test_expected_date_is_the_latest_matching_weekday():
    saturday = date(2026, 10, 3)
    assert client._expected_date("saturday", saturday) == saturday
    assert client._expected_date("friday", saturday) == date(2026, 10, 2)
    assert client._expected_date("sunday", saturday) == date(2026, 9, 27)


async def test_stale_weekday_file_gets_a_note_and_as_of(httpx_mock):
    # Each weekday file is overwritten weekly; one still holding an older week
    # (the 2026-09-15 text here) is flagged rather than passed off as current.
    httpx_mock.add_response(
        url=constants.WELL_LICENCE_DAILY_URL.format(day_code="TUE"), text=_SAMPLE_DAILY_TEXT
    )
    result = await client.get_well_licences_daily("tuesday")
    assert result.note is not None and "2026-09-15" in result.note
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.date() == date(2026, 9, 15)


async def test_get_well_licence_archive_link_invalid_month_raises():
    with pytest.raises(InvalidInput):
        await client.get_well_licence_archive_link(2026, 13)


async def test_get_production_volumes_link_resolves_url(httpx_mock):
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path="Oil")
    httpx_mock.add_response(
        url=url,
        headers={"content-length": "5000", "last-modified": "Tue, 25 Aug 2026 02:11:39 GMT"},
    )
    result = await client.get_production_volumes_link("oil")
    assert result.url == url
    assert result.exists is True
    assert result.size_bytes == 5000
    assert result.last_modified == "Tue, 25 Aug 2026 02:11:39 GMT"


async def test_get_production_volumes_link_invalid_product_raises():
    with pytest.raises(InvalidInput):
        await client.get_production_volumes_link("not-a-product")


async def test_french_invalid_day_error_is_french():
    with pytest.raises(InvalidInput, match="Entrée invalide : day doit être"):
        await client.get_well_licences_daily("someday", lang="fr")


async def test_french_year_error_is_french():
    with pytest.raises(InvalidInput, match="l'archive ST1 de l'AER commence en 2017"):
        await client.get_well_licence_archive_link(1850, lang="fr")


async def test_french_daily_report_has_french_note_and_provenance(httpx_mock):
    httpx_mock.add_response(
        url=constants.WELL_LICENCE_DAILY_URL.format(day_code="TUE"), text=_SAMPLE_DAILY_TEXT
    )
    result = await client.get_well_licences_daily("tuesday", lang="fr")
    assert result.note is not None
    assert "Voici la liste du 2026-09-15 :" in result.note
    assert "n'existent qu'en anglais ;" in result.note
    assert result.provenance.freshness is not None
    assert "publié chaque nuit" in result.provenance.freshness
    assert result.provenance.reproduce.startswith("Pour obtenir")


async def test_french_missing_archive_note_is_french(httpx_mock):
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=2018)
    httpx_mock.add_response(url=url, status_code=404)
    result = await client.get_well_licence_archive_link(2018, lang="fr")
    assert result.note is not None
    assert result.note.startswith("L'AER n'a aucun fichier")


async def test_french_production_volumes_provenance(httpx_mock):
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path="Oil")
    httpx_mock.add_response(url=url)
    result = await client.get_production_volumes_link("oil", lang="fr")
    assert result.provenance.freshness == "ST3 est publié chaque mois, avec un mois de décalage"
    assert result.provenance.limits is not None and "anglais" in result.provenance.limits
    english = await client.get_production_volumes_link("oil")
    assert english.provenance.freshness == "ST3 is released monthly, one month in arrears"
    assert english.provenance.limits is None


async def test_get_production_volumes_link_oil_prices_uses_prices_oil_path(httpx_mock):
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path="prices_oil")
    httpx_mock.add_response(url=url)
    result = await client.get_production_volumes_link("oil_prices")
    assert result.url == url


# A non-2xx answer for the daily file used to be reported as "did not respond
# in time" (UpstreamUnavailable): the raw client call skipped the shared retry
# rules and the one handler caught HTTPStatusError with every network error.

_MONDAY = constants.WELL_LICENCE_DAILY_URL.format(day_code="MON")


async def test_daily_file_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_MONDAY, status_code=404)
    with pytest.raises(NotFound, match=r"WELLSMON\.TXT.*HTTP 404"):
        await client.get_well_licences_daily("monday")
    assert len(httpx_mock.get_requests()) == 1


async def test_daily_file_404_in_french(httpx_mock):
    httpx_mock.add_response(url=_MONDAY, status_code=404)
    with pytest.raises(NotFound, match="aucun fichier quotidien"):
        await client.get_well_licences_daily("monday", lang="fr")


async def test_daily_file_403_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_MONDAY, status_code=403)
    with pytest.raises(UpstreamError, match="returned HTTP 403"):
        await client.get_well_licences_daily("monday")


async def test_daily_file_5xx_is_retried_then_an_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=_MONDAY, status_code=503)
    with pytest.raises(UpstreamError, match="returned HTTP 503"):
        await client.get_well_licences_daily("monday")
    assert len(httpx_mock.get_requests()) == 3


async def test_daily_file_recovers_after_a_transient_5xx(httpx_mock):
    httpx_mock.add_response(url=_MONDAY, status_code=502)
    httpx_mock.add_response(url=_MONDAY, text=_SAMPLE_DAILY_TEXT)
    result = await client.get_well_licences_daily("monday")
    assert "FISHER" in result.raw_text


async def test_daily_file_network_error_is_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"), url=_MONDAY)
    with pytest.raises(UpstreamUnavailable, match="did not respond in time"):
        await client.get_well_licences_daily("monday")
