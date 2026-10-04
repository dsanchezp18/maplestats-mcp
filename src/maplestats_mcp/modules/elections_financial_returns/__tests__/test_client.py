"""Tests for elections_financial_returns/client.py, shaped around the real
Political Financing portal quirks confirmed live this session (see
client.py's module docstring): the warm-up-before-POST session
requirement, the double-JSON-encoded RefreshEventList body, the
select-candidate POST's 302-with-queryId redirect, the one-time
DetailedReport GET requirement before Download works, and the
per-part-varying JSON section keys (DETAIL_DATA vs GROUP_DATA+
DETAIL_DATA+TOTAL_DATA vs SUMMARY_DATA).
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.elections_financial_returns import client, constants
from maplestats_mcp.modules.elections_financial_returns.schemas import FilterOption
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)


@pytest.fixture(autouse=True)
def _reset_state():
    cache_module._caches.clear()
    client._warmed.clear()
    yield


_SEARCH_URL = client._search_url("C76", "62", "8", "1")

_EVENTS_BODY = (
    '"[{\\"Disabled\\":false,\\"Group\\":null,\\"Selected\\":false,\\"Text\\":\\"Select\\",'
    '\\"Value\\":\\"-1\\"},{\\"Disabled\\":false,\\"Group\\":{\\"Disabled\\":false,\\"Name\\":'
    '\\"General Election\\"},\\"Selected\\":false,\\"Text\\":\\"45th general election\\",'
    '\\"Value\\":\\"62\\"}]"'
)

_CANDIDATES_HTML = """
<html><body>
<select id="PartyList" name="SelectedPartyIds">
<option value="-1">All political parties</option>
<option value="28">Conservative Party of Canada</option>
</select>
<select id="ProvinceList" name="SelectedProvinceId">
<option value="-1">All provinces and territories</option>
<option value="11">Prince Edward Island</option>
</select>
<label for="SelectedClientIds">Candidates Found</label>
<span id="foundcnt">19</span>
<select id="SelectedClientIds" name="SelectedClientIds" multiple="multiple">
<option value="56932">Aylward, James / Conservative Party of Canada / Cardigan</option>
<option value="58701">Baughan, Hilda / People&#39;s Party of Canada / Malpeque</option>
</select>
</body></html>
"""

_EVENTS_URL = f"{constants.HOME_URL}/RefreshEventList?selectedAct=CC_C76&selectedEntityCode=1"


def _mock_events(httpx_mock) -> None:
    httpx_mock.add_response(
        url=_EVENTS_URL,
        text=_EVENTS_BODY,
        headers={"content-type": "application/json"},
        is_reusable=True,
    )


def _mock_pairing_search(httpx_mock) -> None:
    """The warm-up GET and the unfiltered search that checks the candidate's election."""
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)


_DECLARATION_JSON = (
    '{"EXPORT_HEADER":[{"DATE":"Sep 21, 2026","TITLE":"Part 1 - Declaration",'
    '"RETURN_STATUS":"Data_as_submitted","ACTIVITY":"45th general election"}],'
    '"DETAIL_DATA":[{"Client_id":"56932","Candidate_last_name":"Aylward",'
    '"Candidate_first_name":"James","Political_Affiliation":"Conservative Party of Canada",'
    '"Electoral_district":"Cardigan","Type_of_return":"C"}]}'
)

_EXPENSES_JSON = (
    '{"EXPORT_HEADER":[{"DATE":"Sep 21, 2026","TITLE":"Part 3a",'
    '"RETURN_STATUS":"Data_as_submitted","ACTIVITY":"45th general election"}],'
    '"GROUP_DATA":[{"Client_id":"56932","Electoral_district":"Cardigan"}],'
    '"DETAIL_DATA":[{"Client_id":"56932","No":"1","Supplier":"Bank of Montreal","Expense_amount":"22.5"}],'
    '"TOTAL_DATA":[]}'
)


async def test_list_elections_decodes_double_json_body(httpx_mock):
    url = f"{constants.HOME_URL}/RefreshEventList?selectedAct=CC_C76&selectedEntityCode=1"
    httpx_mock.add_response(
        url=url, text=_EVENTS_BODY, headers={"content-type": "application/json"}
    )
    result = await client.list_elections(act="after_2019")
    assert len(result.elections) == 1
    assert result.elections[0].id == "62"
    assert result.elections[0].label == "45th general election"
    assert result.elections[0].group == "General Election"


