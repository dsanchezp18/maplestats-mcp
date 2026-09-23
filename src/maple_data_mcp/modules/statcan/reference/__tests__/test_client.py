from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.reference import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


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


_DOCUMENT_FORMATS_HTML = """
<html><body>
<h1 property="name" id="wb-cont">Analysis of residential properties and homeowners in high flood hazard areas</h1>
<section class="block block-ndm-plugins clearfix block-ndm-conttype"><span class="ndm-product-title">Articles and reports: </span><span>46-28-0001202600100004</span></section>
<section class="block block-ndm-plugins clearfix block-ndm-product-block"><span class="ndm-product-title">Description: </span>This study presents an analysis of residential properties.</section>
<table>
<thead><tr><th>Format</th><th>Release date</th><th>More information</th></tr></thead>
<tbody>
<tr class="odd"><td><a href="https://www150.statcan.gc.ca/n1/pub/46-28-0001/2026001/article/00004-eng.htm">HTML</a></td><td>September 3, 2026</td><td></td></tr>
<tr class="even"><td><a href="https://www150.statcan.gc.ca/n1/pub/46-28-0001/2026001/article/00004-eng.pdf">PDF</a></td><td>September 3, 2026</td><td></td></tr>
</tbody>
</table>
</body></html>
"""


async def test_get_document_formats_parses_title_description_and_links(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/46280001202600100004",
        html=_DOCUMENT_FORMATS_HTML,
    )
    result = await client.get_document_formats("46280001202600100004")
    assert (
        result.title
        == "Analysis of residential properties and homeowners in high flood hazard areas"
    )
    assert result.catalogue_number == "46-28-0001202600100004"
    assert result.category == "Articles and reports"
    assert result.description == "This study presents an analysis of residential properties."
    assert len(result.formats) == 2
    assert result.formats[0].format == "HTML"
    assert result.formats[1].format == "PDF"
    assert result.formats[1].url.endswith(".pdf")
    assert result.formats[1].release_date == "September 3, 2026"


async def test_get_document_formats_falls_back_to_stripped_number_on_404(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/46-28-0001202600100004",
        status_code=404,
    )
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/46280001202600100004",
        html=_DOCUMENT_FORMATS_HTML,
    )
    result = await client.get_document_formats("46-28-0001202600100004")
    assert len(result.formats) == 2


async def test_get_document_formats_not_found_raises(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/00000000",
        status_code=404,
    )
    with pytest.raises(NotFound):
        await client.get_document_formats("00000000")


async def test_get_document_formats_empty_catalogue_number_raises():
    with pytest.raises(InvalidInput):
        await client.get_document_formats("")


async def test_get_document_formats_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.get_document_formats("16-511-X", lang="de")


_SERIES_EDITIONS_HTML = """
<html><body>
<h1 property="name" id="wb-cont">Clean technologies and the Survey of Environmental Goods and Services</h1>
<section class="block block-ndm-plugins clearfix block-ndm-conttype"><span class="ndm-product-title">Surveys and statistical programs – Documentation: </span><span>16-511-X</span></section>
<table>
<thead><tr><th>Titles</th><th>Release date</th><th>More Information</th></tr></thead>
<tbody>
<tr class="odd"><td><a href="https://www150.statcan.gc.ca/n1/pub/16-511-x/16-511-x2026001-eng.htm" title="...2024 edition">2024 edition</a></td><td>2026-08-19</td><td></td></tr>
</tbody>
</table>
</body></html>
"""


async def test_get_document_formats_series_level_returns_editions_not_formats(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/16-511-X",
        html=_SERIES_EDITIONS_HTML,
    )
    result = await client.get_document_formats("16-511-X")
    assert result.formats == []
    assert len(result.editions) == 1
    assert result.editions[0].title == "...2024 edition"
    assert result.editions[0].url.endswith("16-511-x2026001-eng.htm")


async def test_get_document_formats_provenance_url_is_the_page_not_a_row_link(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/n1/en/catalogue/46280001202600100004",
        html=_DOCUMENT_FORMATS_HTML,
    )
    result = await client.get_document_formats("46280001202600100004")
    assert result.provenance.url == (
        "https://www150.statcan.gc.ca/n1/en/catalogue/46280001202600100004"
    )


# What the view renders when its session cookie is missing or expired:
# the keyword is silently dropped (empty search box) and every document
# in the catalogue comes back -- confirmed live 2026-09-22.
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
