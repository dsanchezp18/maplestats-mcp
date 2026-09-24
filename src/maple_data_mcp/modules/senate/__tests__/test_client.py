"""Tests for modules/senate/client.py, on markup trimmed from live pages (2026-09-24)."""

from __future__ import annotations

from datetime import date

import pytest

from maple_data_mcp.modules.senate import client
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_LIST = """
<a href="/en/in-the-chamber/votes/44-1">44-1</a>
<a href="/en/in-the-chamber/votes/45-1">45-1</a>
<table class="sc-table table" id="votes-table"><tbody>
<tr>
 <td class="vote-centered" data-order="2025-06-04 14:00:00 1"><a href="/j">2025-06-04</a></td>
 <td><a class="vote-web-title-link" href="/en/in-the-chamber/votes/details/665744/45-1">
   Government Motion no. 5 &#x2013; Sessional orders</a><br />
   Yeas: 68 <text>|</text> Nays: 5 <text>|</text> Abstentions: 3 <text>|</text> Total: 76</td>
 <td class="vote-centered" data-order="999999999999999"> </td>
 <td class="vote-centered"> Adopted </td>
</tr>
<tr>
 <td class="vote-centered"><a href="/j">2025-06-25</a></td>
 <td><a class="vote-web-title-link" href="/en/in-the-chamber/votes/details/667781/45-1">
   Appropriation Act No. 1, 2025-26 &#x2013; C-6 &#x2013; Second Reading</a><br />
   Yeas: 66 <text>|</text> Nays: 13 <text>|</text> Abstentions: 0 <text>|</text> Total: 79</td>
 <td class="vote-centered"><a href="http://www.parl.ca/LEGISInfo">C-6</a></td>
 <td class="vote-centered"> Adopted </td>
</tr>
</tbody></table>
"""

_DETAIL = """
<span class="sc-vote-details-box-date">Tuesday, October 21, 2025 - 45<sup>th</sup> Parliament</span>
<div class="sc-vote-details-box-title">An Act &#x2013; S-205 &#x2013; Second Reading</div>
<div class="sc-vote-details-box-related"><a>Related Bill: S-205</a></div>
<table class="table sc-table" id="sc-vote-details-table"><tbody>
<tr><td><a href="/s/1">Ringuette, Pierrette</a></td><td>ISG</td><td>New Brunswick</td>
 <td data-order="aaa"><i></i></td><td data-order="zzz"></td><td data-order="zzz"></td></tr>
<tr><td><a href="/s/2">Downe, Percy E.</a></td><td>CSG</td><td>Prince Edward Island</td>
 <td data-order="zzz"></td><td data-order="aaa"><i></i></td><td data-order="zzz"></td></tr>
<tr><td><a href="/s/3">Absent, Senator</a></td><td>PSG</td><td>Ontario</td>
 <td data-order="zzz"></td><td data-order="zzz"></td><td data-order="zzz"></td></tr>
</tbody></table>
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_list_votes_parses_totals_bill_and_current_session(httpx_mock):
    httpx_mock.add_response(url="https://sencanada.ca/en/in-the-chamber/votes/", text=_LIST)
    result = await client.list_votes()
    assert result.session == "45-1"
    assert result.sessions_available == ["44-1", "45-1"]
    newest = result.votes[0]
    assert (newest.vote_id, newest.date, newest.bill) == (667781, date(2025, 6, 25), "C-6")
    assert (newest.yeas, newest.nays, newest.abstentions) == (66, 13, 0)
    assert result.votes[1].bill is None and result.votes[1].result == "Adopted"


async def test_list_votes_filters_by_bill_and_keyword(httpx_mock):
    httpx_mock.add_response(url="https://sencanada.ca/en/in-the-chamber/votes/45-1", text=_LIST)
    assert [v.vote_id for v in (await client.list_votes(session="45-1", bill="c-6")).votes] == [
        667781
    ]
    result = await client.list_votes(session="45-1", keyword="sessional")
    assert [v.vote_id for v in result.votes] == [665744]


async def test_get_vote_reads_marked_column(httpx_mock):
    httpx_mock.add_response(
        url="https://sencanada.ca/en/in-the-chamber/votes/details/674459/45-1", text=_DETAIL
    )
    vote = await client.get_vote(674459, "45-1")
    assert [b.vote for b in vote.ballots] == ["Yea", "Nay", ""]
    assert (vote.yeas, vote.nays, vote.abstentions, vote.bill) == (1, 1, 0, "S-205")
    assert vote.date_text == "Tuesday, October 21, 2025 - 45th Parliament"


async def test_layout_change_and_bad_input(httpx_mock):
    httpx_mock.add_response(text="<html>maintenance</html>")
    with pytest.raises(UpstreamError):
        await client.list_votes()
    httpx_mock.add_response(text="<html>no table</html>")
    with pytest.raises(NotFound):
        await client.get_vote(1, "45-1")
    with pytest.raises(InvalidInput):
        await client.get_vote(1, "45")
