from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.reference import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_state():
    cache_module._caches.clear()
    client._warmed.clear()
    yield


_RESULTS_HTML = """
<html><body>
<form><input name="text" value="housing"><input name="texte" value="logement"></form>
<div id="ndm-results">
<details id="all"><summary>All&nbsp;(2,031)</summary>
<ul data-offset="0">
<li class="ndm-item"><div class="ndm-result-container">
<div class="ndm-result-title"><span>1. <a href="/n1/en/catalogue/16-511-X" target="_self">Clean technologies and the Survey of Environmental Goods and Services</a></span></div>
<div class="ndm-result-productid"><span>Surveys and statistical programs – Documentation:</span> 16-511-X</div>
<div class="ndm-result-description"><span class="ndm-result-heading">Description:</span> A technical reference guide for SEGS users.</div>
<div class="ndm-result-date"><span class="ndm-result-heading">Release date: </span><span class="ndm-result-date">2026-08-19</span></div>
</div></li>
<li class="ndm-item"><div class="ndm-result-container">
<div class="ndm-result-title"><span>2. <a href="https://www150.statcan.gc.ca/n1/pub/92f0138m/92f0138m2026001-eng.htm" target="_self">Dissemination Geography Unique Identifier</a></span></div>
<div class="ndm-result-productid"><span>Geographic files and documentation:</span> 92F0138M2026001</div>
<div class="ndm-result-description"><span class="ndm-result-heading">Description:</span> Describes the DGUID structure.</div>
<div class="ndm-result-date"><span class="ndm-result-heading">Release date: </span><span class="ndm-result-date">2026-08-05</span></div>
</div></li>
</ul>
</details>
<details id="surveysandstatisticalprogramsdocumentation"><summary>Surveys and statistical programs – Documentation&nbsp;(1)</summary>
<ul data-offset="0">
<li class="ndm-item"><div class="ndm-result-container">
<div class="ndm-result-title"><span>1. <a href="/n1/en/catalogue/16-511-X" target="_self">Clean technologies and the Survey of Environmental Goods and Services</a></span></div>
<div class="ndm-result-productid"><span>Surveys and statistical programs – Documentation:</span> 16-511-X</div>
<div class="ndm-result-description"><span class="ndm-result-heading">Description:</span> A technical reference guide for SEGS users.</div>
<div class="ndm-result-date"><span class="ndm-result-heading">Release date: </span><span class="ndm-result-date">2026-08-19</span></div>
</div></li>
</ul>
</details>
</div>
</body></html>
"""

_BASE_URL_EN = constants.BASE_URL_TEMPLATE.format(lang="en", path="reference")
_BASE_URL_FR = constants.BASE_URL_TEMPLATE.format(lang="fr", path="references")