async def test_list_elections_invalid_act_raises():
    with pytest.raises(InvalidInput):
        await client.list_elections(act="not-a-real-period")


async def test_search_candidates_warms_up_then_posts(httpx_mock):
    _mock_events(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")  # warm-up
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    result = await client.search_candidates("62", province_id="11")
    assert result.total_found == 19
    assert result.returned_count == 2
    first = result.candidates[0]
    assert first.client_id == "56932"
    assert first.last_name == "Aylward"
    assert first.first_name == "James"
    assert first.party == "Conservative Party of Canada"
    assert first.electoral_district == "Cardigan"
    assert result.available_parties == [FilterOption(id="28", label="Conservative Party of Canada")]


async def test_search_candidates_truncates_and_sets_coverage(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "CANDIDATE_SEARCH_MAX", 1)
    _mock_events(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    result = await client.search_candidates("62")
    assert result.returned_count == 1
    assert result.total_found == 19
    assert result.has_more
    assert result.provenance.coverage is not None
    assert "offset=1" in result.provenance.coverage
    second = await client.search_candidates("62", offset=1)
    assert [c.client_id for c in second.candidates] == ["58701"]
    assert not second.has_more


async def test_search_candidates_unknown_election_is_not_found(httpx_mock):
    _mock_events(httpx_mock)
    with pytest.raises(NotFound, match="9999"):
        await client.search_candidates("9999", last_name="Smith")


async def test_search_candidates_only_warms_up_once(httpx_mock):
    _mock_events(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    await client.search_candidates("62", last_name="a")
    await client.search_candidates("62", last_name="b")
    warmup_gets = [
        r for r in httpx_mock.get_requests() if r.method == "GET" and str(r.url) == _SEARCH_URL
    ]
    assert len(warmup_gets) == 1


async def test_search_candidates_invalid_election_id_raises():
    with pytest.raises(InvalidInput):
        await client.search_candidates("  ")


async def test_search_candidates_invalid_return_status_raises():
    with pytest.raises(InvalidInput):
        await client.search_candidates("62", return_status="not-a-status")


async def test_get_financial_return_part_full_flow(httpx_mock):
    detail_location = (
        "/WPAPPS/WPF/EN/CC/DetailedReport?act=C76&selectedEvent=62&returnStatus=1"
        "&selectedReportType=8&reportOption=2&queryId=04bddb9446c9457bb1a00d34286f2df6"
        "&selectedPart=1"
    )
    detail_url = f"https://www.elections.ca{detail_location}"
    download_url = (
        f"{constants.BASE_URL}/Download?act=C76&selectedEvent=62&returnStatus=1"
        "&reportOption=2&queryId=04bddb9446c9457bb1a00d34286f2df6&selectedClientId=56932"
        "&selectedPart=1&currentReturnPage=0&totalReturnPages=0&downloadFormat=3"
        "&current200Page=0&total200Pages=0"
    )
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", status_code=302, headers={"location": detail_location}
    )
    httpx_mock.add_response(url=detail_url, html="<html></html>")
    httpx_mock.add_response(url=download_url, text=_DECLARATION_JSON)

    result = await client.get_financial_return_part("56932", "1", election_id="62")
    assert result.part_code == "1"
    assert result.part_label == constants.PART_LABELS["1"]
    assert result.export_header["TITLE"] == "Part 1 - Declaration"
    assert result.sections["DETAIL_DATA"][0]["Candidate_last_name"] == "Aylward"
    assert "GROUP_DATA" not in result.sections


async def test_get_financial_return_part_varies_sections_by_part(httpx_mock):
    detail_location = (
        "/WPAPPS/WPF/EN/CC/DetailedReport?act=C76&selectedEvent=62&returnStatus=1"
        "&selectedReportType=8&reportOption=2&queryId=abc123&selectedPart=3A"
    )
    detail_url = f"https://www.elections.ca{detail_location}"
    download_url = (
        f"{constants.BASE_URL}/Download?act=C76&selectedEvent=62&returnStatus=1"
        "&reportOption=2&queryId=abc123&selectedClientId=56932"
        "&selectedPart=3A&currentReturnPage=0&totalReturnPages=0&downloadFormat=3"
        "&current200Page=0&total200Pages=0"
    )
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", status_code=302, headers={"location": detail_location}
    )
    httpx_mock.add_response(url=detail_url, html="<html></html>")
    # Live bytes are UTF-8 with no charset in the Content-Type (2026-10-03).
    httpx_mock.add_response(
        url=download_url,
        content=_EXPENSES_JSON.replace(
            "Bank of Montreal", "Association libérale provinciale Orléans"
        ).encode("utf-8"),
        headers={"content-type": "application/json"},
    )

    result = await client.get_financial_return_part("56932", "3a", election_id="62")
    assert set(result.sections) == {"GROUP_DATA", "DETAIL_DATA", "TOTAL_DATA"}
    supplier = result.sections["DETAIL_DATA"][0]["Supplier"]
    assert supplier == "Association libérale provinciale Orléans"


async def test_get_financial_return_part_invalid_part_raises():
    with pytest.raises(InvalidInput):
        await client.get_financial_return_part("56932", "not-a-part", election_id="62")


async def test_get_financial_return_part_no_redirect_after_select_raises(httpx_mock):
    # After the pairing search: a non-redirecting POST, a forced re-warm, and
    # a second non-redirecting POST before giving up.
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", status_code=200, html="<html></html>", is_reusable=True
    )
    with pytest.raises(UpstreamError):
        await client.get_financial_return_part("56932", "1", election_id="62")
    assert _SEARCH_URL not in client._warmed


