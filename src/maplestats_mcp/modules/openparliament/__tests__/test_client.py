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


# --- Committees, shaped on live responses (2026-09-26) ---------------------

_HEALTH = {
    "name": {"en": "Health", "fr": "Santé"},
    "short_name": {"en": "Health", "fr": "Santé"},
    "slug": "health",
    "parent_url": None,
    "url": "/committees/health/",
}
_ETHICS = {
    "name": {
        "en": "Access to Information, Privacy and Ethics",
        "fr": "Accès à l'information, protection des renseignements personnels et éthique",
    },
    "short_name": {"en": "Information & Ethics", "fr": "Information et éthique"},
    "slug": "ethics",
    "parent_url": None,
    "url": "/committees/ethics/",
}


def _meeting_row(committee: str, number: int, **extra: object) -> dict:
    # List rows have no `session` key; only the detail endpoint adds it.
    return {
        "date": "2026-06-11",
        "number": number,
        "in_camera": False,
        "has_evidence": True,
        "committee_url": f"/committees/{committee}/",
        "url": f"/committees/{committee}/45-1/{number}/",
        **extra,
    }


def _speech_row(n: int, en: str, fr: str, politician: str | None = None) -> dict:
    return {
        "time": "2026-06-11 08:20:00",
        "attribution": {"en": en, "fr": fr},
        "content": {"en": f"<p data-HoCid='{n}'>English {n}</p>", "fr": f"<p>Français {n}</p>"},
        "url": f"/committees/finance/45-1/47/speaker-{n}/",
        "politician_url": f"/politicians/{politician}/" if politician else None,
        "politician_membership_url": None,
        "procedural": False,
        "source_id": str(n),
        "document_url": "/committees/finance/45-1/47/",
    }


async def test_list_committees_current_session_and_bilingual_keyword(httpx_mock):
    httpx_mock.add_response(json={"objects": [_ETHICS, _HEALTH], "pagination": _NO_MORE})
    result = await client.list_committees(keyword="SANTÉ", lang="fr")
    assert [(c.slug, c.name) for c in result.committees] == [("health", "Santé")]
    assert result.session is None and result.returned_count == 1
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert "session" not in query and query["limit"] == ["500"]


async def test_list_committee_keyword_ignores_accents_and_apostrophe_style(httpx_mock):
    # Francophones often type without accents, and with either apostrophe.
    httpx_mock.add_response(json={"objects": [_ETHICS, _HEALTH], "pagination": _NO_MORE})
    for keyword, slug in [
        ("sante", "health"),
        ("ETHIQUE", "ethics"),
        ("acces a l\u2019information", "ethics"),
        ("privacy", "ethics"),
    ]:
        result = await client.list_committees(keyword=keyword, lang="fr")
        assert [c.slug for c in result.committees] == [slug], keyword


async def test_list_committees_empty_session_is_not_found(httpx_mock):
    # Live, a pre-39-1 or unknown session answers 200 with an empty list.
    httpx_mock.add_response(json={"objects": [], "pagination": _NO_MORE})
    with pytest.raises(NotFound, match="39-1"):
        await client.list_committees(session="38-1")


async def test_get_committee_sessions_subcommittees_and_recent_meetings(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/ethics/",
        json={
            **_ETHICS,
            "sessions": [
                {
                    "session": "45-1",
                    "acronym": "ETHI",
                    "source_url": "https://www.ourcommons.ca/Committees/en/ETHI?parl=45&session=1",
                }
            ],
            "subcommittees": ["/committees/ethics-sap/"],
            "related": {"meetings_url": "/committees/meetings/?committee=ethics"},
        },
    )
    httpx_mock.add_response(
        json={
            "objects": [_meeting_row("ethics", 50, in_camera=True, has_evidence=False)],
            "pagination": {"next_url": "/committees/meetings/?committee=ethics&offset=10"},
        }
    )
    committee = await client.get_committee("/committees/Ethics/")
    assert committee.sessions[0].acronym == "ETHI"
    assert committee.subcommittees == ["ethics-sap"]
    meeting = committee.recent_meetings[0]
    assert (meeting.committee, meeting.session, meeting.number) == ("ethics", "45-1", 50)
    assert meeting.in_camera and not meeting.has_evidence
    query = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert query == {"committee": ["ethics"], "limit": ["10"]}


