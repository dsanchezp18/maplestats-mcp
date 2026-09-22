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

from maple_data_mcp.modules.elections_financial_returns import client, constants
from maple_data_mcp.modules.elections_financial_returns.schemas import FilterOption
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


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
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", html=_CANDIDATES_HTML)
    result = await client.search_candidates("62")
    assert result.returned_count == 1
    assert result.total_found == 19
    assert result.provenance.coverage is not None
    assert "1 of 19" in result.provenance.coverage


async def test_search_candidates_only_warms_up_once(httpx_mock):
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
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")  # warm-up
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
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", status_code=302, headers={"location": detail_location}
    )
    httpx_mock.add_response(url=detail_url, html="<html></html>")
    httpx_mock.add_response(url=download_url, text=_EXPENSES_JSON)

    result = await client.get_financial_return_part("56932", "3a", election_id="62")
    assert set(result.sections) == {"GROUP_DATA", "DETAIL_DATA", "TOTAL_DATA"}
    assert result.sections["DETAIL_DATA"][0]["Supplier"] == "Bank of Montreal"


async def test_get_financial_return_part_invalid_part_raises():
    with pytest.raises(InvalidInput):
        await client.get_financial_return_part("56932", "not-a-part", election_id="62")


async def test_get_financial_return_part_no_redirect_after_select_raises(httpx_mock):
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(url=_SEARCH_URL, method="POST", status_code=200, html="<html></html>")
    with pytest.raises(UpstreamError):
        await client.get_financial_return_part("999999", "1", election_id="62")


async def test_get_financial_return_part_expired_session_raises_not_found(httpx_mock):
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
    httpx_mock.add_response(url=_SEARCH_URL, html="<html></html>")
    httpx_mock.add_response(
        url=_SEARCH_URL, method="POST", status_code=302, headers={"location": detail_location}
    )
    httpx_mock.add_response(url=detail_url, html="<html></html>")
    httpx_mock.add_response(
        url=download_url,
        status_code=302,
        headers={"location": "/WPAPPS/WPF/EN/CC/Index?act=C76&selectedEvent=62"},
    )
    with pytest.raises(NotFound):
        await client.get_financial_return_part("56932", "1", election_id="62")
