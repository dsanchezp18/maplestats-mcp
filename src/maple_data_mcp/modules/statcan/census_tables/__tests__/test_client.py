"""Tests for census_tables/client.py, on markup trimmed from live pages (2026-09-24)."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.census_tables import client
from maple_data_mcp.shared import cache as cache_module

BASE = "https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/dt-td/"

INDEX_2016 = """
<a href="Lp-eng.cfm?LANG=E&amp;APATH=3&amp;GRP=1&amp;THEME=115&amp;VID=0">Age and sex</a>
<a href="Lp-eng.cfm?LANG=E&amp;APATH=3&amp;GRP=1&amp;THEME=0&amp;VID=0">All</a>
"""

INDEX_2006 = """
<a href="Lp-eng.cfm?LANG=E&amp;APATH=7&amp;GRP=1&amp;THEME=0&amp;VNAMEE=Aboriginal%20ancestry">Aboriginal ancestry (10)</a>
<a href="Index-eng.cfm?THEME=66">Aboriginal peoples</a>
"""

PAGE_1 = """<table><tbody>
<tr><td>1</td><td> 98-400-X2016097 </td>
<td> Household Total Income Groups (22) for Private Households of Canada </td>
<td><a href="Rp-eng.cfm?PID=110192">HTML</a> | <a href="Download.cfm?PID=110192">B20/20</a></td></tr>
</tbody></table>
<a href="Lp-eng.cfm?GRP=0&amp;StartRow=21&amp;THEME=115">Next</a>"""

PAGE_2 = """<table><tbody>
<tr><td>21</td><td> 98-400-X2016098 </td><td> Age (127) and Sex (3) for Canada </td>
<td><a href="Rp-eng.cfm?PID=110193">HTML</a></td></tr>
</tbody></table>"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def test_theme_urls_ungroup_and_skip_theme_zero():
    themes = client.theme_urls(INDEX_2016, BASE)
    assert list(themes) == ["Age and sex"]
    assert "GRP=0" in themes["Age and sex"] and "THEME=115" in themes["Age and sex"]


def test_2006_style_index_builds_theme_urls_from_template():
    themes = client.theme_urls(INDEX_2006, BASE)
    url = themes["Aboriginal peoples"]
    assert "APATH=3" in url and "THEME=66" in url and "GRP=0" in url
    assert "VNAMEE=&" in url or url.endswith("VNAMEE=")


def test_list_page_rows_and_next_link():
    rows, next_url = client.parse_list_page(PAGE_1, "2016", "Income", BASE + "Lp-eng.cfm")
    assert [(r.pid, r.catalogue_number, r.has_ivt) for r in rows] == [
        ("110192", "98-400-X2016097", True)
    ]
    assert next_url is not None and "StartRow=21" in next_url


async def test_search_crawls_pages_and_requires_every_word(httpx_mock):
    httpx_mock.add_response(url=BASE + "index-eng.cfm", text=INDEX_2016)
    httpx_mock.add_response(text=PAGE_1)
    httpx_mock.add_response(text=PAGE_2)
    result = await client.search("income households")
    assert result.total_tables == 2
    assert [t.pid for t in result.tables] == ["110192"]


async def test_ivt_only_table_gets_canivt_note(httpx_mock):
    httpx_mock.add_response(url=BASE + "CompDataDownload.cfm?LANG=E&PID=5&OFT=CSV", status_code=404)
    httpx_mock.add_response(
        url=BASE + "OpenDataDownload.cfm?PID=5", headers={"content-type": "text/html"}
    )
    httpx_mock.add_response(
        url=BASE + "Download.cfm?PID=5",
        headers={"content-type": "application/x-beyond2020", "content-length": "0"},
    )
    result = await client.get_downloads("5")
    assert result.ivt_only
    assert result.ivt_note is not None and "canivt::read_ivt" in result.ivt_note
    assert [d.size_bytes for d in result.downloads] == [None, None, None]