async def test_get_committee_tolerates_null_lists(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/health/",
        json={**_HEALTH, "sessions": None, "subcommittees": None},
    )
    httpx_mock.add_response(json={"objects": None, "pagination": _NO_MORE})
    committee = await client.get_committee("health")
    assert (committee.sessions, committee.subcommittees, committee.recent_meetings) == ([], [], [])


async def test_search_committee_meetings_maps_filters(httpx_mock):
    httpx_mock.add_response(
        json={
            "objects": [_meeting_row("finance", 47)],
            "pagination": {"next_url": "/committees/meetings/?offset=1"},
        }
    )
    result = await client.search_committee_meetings(
        committee="finance",
        session="45-1",
        date_from="2026-06-01",
        date_to="2026-06-30",
        in_camera=False,
        limit=1,
    )
    assert result.has_more and result.meetings[0].session == "45-1"
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query == {
        "committee": ["finance"],
        "session": ["45-1"],
        "date__gte": ["2026-06-01"],
        "date__lte": ["2026-06-30"],
        "in_camera": ["false"],
        "limit": ["1"],
    }


async def test_unknown_committee_meetings_is_not_found(httpx_mock):
    # Live, /committees/meetings/?committee=nosuch answers an empty list.
    httpx_mock.add_response(json={"objects": [], "pagination": _NO_MORE})
    httpx_mock.add_response(status_code=404, text="<!doctype html>")
    with pytest.raises(NotFound):
        await client.search_committee_meetings(committee="nosuch")


async def test_known_committee_with_no_matching_meetings_is_empty(httpx_mock):
    httpx_mock.add_response(json={"objects": [], "pagination": _NO_MORE})
    httpx_mock.add_response(json=_HEALTH)
    result = await client.search_committee_meetings(committee="health", date_to="2001-01-01")
    assert result.meetings == [] and not result.has_more


async def test_get_committee_meeting_witnesses_and_transcript_slice(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/finance/45-1/47/",
        json={
            **_meeting_row("finance", 47),
            "session": "45-1",
            "start_time": "08:15:00",
            "end_time": "10:30:00",
            "minutes_url": "https://www.ourcommons.ca/DocumentViewer/en/45-1/FINA/meeting-47/minutes",
            "notice_url": None,
            "webcast_url": None,
        },
    )
    speeches = [
        _speech_row(
            1,
            "The Chair (Hon. Karina Gould (Burlington, Lib.))",
            "La présidente (L'hon. Karina Gould (Burlington, Lib.))",
            politician="karina-gould",
        ),
        _speech_row(2, "The Clerk of the Committee (Nancy Vohl)", "La greffière (Nancy Vohl)"),
        _speech_row(
            3,
            "Paul Deegan (President and Chief Executive Officer, News Media Canada)",
            "Paul Deegan (président et chef de la direction, Médias d'Info Canada)",
        ),
        # Later turns give the bare name only.
        _speech_row(4, "Paul Deegan", "Paul Deegan"),
        _speech_row(5, "Some hon. members", "Des députés"),
        _speech_row(6, "Paul Deegan (News Media Canada)", "Paul Deegan (Médias d'Info Canada)"),
    ]
    httpx_mock.add_response(json={"objects": speeches, "pagination": _NO_MORE})
    meeting = await client.get_committee_meeting("finance", "45-1", 47, limit=2, offset=2)
    assert meeting.meeting.session == "45-1" and meeting.start_time == "08:15:00"
    assert [(w.name, w.role) for w in meeting.witnesses] == [
        ("Paul Deegan", "President and Chief Executive Officer, News Media Canada")
    ]
    assert meeting.total_speeches == 6 and meeting.has_more
    assert [s.text for s in meeting.speeches] == ["English 3", "English 4"]
    query = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert query["document"] == ["/committees/finance/45-1/47/"]

    fr = await client.get_committee_meeting("finance", "45-1", 47, limit=0, lang="fr")
    assert fr.speeches == [] and fr.has_more  # served from cache
    assert fr.witnesses[0].role == "président et chef de la direction, Médias d'Info Canada"


