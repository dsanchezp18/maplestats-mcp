"""Tests for Manitoba results against files saved from Elections Manitoba on 2026-10-03.

mb_1999_votes.xls and mb_1999_summary.xls are the live 1999 files, whole: the votes file is
a real .xls whose bilingual divisions carry the French name on their second row, the
summary is an .xlsx workbook saved under an .xls name. mb_2019_summary.xls is the live 2019
summary of results, with its earlier "Old" sheet first. mb_2023_votes.xlsx and
mb_2023_summary.xlsx are the 2023 files cut to three divisions. mb_1999_areas.xlsx is the
1999 voting-area workbook cut to Arthur-Virden; mb_43ge.zip and mb_42ge.zip hold real
members of the 2023 and 2019 voting-area zips (2019's Concordia has a note row across the
vote columns).
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.elections_provincial import client, constants, manitoba
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_HERE = Path(__file__).parent
_2023 = constants.MB_FILES["43"]
_2019 = constants.MB_FILES["42"]


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _serve(body: bytes):
    """A server for one zip that answers HEAD and byte ranges, as Elections Manitoba does."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


def test_listing_has_the_seven_general_elections():
    listing = client.list_elections("mb")
    assert [e.date[:4] for e in listing.elections] == [
        "2023",
        "2019",
        "2016",
        "2011",
        "2007",
        "2003",
        "1999",
    ]
    assert all(e.seats == 57 and e.detail == "candidate" for e in listing.elections)
    assert listing.elections[0].source_url == _2023.votes
    assert any("Manitoba" in note and "risk" in note for note in listing.notes)


def test_2023_files_give_candidates_electors_and_turnout():
    districts = manitoba.parse_results(_bytes("mb_2023_votes.xlsx"), _bytes("mb_2023_summary.xlsx"))
    # "Union Station/Gare-Union" in the summary matches "Union Station" in the votes file.
    assert [d.name for d in districts] == ["Agassiz", "Brandon West", "Union Station"]
    agassiz = districts[0]
    assert (agassiz.electors, agassiz.rejected_ballots, agassiz.turnout) == (13366, 18, 53.35)
    # The "Declined" and "Rejected" rows are not candidates.
    assert [c.party_code for c in agassiz.candidates] == ["PC", "NDP", "KP", "MLP"]
    winner = agassiz.candidates[0]
    assert winner.name == "Jodie BYRAM" and winner.elected and winner.share == 63.85
    assert agassiz.valid_votes == 7077
    assert agassiz.candidates[3].party == "Manitoba Liberal Party"


def test_1999_french_name_rows_continue_their_division():
    districts = manitoba.parse_results(_bytes("mb_1999_votes.xls"), _bytes("mb_1999_summary.xls"))
    assert len(districts) == 57
    by_name = {d.name: d for d in districts}
    # "Brandon Est" sits on the second candidate's row of Brandon East.
    assert [c.name for c in by_name["Brandon East"].candidates] == [
        "Drew Caldwell",
        "Marty Snelling",
        "Don Jessiman",
        "Peter Logan",
    ]
    assert by_name["Brandon West"].candidates[3].party_code == "CPC-M"
    # The summary writes "Lac Du Bonnet" and "St.Vital"; the names come from the votes file.
    assert "Lac du Bonnet" in by_name and "St. Vital" in by_name
    seats: dict[str, int] = {}
    for d in districts:
        winner = next(c for c in d.candidates if c.elected)
        seats[winner.party_code or ""] = seats.get(winner.party_code or "", 0) + 1
    assert seats == {"NDP": 32, "PC": 24, "Lib.": 1}


def test_2019_summary_skips_the_old_sheet():
    summary = manitoba.parse_summary(_bytes("mb_2019_summary.xls"))
    assert len(summary) == 57
    # The "Old" sheet has 7,646 ballots for Agassiz; the final sheet 7,575.
    assert summary["agassiz"].ballots == 7575 and summary["agassiz"].electors == 13514


def test_votes_file_missing_a_division_is_an_error():
    with pytest.raises(UpstreamError, match="division"):
        manitoba.parse_results(_bytes("mb_2023_votes.xlsx"), _bytes("mb_1999_summary.xls"))


def test_party_labels_reduce_to_one_code():
    assert manitoba.party("NDP / NPD / NPD") == ("New Democratic Party of Manitoba", "NDP")
    assert manitoba.party("PC Manitoba")[1] == "PC"
    assert manitoba.party("The Manitoba Greens")[1] == "GPM"
    assert manitoba.party("Liberal")[1] == "Lib."
    assert manitoba.party("CPC-M / PCC-M")[1] == "CPC-M"