async def test_search_documents_parses_entries(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")  # warm-up
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing", html=_RESULTS_HTML)
    result = await client.search_documents("housing")
    assert result.total_matched == 2031
    assert result.returned_count == 2
    first = result.documents[0]
    assert first.catalogue_number == "16-511-X"
    assert first.category == "Surveys and statistical programs – Documentation"
    assert first.description == "A technical reference guide for SEGS users."
    assert first.release_date == "2026-08-19"
    assert first.url == "https://www150.statcan.gc.ca/n1/en/catalogue/16-511-X"


async def test_search_documents_keeps_absolute_url_as_is(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing", html=_RESULTS_HTML)
    result = await client.search_documents("housing")
    second = result.documents[1]
    assert second.url == "https://www150.statcan.gc.ca/n1/pub/92f0138m/92f0138m2026001-eng.htm"


async def test_search_documents_warms_up_once(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=a", html=_RESULTS_HTML)
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=b", html=_RESULTS_HTML)
    await client.search_documents("a")
    await client.search_documents("b")
    warmup_requests = [r for r in httpx_mock.get_requests() if str(r.url) == _BASE_URL_EN]
    assert len(warmup_requests) == 1


async def test_search_documents_empty_query_omits_query_param(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10", html=_RESULTS_HTML)
    await client.search_documents("")


async def test_search_documents_fr_uses_texte_param_and_plural_path(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_FR, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_FR}?count=10&texte=logement", html=_RESULTS_HTML)
    await client.search_documents("logement", lang="fr")


async def test_search_documents_pagination_param(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing&p=1-All", html=_RESULTS_HTML)
    await client.search_documents("housing", page=2)


async def test_search_documents_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.search_documents("housing", lang="de")


async def test_search_documents_invalid_count_raises():
    with pytest.raises(InvalidInput):
        await client.search_documents("housing", count=0)


async def test_search_documents_invalid_page_raises():
    with pytest.raises(InvalidInput):
        await client.search_documents("housing", page=-1)


async def test_search_documents_missing_results_container_raises(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(
        url=f"{_BASE_URL_EN}?count=10&text=housing", html="<html><body>nope</body></html>"
    )
    with pytest.raises(UpstreamError):
        await client.search_documents("housing")


async def test_search_documents_upstream_5xx_becomes_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing", status_code=500)
    with pytest.raises(UpstreamError):
        await client.search_documents("housing")


_ANALYSIS_BASE_URL_EN = constants.BASE_URL_TEMPLATE.format(lang="en", path="analysis")


async def test_search_analysis_parses_entries_and_sets_catalogue(httpx_mock):
    httpx_mock.add_response(url=_ANALYSIS_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(
        url=f"{_ANALYSIS_BASE_URL_EN}?count=10&text=housing", html=_RESULTS_HTML
    )
    result = await client.search_analysis("housing")
    assert result.catalogue == "analysis"
    assert result.returned_count == 2


async def test_search_documents_and_search_analysis_warm_up_independently(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=_ANALYSIS_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=a", html=_RESULTS_HTML)
    httpx_mock.add_response(url=f"{_ANALYSIS_BASE_URL_EN}?count=10&text=a", html=_RESULTS_HTML)
    await client.search_documents("a")
    await client.search_analysis("a")
    warmups = [
        r for r in httpx_mock.get_requests() if str(r.url) in (_BASE_URL_EN, _ANALYSIS_BASE_URL_EN)
    ]
    assert len(warmups) == 2


_DATA_BASE_URL_EN = constants.BASE_URL_TEMPLATE.format(lang="en", path="data")
_DATA_BASE_URL_FR = constants.BASE_URL_TEMPLATE.format(lang="fr", path="donnees")


async def test_search_data_parses_entries_and_sets_catalogue(httpx_mock):
    httpx_mock.add_response(url=_DATA_BASE_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=f"{_DATA_BASE_URL_EN}?count=10&text=microdata", html=_RESULTS_HTML)
    result = await client.search_data("microdata")
    assert result.catalogue == "data"
    assert result.returned_count == 2


async def test_search_data_fr_uses_texte_param_and_donnees_path(httpx_mock):
    httpx_mock.add_response(url=_DATA_BASE_URL_FR, html="<html></html>")
    httpx_mock.add_response(
        url=f"{_DATA_BASE_URL_FR}?count=10&texte=microdonnees", html=_RESULTS_HTML
    )
    await client.search_data("microdonnees", lang="fr")


_IGNORED_QUERY_HTML = _RESULTS_HTML.replace('value="housing"', 'value=""').replace(
    'value="logement"', 'value=""'
)


async def test_expired_session_rewarms_and_retries(httpx_mock):
    client._warmed.add(("reference", "en"))  # warmed earlier in the process
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing", html=_IGNORED_QUERY_HTML)
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>")  # forced re-warm
    httpx_mock.add_response(url=f"{_BASE_URL_EN}?count=10&text=housing", html=_RESULTS_HTML)
    result = await client.search_documents("housing")
    assert result.returned_count == 2
    warmups = [r for r in httpx_mock.get_requests() if str(r.url) == _BASE_URL_EN]
    assert len(warmups) == 1


async def test_ignored_query_after_rewarm_raises_instead_of_returning_everything(httpx_mock):
    httpx_mock.add_response(url=_BASE_URL_EN, html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=f"{_BASE_URL_EN}?count=10&text=housing", html=_IGNORED_QUERY_HTML, is_reusable=True
    )
    with pytest.raises(UpstreamError):
        await client.search_documents("housing")
    assert ("reference", "en") not in client._warmed
