"""Tests for modules/openparliament/client.py, shaped on live responses (2026-09-24)."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.openparliament import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_NO_MORE = {"offset": 0, "limit": 500, "next_url": None, "previous_url": None}


def _vote(number: int, bill: str | None = "/bills/45-1/C-266/") -> dict:
    return {
        "bill_url": bill,
        "session": "45-1",
        "number": number,
        "date": "2026-09-23",
        "description": {"en": "2nd reading of Bill C-266", "fr": "2e lecture du projet C-266"},
        "result": "Passed",
        "yea_total": 295,
        "nay_total": 21,
        "paired_total": 14,
        "url": f"/votes/45-1/{number}/",
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_search_bills_defaults_to_current_session_and_filters_locally(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/votes/?limit=1",
        json={"objects": [_vote(174)], "pagination": _NO_MORE},
    )
    bills = [
        {
            "session": "45-1",
            "introduced": "2026-01-28",
            "name": {"en": "An Act to amend the Income Tax Act", "fr": "Loi modifiant la Loi"},
            "number": "C-19",
            "url": "/bills/45-1/C-19/",
        },
        {
            "session": "45-1",
            "introduced": "2025-06-03",
            "name": {"en": "Strong borders", "fr": "Frontières"},
            "number": "C-2",
            "url": "/bills/45-1/C-2/",
        },
    ]
    httpx_mock.add_response(json={"objects": bills, "pagination": _NO_MORE})
    result = await client.search_bills(keyword="income tax")
    assert [b.number for b in result.bills] == ["C-19"]
    assert result.bills[0].url == "https://openparliament.ca/bills/45-1/C-19/"
    query = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert query["session"] == ["45-1"] and query["limit"] == ["500"]
    assert httpx_mock.get_requests()[-1].headers["API-Version"] == "v1"


async def test_bill_list_follows_pagination(httpx_mock):
    row = {"session": "44-1", "name": {"en": "x"}, "number": "C-1", "url": "/bills/44-1/C-1/"}
    httpx_mock.add_response(
        json={"objects": [row], "pagination": {"next_url": "/bills/?offset=500"}}
    )
    httpx_mock.add_response(json={"objects": [row], "pagination": _NO_MORE})
    result = await client.search_bills(session="44-1")
    assert result.total_matches == 2
    offsets = [parse_qs(urlparse(str(r.url)).query)["offset"] for r in httpx_mock.get_requests()]
    assert offsets == [["0"], ["1"]]


async def test_get_bill_includes_votes_and_slugs(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/bills/45-1/C-266/",
        json={
            "session": "45-1",
            "introduced": "2025-06-03",
            "name": {"en": "Skilled trades", "fr": "Métiers"},
            "number": "C-266",
            "short_title": {"en": "", "fr": ""},
            "status": {"en": "Second reading (House)"},
            "law": None,
            "sponsor_politician_url": "/politicians/jane-doe/",
            "private_member_bill": True,
            "url": "/bills/45-1/C-266/",
        },
    )
    httpx_mock.add_response(json={"objects": [_vote(174)], "pagination": _NO_MORE})
    bill = await client.get_bill("45-1", "c-266", lang="fr")
    assert bill.name == "Métiers" and bill.short_title is None
    assert bill.status == "Second reading (House)"  # falls back to English
    assert bill.sponsor == "jane-doe"
    assert bill.votes[0].bill == "C-266" and bill.votes[0].description.startswith("2e")


async def test_unknown_object_is_not_found_and_html_is_upstream_error(httpx_mock):
    httpx_mock.add_response(status_code=404, text="<!doctype html><title>No go</title>")
    with pytest.raises(NotFound):
        await client.get_politician("nobody-here")
    httpx_mock.add_response(text="<!doctype html>")
    with pytest.raises(UpstreamError):
        await client.get_vote("45-1", 1)


async def test_get_vote_with_ballots(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/votes/45-1/174/",
        json={
            **_vote(174),
            "party_votes": [
                {"vote": "No", "disagreement": 0.0, "party": {"short_name": {"en": "Bloc"}}}
            ],
        },
    )
    httpx_mock.add_response(
        json={
            "objects": [{"politician_url": "/politicians/sima-acan/", "ballot": "Yes"}],
            "pagination": _NO_MORE,
        }
    )
    vote = await client.get_vote("45-1", 174, include_ballots=True)
    assert vote.party_votes[0].party == "Bloc" and vote.party_votes[0].vote == "No"
    assert vote.ballots[0].politician == "sima-acan"


async def test_search_politicians_filters_roster(httpx_mock):
    httpx_mock.add_response(
        json={
            "objects": [
                {
                    "name": "Mark Carney",
                    "url": "/politicians/mark-carney/",
                    "current_party": {"short_name": {"en": "Liberal"}},
                    "current_riding": {"province": "ON", "name": {"en": "Nepean"}},
                },
                {"name": "Ziad Aboultaif", "url": "/politicians/ziad-aboultaif/"},
            ],
            "pagination": _NO_MORE,
        }
    )
    result = await client.search_politicians(name="carney", province="on")
    assert [(p.slug, p.party, p.current) for p in result.politicians] == [
        ("mark-carney", "Liberal", True)
    ]


async def test_speeches_strip_html_and_build_debate_path(httpx_mock):
    httpx_mock.add_response(
        json={
            "objects": [
                {
                    "time": "2026-09-23 14:00:00",
                    "attribution": {"en": "The Speaker"},
                    "content": {"en": "<p>Hello &amp; <a href='/x/'>welcome</a>.</p><p>Bye</p>"},
                    "url": "/debates/2026/9/23/the-speaker-1/",
                    "politician_url": None,
                    "procedural": False,
                    "document_url": "/debates/2026/9/23/",
                }
            ],
            "pagination": {"next_url": "/speeches/?offset=1"},
        }
    )
    result = await client.search_speeches(debate_date="2026-09-03")
    assert result.speeches[0].text == "Hello & welcome.\nBye"
    assert result.has_more
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query["document"] == ["/debates/2026/9/3/"]


_SEARCH = """
<div class="columns small-12 medium-4 result_summary">Results <strong>1</strong>-<strong>15</strong>
 of <strong>3,614</strong></div>