def test_1999_long_voting_area_file():
    areas = manitoba.parse_areas(_bytes("mb_1999_areas.xlsx"))["Arthur-Virden"]
    assert len(areas) == 68
    first = areas[0]
    assert (first.label, first.place, first.declined) == ("1", "Elkhorn Legion Hall", 1)
    assert [(v.name, v.votes) for v in first.votes] == [
        ("Bob Brigden", 8),
        ("Perry Kalynuk", 56),
        ("Larry N. Maguire", 73),
    ]
    # The areas add up to the division's 8,559 valid votes in the summary.
    assert sum(v.votes for a in areas for v in a.votes) == 8559


def test_2011_sheet_heading_both_columns_voting_area():
    # Spruce Woods and St. Vital in 2011 head the number and the place "Voting Area".
    rows: list[list[object]] = [
        ["Voting\nArea", "Voting Area", "ALLAN,\nNancy (NDP)", "BROWN,\nMike (PC)", "Rejected"],
        [1.0, "Windsor Community Club", 64.0, 36.0, 0.0],
        ["Totals", "", 64.0, 36.0, 0.0],
    ]
    areas = manitoba._wide(rows)
    assert areas is not None and len(areas) == 1
    assert (areas[0].label, areas[0].place) == ("1", "Windsor Community Club")
    assert [(v.name, v.party_code, v.votes) for v in areas[0].votes] == [
        ("Nancy ALLAN", "NDP", 64),
        ("Mike BROWN", "PC", 36),
    ]


async def test_voting_areas_read_one_member_by_range(httpx_mock):
    httpx_mock.add_response(url=_2023.votes, content=_bytes("mb_2023_votes.xlsx"))
    httpx_mock.add_response(url=_2023.summary, content=_bytes("mb_2023_summary.xlsx"))
    httpx_mock.add_callback(_serve(_bytes("mb_43ge.zip")), url=_2023.by_area, is_reusable=True)
    result = await client.get_voting_areas("mb", "agassiz", "2023", voting_area="1")
    assert result.district == "Agassiz" and result.election_date == "2023-10-03"
    assert [(r.candidate, r.votes) for r in result.rows] == [
        ("Jodie BYRAM", 76),
        ("Richard DAVIES", 3),
        ("Danica WIGGINS", 21),
        ("Mark WILSON", 7),
    ]
    assert len(result.areas) == 63 and result.areas[0].electors == 181
    assert result.areas[-1].voting_area.startswith("BALLOTS CAST OUTSIDE")
    assert result.district_valid_votes == result.areas_valid_votes == 7077
    assert "project owner's risk" in (result.provenance.limits or "")
    assert result.provenance.url == _2023.by_area


async def test_voting_areas_skip_the_2019_note_row(httpx_mock):
    body = _bytes("mb_42ge.zip")
    httpx_mock.add_callback(_serve(body), url=_2019.by_area, is_reusable=True)
    members = await manitoba.list_area_files("42")
    parsed = await manitoba.read_area_file("42", members[0])
    areas = parsed[""]
    assert manitoba.member_key(members[0].name) == "concordia"
    assert areas[-1].label == "Non Resident Advance/non-Résident anticipation"
    assert sum(v.votes for a in areas for v in a.votes) == 7212


async def test_voting_areas_need_one_manitoba_division(httpx_mock):
    with pytest.raises(InvalidInput, match="Manitoba"):
        await client.get_voting_areas("sk", "nutana")
    httpx_mock.add_response(url=_2023.votes, content=_bytes("mb_2023_votes.xlsx"))
    httpx_mock.add_response(url=_2023.summary, content=_bytes("mb_2023_summary.xlsx"))
    with pytest.raises(InvalidInput, match="Brandon West"):
        await client.get_voting_areas("mb", "on")
    with pytest.raises(InvalidInput, match="choose from"):
        await client.get_voting_areas("mb", "Nowhere")


async def test_seats_and_results_carry_the_terms_notice(httpx_mock):
    httpx_mock.add_response(url=_2023.votes, content=_bytes("mb_2023_votes.xlsx"))
    httpx_mock.add_response(url=_2023.summary, content=_bytes("mb_2023_summary.xlsx"))
    seats = await client.get_seats("mb")
    assert seats.seats_contested == 3 and seats.parties[0].seats == 2
    assert "project owner's risk" in (seats.provenance.limits or "")
    assert seats.attribution == constants.MB_ATTRIBUTION
    results = await client.get_results("mb", "2023", party="liberal")
    assert {r.party_code for r in results.rows} == {"MLP"}
    assert results.districts[0].electors == 13366
