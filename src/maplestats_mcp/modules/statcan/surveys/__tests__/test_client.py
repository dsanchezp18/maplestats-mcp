from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared import retrying
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


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


async def test_get_survey_metadata_not_found_page_answering_503_raises_at_once(httpx_mock):
    # Since 2026-10-29 StatCan's 404 page answers 503: still NotFound, and with
    # no retries (one request each to IMDB and the error page).
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=999999"
    error_page_url = "https://www.statcan.gc.ca/error-erreur/stc_srvmsg404.html"
    httpx_mock.add_response(url=url, status_code=302, headers={"Location": error_page_url})
    httpx_mock.add_response(url=error_page_url, status_code=503)
    with pytest.raises(NotFound):
        await client.get_survey_metadata(999999)
    assert len(httpx_mock.get_requests()) == 2


async def test_search_surveys_404_says_the_directory_is_unavailable(httpx_mock):
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, status_code=404)
    with pytest.raises(UpstreamUnavailable, match="survey directory .* is unavailable"):
        await client.search_surveys()


async def test_get_survey_metadata_genuine_500_becomes_upstream_error(httpx_mock):
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=5108"
    httpx_mock.add_response(url=url, status_code=500)
    with pytest.raises(UpstreamError):
        await client.get_survey_metadata(5108)


async def test_get_survey_metadata_failure_is_not_cached(httpx_mock, monkeypatch):
    """A 503 that outlasts the retries must not poison the cache for 24 h."""

    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retrying.asyncio, "sleep", no_sleep)
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=5108"
    # One answer to see whether the 503 is the unknown-survey page, then the retries.
    for _ in range(retrying.RETRY_ATTEMPTS + 1):
        httpx_mock.add_response(url=url, status_code=503)
    with pytest.raises(UpstreamError, match="503"):
        await client.get_survey_metadata(5108)
    httpx_mock.add_response(url=url, html=_METADATA_HTML)
    result = await client.get_survey_metadata(5108)
    assert result.name == "Aboriginal Children's Survey (ACS)"
    assert result.provenance.cached is False


async def test_get_survey_metadata_success_is_still_cached(httpx_mock):
    url = f"{constants.IMDB_BASE_URL_EN}?Function=getSurvey&SDDS=5108"
    httpx_mock.add_response(url=url, html=_METADATA_HTML)
    first = await client.get_survey_metadata(5108)
    second = await client.get_survey_metadata(5108)  # no second request is mocked
    assert (first.provenance.cached, second.provenance.cached) == (False, True)


async def test_get_survey_metadata_invalid_lang_raises():
    with pytest.raises(InvalidInput):
        await client.get_survey_metadata(5108, lang="de")


async def test_search_surveys_expired_session_rewarms_and_retries(httpx_mock):
    client._warmed_list_langs.add("en")  # warmed earlier in the process
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html="<html></html>")  # expired
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html="<html></html>")  # re-warm
    httpx_mock.add_response(url=constants.SURVEY_LIST_URL_EN, html=_LIST_HTML)
    result = await client.search_surveys()
    assert result.returned_count > 0


async def test_search_surveys_empty_directory_after_rewarm_raises(httpx_mock):
    httpx_mock.add_response(
        url=constants.SURVEY_LIST_URL_EN, html="<html></html>", is_reusable=True
    )
    with pytest.raises(UpstreamError):
        await client.search_surveys()
    assert "en" not in client._warmed_list_langs
