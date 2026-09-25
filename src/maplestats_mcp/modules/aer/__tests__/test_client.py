"""Tests for aer/client.py, shaped around real AER quirks confirmed live
2026-09-22 (see client.py's module docstring): the static.aer.ca bypass
for ST1 .TXT files, real HTTP 303 redirects for ST3/.zip files, and the
2023/2024 archive-URL path-prefix boundary.
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.aer import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

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
    httpx_mock.add_response(url=url, headers={"content-length": "123456"})
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
    url = constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=1999)
    httpx_mock.add_response(url=url, status_code=404)
    result = await client.get_well_licence_archive_link(1999)
    assert result.exists is False
    assert result.size_bytes is None


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


async def test_get_production_volumes_link_oil_prices_uses_prices_oil_path(httpx_mock):
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path="prices_oil")
    httpx_mock.add_response(url=url)
    result = await client.get_production_volumes_link("oil_prices")
    assert result.url == url
