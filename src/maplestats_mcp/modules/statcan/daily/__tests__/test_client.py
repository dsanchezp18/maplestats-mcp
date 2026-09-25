from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.daily import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_ATOM_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Statistics Canada, The Daily: Housing</title>
  <updated>2026-09-18T08:30:00-04:00</updated>
  <entry>
    <title type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">Quarterly rent statistics, <span class="refper">second quarter 2026</span></div>
    </title>
    <link href="https://www.statcan.gc.ca/daily-quotidien/260909/dq260909c-eng.htm"></link>
    <id>https://www.statcan.gc.ca/daily-quotidien/260909/dq260909c-eng.htm</id>
    <updated>2026-09-09T08:30:00-04:00</updated>
    <summary type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">The average asking rent was $2,130 per month.</div>
    </summary>
  </entry>
  <entry>
    <title type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">Product/Study: Analysis in Brief</div>
    </title>
    <link href="https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=11-621-M"></link>
    <id>https://www.statcan.gc.ca/cgi-bin/IPS/display?cat_num=11-621-M</id>
    <updated>2026-09-02T08:30:00-04:00</updated>
    <summary type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">Catalogue number 11-621-M (HTML | PDF)</div>
    </summary>
  </entry>
</feed>
"""


async def test_get_releases_parses_entries(httpx_mock):
    url = f"{constants.BASE_URL}/46-eng.atom"
    httpx_mock.add_response(url=url, content=_ATOM_BODY)
    result = await client.get_releases("housing")
    assert result.returned_count == 2
    first = result.releases[0]
    assert first.title == "Quarterly rent statistics, second quarter 2026"
    assert first.url == "https://www.statcan.gc.ca/daily-quotidien/260909/dq260909c-eng.htm"
    assert first.published_at is not None
    assert first.published_at.year == 2026
    assert "2,130" in (first.summary or "")


async def test_get_releases_second_entry_is_a_product_announcement(httpx_mock):
    url = f"{constants.BASE_URL}/46-eng.atom"
    httpx_mock.add_response(url=url, content=_ATOM_BODY)
    result = await client.get_releases("housing")
    second = result.releases[1]
    assert "cat_num=11-621-M" in second.url


async def test_get_releases_respects_limit(httpx_mock):
    url = f"{constants.BASE_URL}/46-eng.atom"
    httpx_mock.add_response(url=url, content=_ATOM_BODY)
    result = await client.get_releases("housing", limit=1)
    assert result.returned_count == 1


async def test_get_releases_default_subject_is_all(httpx_mock):
    url = f"{constants.BASE_URL}/0-eng.atom"
    httpx_mock.add_response(url=url, content=_ATOM_BODY)
    result = await client.get_releases()
    assert result.subject == "all"


async def test_get_releases_fr_uses_fra_suffix(httpx_mock):
    url = f"{constants.BASE_URL}/46-fra.atom"
    httpx_mock.add_response(url=url, content=_ATOM_BODY)
    await client.get_releases("housing", lang="fr")


async def test_get_releases_invalid_subject_raises():
    with pytest.raises(InvalidInput):
        await client.get_releases("not_a_real_subject")


async def test_get_releases_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.get_releases("housing", limit=0)


async def test_get_releases_upstream_5xx_becomes_upstream_error(httpx_mock):
    url = f"{constants.BASE_URL}/46-eng.atom"
    for _ in range(3):
        httpx_mock.add_response(url=url, status_code=500)
    with pytest.raises(UpstreamError):
        await client.get_releases("housing")


async def test_get_releases_invalid_xml_becomes_upstream_error(httpx_mock):
    url = f"{constants.BASE_URL}/46-eng.atom"
    httpx_mock.add_response(url=url, content=b"not xml at all")
    with pytest.raises(UpstreamError):
        await client.get_releases("housing")


_ARCHIVE_BODY = [
    {
        "rid": "3309",
        "date": "2012-03-14 00:00:01",
        "type": "meeting",
        "title": "Industrial capacity utilization rates",
        "description": "Fourth quarter 2011",
        "url": "/daily-quotidien/120314/dq120314a-eng.htm",
    },
    {
        "rid": "3341",
        "date": "2015-01-06 00:00:01",
        "type": "meeting",
        "title": "Industrial product and raw materials price indexes",
        "description": "November 2014",
        "url": "/daily-quotidien/150106/dq150106a-eng.htm",
    },
    {
        "rid": "9999",
        "date": "2020-06-01 00:00:01",
        "type": "meeting",
        "title": "Labour Force Survey",
        "description": "May 2020",
        "url": "/daily-quotidien/200601/dq200601a-eng.htm",
    },
]

_ARCHIVE_URL = constants.FULL_ARCHIVE_URL.format(suffix="eng")


async def test_search_archive_filters_by_query(httpx_mock):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_ARCHIVE_BODY)
    result = await client.search_archive("industrial")
    assert result.total_matched == 2
    assert all("industrial" in e.title.lower() for e in result.entries)


async def test_search_archive_sorts_most_recent_first(httpx_mock):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_ARCHIVE_BODY)
    result = await client.search_archive("")
    assert result.total_matched == 3
    dates = [e.release_date for e in result.entries]
    assert dates == sorted(dates, reverse=True)


async def test_search_archive_filters_by_date_range(httpx_mock):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_ARCHIVE_BODY)
    result = await client.search_archive("", start_date="2015-01-01", end_date="2015-12-31")
    assert result.total_matched == 1
    assert result.entries[0].title == "Industrial product and raw materials price indexes"


async def test_search_archive_resolves_relative_url(httpx_mock):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_ARCHIVE_BODY)
    result = await client.search_archive("industrial capacity")
    assert result.entries[0].url == (
        "https://www150.statcan.gc.ca/daily-quotidien/120314/dq120314a-eng.htm"
    )


async def test_search_archive_invalid_date_raises():
    with pytest.raises(InvalidInput):
        await client.search_archive("", start_date="not-a-date")


async def test_search_archive_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.search_archive("", limit=0)


async def test_search_archive_fr_uses_fra_url(httpx_mock):
    url = constants.FULL_ARCHIVE_URL.format(suffix="fra")
    httpx_mock.add_response(url=url, json=_ARCHIVE_BODY)
    await client.search_archive("", lang="fr")


async def test_search_archive_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=_ARCHIVE_URL, status_code=500)
    with pytest.raises(UpstreamError):
        await client.search_archive("")
