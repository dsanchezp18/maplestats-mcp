"""Tests for cra_digital_economy_registry/client.py, shaped around the
real page structure confirmed live 2026-09-21: the entire registry is
server-rendered in one `table.wb-tables`, with `wb-inv` "-" markers for
an absent trade name or de-registration date (see client.py docstring).
"""

from __future__ import annotations

from datetime import date

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
    assert first.effective_registration_date == date(2026, 9, 1)
    assert first.registration_date_text == "September 1, 2026"
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
    assert third.effective_deregistration_date == date(2023, 6, 30)
    assert third.deregistration_date_text == "June 30, 2023"


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


# Rows copied from the live French page (2026-10-03), with the hand-typed
# variants that page and the English one carry.
_REGISTRY_HTML_FR = """
<html><body>
<table class="wb-tables table">
<thead><tr><th>Dénomination sociale</th><th>Nom commercial</th>
<th>Numéro d'entreprise</th><th>Date d'entrée en vigueur de l'inscription</th>
<th>Date d'entrée en vigueur de l'annulation de l'inscription</th></tr></thead>
<tbody>
<tr><td>NETFLIX, INC.</td>
<td><span class="wb-inv">-</span></td>
<td>810191114RT0001</td>
<td><span class="nowrap">1 juillet 2021</span></td>
<td><span class="nowrap">30 juin 2022</span></td>
</tr><tr><td>A</td><td><span class="wb-inv">-</span></td><td>1RT0001</td>
<td><span class="nowrap">1 septembre, 2026</span></td><td><span class="wb-inv">-</span></td>
</tr><tr><td>B</td><td><span class="wb-inv">-</span></td><td>2RT0001</td>
<td><span class="nowrap">février 3 2026</span></td><td><span class="nowrap">20 août2026</span></td>
</tr>
</tbody>
</table>
</body></html>
"""


async def test_french_dates_become_iso_dates(httpx_mock):
    # Before the fix these came back as "1 juillet 2021", unsortable text.
    httpx_mock.add_response(url=constants.URL_FR, html=_REGISTRY_HTML_FR)
    result = await client.search_registrants(lang="fr")
    netflix, a, b = result.registrants
    assert netflix.effective_registration_date == date(2021, 7, 1)
    assert netflix.effective_deregistration_date == date(2022, 6, 30)
    assert netflix.registration_date_text == "1 juillet 2021"
    assert a.effective_registration_date == date(2026, 9, 1)
    assert a.effective_deregistration_date is None
    assert b.effective_registration_date == date(2026, 2, 3)
    assert b.effective_deregistration_date == date(2026, 8, 20)
    dumped = netflix.model_dump(mode="json")
    assert dumped["effective_registration_date"] == "2021-07-01"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("July 1, 2023", date(2023, 7, 1)),
        ("July1, 2021", date(2021, 7, 1)),
        ("1er juillet 2021", date(2021, 7, 1)),
        ("Obtober 1, 2024", None),  # misspelt live; the text is kept instead
        ("February 30, 2024", None),
        (None, None),
    ],
)
def test_parse_date_variants(text, expected):
    assert client.parse_date(text) == expected