async def test_get_financial_return_part_rejects_candidate_from_another_election(httpx_mock):
    # Live 2026-10-03: client 56572 asked under election 53 came back with his
    # 2025 return labelled as the 2021 election; he is not in 53's candidates.
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    with pytest.raises(NotFound, match="did not run"):
        await client.get_financial_return_part("56572", "1", election_id="62")


async def test_get_financial_return_part_unknown_election_is_not_found(httpx_mock):
    _mock_events(httpx_mock)
    with pytest.raises(NotFound, match="no election"):
        await client.get_financial_return_part("56932", "1", election_id="9999")


async def test_search_candidates_expired_session_rewarms_and_retries(httpx_mock):
    _mock_events(httpx_mock)
    client._warmed.add(_SEARCH_URL)  # warmed earlier; server-side session since expired
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html="<html><form></form></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="GET", html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    result = await client.search_candidates("62")
    assert result.total_found == 19


async def test_search_candidates_empty_form_is_an_error_not_zero_results(httpx_mock):
    _mock_events(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, method="GET", html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", html="<html><form></form></html>", is_reusable=True
    )
    with pytest.raises(UpstreamError):
        await client.search_candidates("62")


async def test_search_candidates_genuine_zero_matches_is_not_an_error(httpx_mock):
    _mock_events(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, method="GET", html="<html></html>")
    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        html='<html><span id="foundcnt">0</span><select id="SelectedClientIds"></select></html>',
    )
    result = await client.search_candidates("62", last_name="Zzqxqzz")
    assert result.total_found == 0


async def test_get_financial_return_part_lost_session_rewarms_then_raises(httpx_mock):
    detail_location = (
        "/WPAPPS/WPF/EN/CC/DetailedReport?act=C76&selectedEvent=62&returnStatus=1"
        "&selectedReportType=8&reportOption=2&queryId=deadbeef12&selectedPart=1"
    )
    detail_url = f"https://www.elections.ca{detail_location}"
    download_url = (
        f"{constants.BASE_URL}/Download?act=C76&selectedEvent=62&returnStatus=1"
        "&reportOption=2&queryId=deadbeef12&selectedClientId=56932"
        "&selectedPart=1&currentReturnPage=0&totalReturnPages=0&downloadFormat=3"
        "&current200Page=0&total200Pages=0"
    )
    # A lost session redirects the Download back to the search form: the
    # client re-warms, selects again, and only then gives up (AGENTS.md).
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        status_code=302,
        headers={"location": detail_location},
        is_reusable=True,
    )
    httpx_mock.add_response(url=detail_url, html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=download_url,
        status_code=302,
        headers={"location": "/WPAPPS/WPF/EN/CC/Index?act=C76&selectedEvent=62"},
        is_reusable=True,
    )
    with pytest.raises(UpstreamUnavailable):
        await client.get_financial_return_part("56932", "1", election_id="62")
    downloads = [r for r in httpx_mock.get_requests() if "/Download?" in str(r.url)]
    assert len(downloads) == 2


