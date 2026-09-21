from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.daily import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError


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