async def test_in_camera_meeting_has_empty_transcript(httpx_mock):
    httpx_mock.add_response(
        json={
            **_meeting_row("ethics", 50, in_camera=True, has_evidence=False),
            "session": "45-1",
            "webcast_url": None,
        }
    )
    httpx_mock.add_response(json={"objects": [], "pagination": _NO_MORE})
    meeting = await client.get_committee_meeting("ethics", "45-1", 50)
    assert meeting.meeting.in_camera and meeting.total_speeches == 0
    assert (meeting.speeches, meeting.witnesses, meeting.has_more) == ([], [], False)


async def test_committee_validation():
    with pytest.raises(InvalidInput):
        await client.get_committee("Finance Committee!")
    with pytest.raises(InvalidInput):
        await client.get_committee_meeting("finance", "45", 1)
    with pytest.raises(InvalidInput):
        await client.get_committee_meeting("finance", "45-1", 0)
    with pytest.raises(InvalidInput):
        await client.get_committee_meeting("finance", "45-1", 1, offset=-1)
    with pytest.raises(InvalidInput):
        await client.search_committee_meetings(date_from="June 1")


async def test_french_ourcommons_links(httpx_mock):
    # French pages checked live 2026-09-26: noscommunes.ca, with French
    # path words in DocumentViewer links; webcast links stay as given.
    en_page = "https://www.ourcommons.ca/Committees/en/FINA?parl=45&session=1"
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/finance/",
        json={
            "name": {"en": "Finance", "fr": "Finances"},
            "short_name": {"en": "Finance", "fr": "Finances"},
            "slug": "finance",
            "parent_url": None,
            "sessions": [{"session": "45-1", "acronym": "FINA", "source_url": en_page}],
            "subcommittees": [],
        },
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/meetings/?committee=finance&limit=10",
        json={"objects": [], "pagination": _NO_MORE},
        is_reusable=True,
    )
    french = await client.get_committee("finance", lang="fr")
    assert french.name == "Finances"
    assert french.sessions[0].source_url == (
        "https://www.noscommunes.ca/Committees/fr/FINA?parl=45&session=1"
    )
    assert (await client.get_committee("finance")).sessions[0].source_url == en_page

    viewer = "https://www.ourcommons.ca/DocumentViewer/en/45-1/FINA/meeting-47/"
    httpx_mock.add_response(
        url="https://api.openparliament.ca/committees/finance/45-1/47/",
        json={
            **_meeting_row("finance", 47),
            "session": "45-1",
            "minutes_url": viewer + "minutes",
            "notice_url": viewer + "notice",
            "webcast_url": "https://www.ourcommons.ca/webcast/45-1/FINA/47",
        },
    )
    httpx_mock.add_response(json={"objects": [], "pagination": _NO_MORE})
    meeting = await client.get_committee_meeting("finance", "45-1", 47, lang="fr")
    french_viewer = "https://www.noscommunes.ca/DocumentViewer/fr/45-1/FINA/reunion-47/"
    assert meeting.minutes_url == french_viewer + "proces-verbal"
    assert meeting.notice_url == french_viewer + "avis-convocation"
    assert meeting.webcast_url == "https://www.ourcommons.ca/webcast/45-1/FINA/47"
    english = await client.get_committee_meeting("finance", "45-1", 47)  # cached
    assert english.minutes_url == viewer + "minutes"
    # A link of another shape is kept rather than guessed at.
    assert client._ourcommons("https://example.org/x", "fr") == "https://example.org/x"