async def test_get_financial_return_part_lost_session_recovers(httpx_mock):
    detail_location = (
        "/WPAPPS/WPF/EN/CC/DetailedReport?act=C76&selectedEvent=62&returnStatus=1"
        "&selectedReportType=8&reportOption=2&queryId=feed01&selectedPart=1"
    )
    download_url = (
        f"{constants.BASE_URL}/Download?act=C76&selectedEvent=62&returnStatus=1"
        "&reportOption=2&queryId=feed01&selectedClientId=56932"
        "&selectedPart=1&currentReturnPage=0&totalReturnPages=0&downloadFormat=3"
        "&current200Page=0&total200Pages=0"
    )
    _mock_events(httpx_mock)
    _mock_pairing_search(httpx_mock)
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>", is_reusable=True)
    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        status_code=302,
        headers={"location": detail_location},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=f"https://www.elections.ca{detail_location}", html="<html></html>", is_reusable=True
    )
    httpx_mock.add_response(url=download_url, status_code=302, headers={"location": "/x"})
    httpx_mock.add_response(url=download_url, text=_DECLARATION_JSON)
    result = await client.get_financial_return_part("56932", "1", election_id="62")
    assert result.sections["DETAIL_DATA"][0]["Candidate_last_name"] == "Aylward"


async def test_french_download_header_key(httpx_mock):
    fr_search = client._search_url("C76", "62", "8", "1", "fr")
    fr_events = (
        "https://www.elections.ca/WPAPPS/WPF/FR/Home/RefreshEventList"
        "?selectedAct=CC_C76&selectedEntityCode=1"
    )
    detail_location = (
        "/WPAPPS/WPF/FR/CC/DetailedReport?act=C76&selectedEvent=62&returnStatus=1"
        "&selectedReportType=8&reportOption=2&queryId=abc&selectedPart=1"
    )
    download_url = (
        f"{constants.BASE_URLS['fr']}/Download?act=C76&selectedEvent=62&returnStatus=1"
        "&reportOption=2&queryId=abc&selectedClientId=56932"
        "&selectedPart=1&currentReturnPage=0&totalReturnPages=0&downloadFormat=3"
        "&current200Page=0&total200Pages=0"
    )
    httpx_mock.add_response(url=fr_events, text=_EVENTS_BODY)
    httpx_mock.add_response(url=fr_search, html="<html></html>")
    httpx_mock.add_response(url=fr_search, method="POST", html=_CANDIDATES_HTML)
    httpx_mock.add_response(
        url=fr_search, method="POST", status_code=302, headers={"location": detail_location}
    )
    httpx_mock.add_response(url=f"https://www.elections.ca{detail_location}", html="<html/>")
    # Key names from the live French download (2026-10-03).
    httpx_mock.add_response(
        url=download_url,
        content=(
            '{"RUBRIQUE_EXPORTER":[{"TITRE":"Partie 1 - Déclaration"}],'
            '"DONNÉES_DÉTAIL":[{"Nom_de_famille_du_candidat":"Aylward"}]}'
        ).encode(),
    )
    result = await client.get_financial_return_part("56932", "1", election_id="62", lang="fr")
    assert result.export_header == {"TITRE": "Partie 1 - Déclaration"}
    assert list(result.sections) == ["DONNÉES_DÉTAIL"]
    assert result.part_label == "Partie 1 – Déclaration"
    assert (result.provenance.limits or "").startswith("Requête (liée à la session\xa0;")
    assert (result.provenance.licence or "").startswith("Avis d'Élections Canada")


async def test_french_errors():
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: act doit être l'une"):
        await client.list_elections(act="not-a-real-period", lang="fr")
    with pytest.raises(InvalidInput, match="part doit être l'une des valeurs"):
        await client.get_financial_return_part("1", "9", election_id="62", lang="fr")
    with pytest.raises(InvalidInput, match="election_id ne doit pas être vide"):
        await client.search_candidates("  ", lang="fr")
    with pytest.raises(InvalidInput, match=r"^election_id must not be empty\.$"):
        await client.search_candidates("  ")
