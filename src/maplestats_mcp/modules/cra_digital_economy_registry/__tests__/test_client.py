"""Tests for cra_digital_economy_registry/client.py, shaped around the
real page structure confirmed live 2026-09-21: the entire registry is
server-rendered in one `table.wb-tables`, with `wb-inv` "-" markers for
an absent trade name or de-registration date (see client.py docstring).
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.cra_digital_economy_registry import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_REGISTRY_HTML = """
<html><body>
<table class="wb-tables table">
<caption>Registered simplified GST/HST digital economy businesses</caption>
<thead><tr><th>Legal name</th><th>Operating or trade name(s)</th>
<th>Business number</th><th>Effective registration date</th>
<th>Effective de-registration date</th></tr></thead>
<tbody>
<tr><td>AIRGSM PTE. LTD.</td><td>Airalo</td><td>751950577RT9999</td>
<td><span class="nowrap">September 1, 2026</span></td>
<td><span class="wb-inv">-</span></td></tr>
<tr><td>BERG SHOW LLC</td><td><span class="wb-inv">-</span></td>
<td>752047175RT9999</td><td><span class="nowrap">September 15, 2026</span></td>
<td><span class="wb-inv">-</span></td></tr>
<tr><td>1 &amp; 1 MAIL &amp; MEDIA INC.</td><td><span class="wb-inv">-</span></td>
<td>792079006RT0001</td><td><span class="nowrap">July 1, 2021</span></td>
<td><span class="nowrap">June 30, 2023</span></td></tr>
</tbody>
</table>
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


async def test_search_registrants_parses_all_rows_with_no_query(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants()
    assert result.total_registrants == 3
    assert result.returned_count == 3
    first = result.registrants[0]
    assert first.legal_name == "AIRGSM PTE. LTD."
    assert first.trade_name == "Airalo"
    assert first.business_number == "751950577RT9999"
    assert first.effective_registration_date == "September 1, 2026"
    assert first.effective_deregistration_date is None


async def test_search_registrants_treats_wb_inv_dash_as_none(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants()
    second = result.registrants[1]
    assert second.trade_name is None


async def test_search_registrants_keeps_re_registered_rows_distinct(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants()
    third = result.registrants[2]
    assert third.business_number == "792079006RT0001"
    assert third.effective_deregistration_date == "June 30, 2023"


async def test_search_registrants_filters_by_query_case_insensitive(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants("airalo")
    assert result.returned_count == 1
    assert result.registrants[0].legal_name == "AIRGSM PTE. LTD."


async def test_search_registrants_filters_by_business_number(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants("752047175")
    assert result.returned_count == 1
    assert result.registrants[0].legal_name == "BERG SHOW LLC"


async def test_search_registrants_no_match_returns_empty(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants("no such business")
    assert result.returned_count == 0
    assert result.total_matched == 0
    assert result.total_registrants == 3


async def test_search_registrants_fr_uses_french_url(httpx_mock):
    httpx_mock.add_response(url=constants.URL_FR, html=_REGISTRY_HTML)
    result = await client.search_registrants(lang="fr")
    assert result.total_registrants == 3


async def test_search_registrants_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.search_registrants(lang="de")


async def test_search_registrants_missing_table_raises(httpx_mock):
    httpx_mock.add_response(url=constants.URL_EN, html="<html><body>nope</body></html>")
    with pytest.raises(UpstreamError):
        await client.search_registrants()


async def test_search_registrants_truncates_and_sets_coverage(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "SEARCH_RESULTS_MAX", 1)
    httpx_mock.add_response(url=constants.URL_EN, html=_REGISTRY_HTML)
    result = await client.search_registrants()
    assert result.returned_count == 1
    assert result.total_matched == 3
    assert result.provenance.coverage is not None
    assert "1 of 3" in result.provenance.coverage
