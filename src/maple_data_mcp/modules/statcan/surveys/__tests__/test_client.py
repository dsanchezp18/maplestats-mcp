from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.surveys import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_state():
    cache_module._caches.clear()
    client._warmed_list_langs.clear()
    yield


_LIST_HTML = """
<html><body>
<h2 id="topic_a">A</h2>
<ul class="ndm-surveys-az">
<li><a href="/n1/en/surveys/3326">A One Day Snapshot in Canada's Correctional Facilities</a></li>
<li><a href="/n1/en/surveys/5108">Aboriginal Children's Survey</a></li>
</ul>
</body></html>
"""

_METADATA_HTML = """
<html><body>
<h1 id="wb-cont">Aboriginal Children's Survey (ACS)</h1>
<div class="row"><div class="col-md-3"><p><strong>Status:</strong></p></div><div class="col-md-9"><p>Inactive</p></div></div>
<div class="row"><div class="col-md-3"><p><strong>Frequency:</strong></p></div><div class="col-md-9"><p>One Time</p></div></div>
<div class="row"><div class="col-md-3"><p><strong>Record number:</strong></p></div><div class="col-md-9"><p>5108</p></div></div>
<h3 id="a1">Description</h3>
<p>The Aboriginal Children's Survey was designed to provide a picture of early development.</p>
<h4>Subjects</h4>
<ul>
<li>Child development and behaviour</li>
<li>Indigenous peoples</li>
</ul>
</body></html>
"""


async def test_search_surveys_parses_listing(httpx_mock):
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html=_LIST_HTML)
    result = await client.search_surveys()
    assert result.total_matched == 2
    assert result.surveys[1].survey_id == 5108
    assert result.surveys[1].name == "Aboriginal Children's Survey"


async def test_search_surveys_filters_by_query(httpx_mock):
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html="<html></html>")
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html=_LIST_HTML)
    result = await client.search_surveys("aboriginal")
    assert result.total_matched == 1
    assert result.surveys[0].survey_id == 5108


async def test_search_surveys_fr_uses_fr_url(httpx_mock):
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_FR, html="<html></html>")
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_FR, html=_LIST_HTML)
    await client.search_surveys(lang="fr")


async def test_search_surveys_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.search_surveys(lang="de")


async def test_search_surveys_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.search_surveys(limit=0)


async def test_get_survey_metadata_parses_fields(httpx_mock):
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=5108"
    httpx_mock.add_response(url=url, html=_METADATA_HTML)
    result = await client.get_survey_metadata(5108)
    assert result.name == "Aboriginal Children's Survey (ACS)"
    assert result.status == "Inactive"
    assert result.frequency == "One Time"
    assert result.description == (
        "The Aboriginal Children's Survey was designed to provide a picture of early development."
    )
    assert result.subjects == ["Child development and behaviour", "Indigenous peoples"]
    assert result.detail_url == url


async def test_get_survey_metadata_fr_uses_fr_script(httpx_mock):
    url = f"{constants.IMDB_BASE_URL_FR}?Function=getSurvey&SDDS=5108"
    httpx_mock.add_response(url=url, html=_METADATA_HTML)
    await client.get_survey_metadata(5108, lang="fr")


async def test_get_survey_metadata_not_found_raises(httpx_mock):
    # Confirmed live: an unknown SDDS number redirects through
    # StatCan's own dedicated 404 page, which itself answers HTTP 500
    # due to a broken redirect chain on their end (302 -> 301 -> 500).
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=999999"
    error_page_url = "https://www.statcan.gc.ca/error-erreur/stc_srvmsg404.html"
    httpx_mock.add_response(url=url, status_code=302, headers={"Location": error_page_url})
    httpx_mock.add_response(url=error_page_url, status_code=500)
    with pytest.raises(NotFound):
        await client.get_survey_metadata(999999)


async def test_get_survey_metadata_genuine_500_becomes_upstream_error(httpx_mock):
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=5108"
    httpx_mock.add_response(url=url, status_code=500)
    with pytest.raises(UpstreamError):
        await client.get_survey_metadata(5108)


async def test_get_survey_metadata_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.get_survey_metadata(5108, lang="de")