<div class="row result" data-url="/debates/2026/6/16/jenny-kwan-1/">
  <div class="search-main-col"><p><a href="/debates/2026/6/16/jenny-kwan-1/#hl"
   class="statement_topic">Budget Bill</a> &nbsp;A family facing eviction is in a
   <em>housing crisis</em>.</p></div>
  <div class="search-context-col">
    <p>June 16th, 2026<span class="br slash"></span>House debate</p>
    <p><a href="/politicians/jenny-kwan/" class="pol_name">Jenny Kwan</a>
     <span class="tag partytag_ndp">NDP</span></p>
  </div>
</div>
"""


async def test_search_hansard_parses_hits(httpx_mock):
    httpx_mock.add_response(text=_SEARCH)
    result = await client.search_hansard('"housing crisis"', sort="newest")
    hit = result.hits[0]
    assert (hit.date, hit.document_type, hit.topic) == (
        date(2026, 6, 16),
        "House debate",
        "Budget Bill",
    )
    assert hit.excerpt == "A family facing eviction is in a housing crisis."
    assert (hit.politician, hit.party) == ("jenny-kwan", "NDP")
    assert result.total_matches == 3614 and result.has_more
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query["sort"] == ["date desc"]


async def test_search_hansard_no_results_and_layout_change(httpx_mock):
    httpx_mock.add_response(text="<p>No results found</p>")
    result = await client.search_hansard("zzqq")
    assert (result.hits, result.total_matches, result.has_more) == ([], 0, False)
    httpx_mock.add_response(text="<html>captcha</html>")
    with pytest.raises(UpstreamError):
        await client.search_hansard("other")


async def test_validation():
    with pytest.raises(InvalidInput):
        await client.get_bill("45", "C-2")
    with pytest.raises(InvalidInput):
        await client.get_bill("45-1", "X-2")
    with pytest.raises(InvalidInput):
        await client.search_votes(bill="C-2")
    with pytest.raises(InvalidInput):
        await client.search_speeches()
    with pytest.raises(InvalidInput):
        await client.get_politician("bad slug!")
    with pytest.raises(InvalidInput):
        await client.search_votes(date_from="Sept 1")
    assert client._date("2026-09-23") == date(2026, 9, 23)
