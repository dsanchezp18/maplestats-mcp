from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.daily import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# Shapes confirmed live 2026-10-02: indicator rows carry an artificial
# time-of-day in "date" and an empty "url" until published; product rows add
# "release_date" and "pid" and the file has no future dates.
_INDICATORS = [
    {
        "date": "2012-03-16 00:00:01",
        "type": "meeting",
        "title": "Monthly Survey of Manufacturing",
        "description": "January 2012",
        "url": "/daily-quotidien/120316/dq120316a-eng.htm",
    },
    {
        "date": "2099-01-09 00:00:02",
        "type": "meeting",
        "title": "Labour Force Survey",
        "description": "December 2098",
        "url": "",
    },
    {
        "date": "2099-01-09 00:00:01",
        "type": "meeting",
        "title": "Enquête sur la population active",
        "description": "December 2098",
        "url": "",
    },
    {
        "date": "2098-12-04 00:00:01",
        "type": "meeting",
        "title": "Canadian international merchandise trade",
        "description": "October 2098",
        "url": "",
    },
]
_PRODUCTS = [
    {
        "date": "2012-04-02 00:00:00",
        "release_date": "2012-04-02",
        "pid": "45-004-X2012001",
        "type": "meeting",
        "title": "The Supply and Disposition of Refined Petroleum Products in Canada",
        "description": "Catalogue number 45-004-X2012001 (HTML | PDF)",
        "url": "/en/catalogue/45-004-X",
    }
]
_INDICATORS_URL = constants.KEY_INDICATORS_URL.format(suffix="eng")
_PRODUCTS_URL = constants.PRODUCTS_URL.format(suffix="eng")


async def test_calendar_upcoming_is_soonest_first_and_has_no_url(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar()
    assert result.entries[0].title == "Canadian international merchandise trade"
    assert result.total_matched == 3
    assert all(e.scheduled and e.url is None for e in result.entries)
    assert str(result.latest_scheduled_date) == "2099-01-09"


async def test_calendar_query_ignores_accents_and_needs_every_word(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar("enquete population")
    assert [e.title for e in result.entries] == ["Enquête sur la population active"]
    none = await client.get_release_calendar("labour trade")
    assert none.total_matched == 0


async def test_calendar_history_is_newest_first_with_full_url(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar(
        "manufacturing", upcoming_only=False, end_date="2012-12-31"
    )
    entry = result.entries[0]
    assert not entry.scheduled
    assert entry.release_date.year == 2012
    assert entry.url == "https://www150.statcan.gc.ca/daily-quotidien/120316/dq120316a-eng.htm"


async def test_calendar_products_have_no_future_rows(httpx_mock):
    httpx_mock.add_response(url=_PRODUCTS_URL, json=_PRODUCTS)
    upcoming = await client.get_release_calendar(kind="products")
    assert upcoming.total_matched == 0
    history = await client.get_release_calendar("45-004-X", kind="products", upcoming_only=False)
    assert history.entries[0].catalogue_number == "45-004-X2012001"
    assert history.entries[0].reference_period is None


async def test_calendar_rejects_bad_kind_and_date():
    with pytest.raises(InvalidInput):
        await client.get_release_calendar(kind="nope")
    with pytest.raises(InvalidInput):
        await client.get_release_calendar(start_date="soon")
