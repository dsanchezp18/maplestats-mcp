"""Tests for provincial election results against real payloads saved 2026-10-01.

The fixtures are cut from the live files, with their original fields and quirks:
qc_2022.json and qc_2012.json (Elections Quebec, three and one ridings),
ab_results_2023.html and ab_winners_2023.html (Elections Alberta's unbalanced
upper-case HTML, three divisions including one with two independents in one cell),
bc_by_va.csv (Windows-1252 with a byte order mark, one district in 2020, one
by-election row that must be ignored, and a candidate with an accent) and
bc_by_place.csv (UTF-8, two districts in 2024).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.elections_provincial import (
    alberta,
    british_columbia,
    client,
    constants,
    quebec,
)
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


QC_2022 = quebec.file_url("2022-10-03")
QC_2012 = quebec.file_url("2012-09-04")
AB_PAGE = alberta.results_url("101")
AB_WINNERS = alberta.winners_url("101")


def _mock_alberta(httpx_mock):
    httpx_mock.add_response(url=AB_PAGE, content=_bytes("ab_results_2023.html"))
    httpx_mock.add_response(url=AB_WINNERS, content=_bytes("ab_winners_2023.html"))


# --- listing and input checks -------------------------------------------------------------


def test_list_elections_covers_three_provinces_and_blocks_ontario():
    listing = client.list_elections()
    by_province = {p: [e for e in listing.elections if e.province == p] for p in ("qc", "ab", "bc")}
    assert len(by_province["qc"]) == 14 and by_province["qc"][0].date == "2022-10-03"
    assert [e.date[:4] for e in by_province["ab"]] == ["2023", "2019", "2015", "2012", "2008"]
    assert by_province["bc"][0].seats == 93
    assert [b.province for b in listing.blocked] == ["on"]
    assert "scrape" in listing.blocked[0].reason
    assert client.list_elections("bc", "fr").elections[0].province_name == "Colombie-Britannique"
    assert len(client.list_elections("ab").elections) == 5


async def test_ontario_and_unknown_inputs_are_invalid():
    with pytest.raises(InvalidInput, match="Ontario"):
        await client.get_results("on")
    with pytest.raises(InvalidInput, match="province"):
        await client.get_results("mb")
    with pytest.raises(InvalidInput, match="election must be"):
        await client.get_results("qc", "1999")
    with pytest.raises(InvalidInput, match="limit"):
        await client.get_results("qc", limit=0)
    with pytest.raises(InvalidInput, match="offset"):
        await client.get_results("qc", offset=-1)


# --- Quebec -------------------------------------------------------------------------------


def test_quebec_parse_reads_names_parties_and_the_winner():
    districts = quebec.parse(_bytes("qc_2022.json"))
    assert [d.name for d in districts] == ["Abitibi-Est", "Gaspé", "Mercier"]
    first = districts[0]
    assert (first.number, first.electors, first.valid_votes, first.rejected_ballots) == (
        "648",
        33723,
        20695,
        404,
    )
    winner = first.candidates[0]
    assert winner.name == "Pierre Dufour" and winner.elected and winner.votes == 9762
    assert winner.party == "Coalition avenir Québec - L'équipe François Legault"
    assert winner.party_code == "C.A.Q.-E.F.L." and winner.share == 47.17
    assert sum(c.elected for c in first.candidates) == 1


def test_quebec_parse_handles_the_older_file_layout():
    districts = quebec.parse(_bytes("qc_2012.json"))
    assert districts[0].candidates[0].name == "Élizabeth Larouche"
    assert districts[0].candidates[0].party == "Parti québécois"
    assert districts[0].number == "579"


def test_quebec_parse_rejects_a_file_without_ridings():
    with pytest.raises(UpstreamError):
        quebec.parse(b'{"statistiques": {}}')
    with pytest.raises(UpstreamError):
        quebec.parse(b"<html>not json</html>")


async def test_quebec_district_filter_ignores_accents(httpx_mock):
    httpx_mock.add_response(url=QC_2022, content=_bytes("qc_2022.json"))
    result = await client.get_results("qc", "2022", district="gaspe", winners_only=True)
    assert result.total_rows == 1
    row = result.rows[0]
    assert row.district == "Gaspé" and row.candidate == "Stéphane Sainte-Croix"
    assert row.party_code == "C.A.Q.-E.F.L." and row.elected
    assert result.districts[0].electors == 30190 and result.districts[0].turnout == 60.96
    assert result.districts[0].winner == "Stéphane Sainte-Croix"
    assert result.provenance.url == QC_2022
    assert "Élections Québec" in result.attribution


async def test_quebec_party_candidate_and_number_filters(httpx_mock):
    httpx_mock.add_response(url=QC_2022, content=_bytes("qc_2022.json"))
    by_code = await client.get_results("qc", "2022-10-03", party="caq")
    assert by_code.total_rows == 3 and all(r.party_code == "C.A.Q.-E.F.L." for r in by_code.rows)
    by_name = await client.get_results("qc", "2022", party="quebec solidaire")
    assert by_name.total_rows == 3
    by_candidate = await client.get_results("qc", "2022", candidate="meganne perry")
    assert by_candidate.total_rows == 1
    assert by_candidate.rows[0].candidate == "Méganne Perry Mélançon"
    by_number = await client.get_results("qc", "2022", district="350")
    assert {r.district for r in by_number.rows} == {"Mercier"}


async def test_quebec_defaults_to_the_latest_election_and_pages(httpx_mock):
    httpx_mock.add_response(url=QC_2022, content=_bytes("qc_2022.json"))
    result = await client.get_results("qc", limit=2)
    assert result.election_date == "2022-10-03" and len(result.rows) == 2
    assert result.truncated and result.provenance.limits
    rest = await client.get_results("qc", limit=2, offset=2)
    assert rest.rows[0].candidate == "Benjamin Gingras" and rest.offset == 2
    assert rest.provenance.cached


async def test_quebec_seat_summary_adds_up(httpx_mock):
    httpx_mock.add_response(url=QC_2022, content=_bytes("qc_2022.json"))
    summary = await client.get_seats("qc", "2022")
    assert summary.seats_contested == 3 and summary.seats_decided == 3
    assert summary.total_valid_votes == 20695 + 18219 + 27363
    assert sum(p.seats for p in summary.parties) == 3
    assert summary.parties[0].seats == 2
    assert summary.parties[0].vote_share == pytest.approx(
        100 * summary.parties[0].votes / summary.total_valid_votes, abs=0.01
    )


async def test_missing_file_is_not_found(httpx_mock):
    httpx_mock.add_response(url=QC_2012, status_code=404)
    with pytest.raises(NotFound):
        await client.get_results("qc", "2012")


async def test_upstream_server_error_is_typed(httpx_mock):
    httpx_mock.add_response(url=QC_2012, status_code=500, is_reusable=True)
    with pytest.raises(UpstreamError):
        await client.get_results("qc", "2012")


# --- Alberta ------------------------------------------------------------------------------


def test_alberta_parse_names_winners_and_drops_zero_columns():
    winners = alberta.parse_winners(_bytes("ab_winners_2023.html").decode("utf-8"))
    assert winners["01"] == ("DIANA BATTEN", 10959)
    districts = alberta.parse_results(_bytes("ab_results_2023.html").decode("utf-8"), winners)
    acadia = districts[0]
    assert (acadia.name, acadia.number, acadia.turnout, acadia.valid_votes) == (
        "CALGARY-ACADIA",
        "01",
        65.3,
        22562,
    )
    assert [c.party_code for c in acadia.candidates] == ["NDP", "GPA", "SM", "UCP", "WLC", "IND"]
    ndp = acadia.candidates[0]
    assert ndp.name == "DIANA BATTEN" and ndp.elected and ndp.party == "ALBERTA NDP"
    assert ndp.share == 48.57
    assert all(c.name is None for c in acadia.candidates[1:])


def test_alberta_parse_splits_two_independents_in_one_cell():
    winners = alberta.parse_winners(_bytes("ab_winners_2023.html").decode("utf-8"))
    districts = alberta.parse_results(_bytes("ab_results_2023.html").decode("utf-8"), winners)
    wood_buffalo = districts[2]
    independents = [c for c in wood_buffalo.candidates if c.party_code == "IND"]
    assert sorted(c.votes for c in independents) == [331, 625]
    assert wood_buffalo.candidates[2].name == "TANY YAO"


def test_alberta_parse_rejects_a_page_without_the_table():
    with pytest.raises(UpstreamError):
        alberta.parse_results("<html><body>maintenance</body></html>", {})
    page = _bytes("ab_results_2023.html").decode("utf-8")
    first_row = page.index("orResultsED.cfm")
    cell = '<TD style="text-align:right;">'
    cut = page.index(cell, first_row)
    broken = page[:cut] + page[cut + len(cell) :]
    with pytest.raises(UpstreamError, match="cells"):
        alberta.parse_results(broken, {})


async def test_alberta_results_and_seats(httpx_mock):
    _mock_alberta(httpx_mock)
    result = await client.get_results("ab", "2023", party="ucp", winners_only=True)
    assert [r.district for r in result.rows] == ["FORT MCMURRAY-WOOD BUFFALO"]
    assert result.rows[0].candidate == "TANY YAO" and result.rows[0].district_number == "61"
    seats = await client.get_seats("ab", "2023-05-29")
    assert seats.seats_decided == 3
    names = {p.party: p.seats for p in seats.parties}
    assert names["ALBERTA NDP"] == 2 and names["UNITED CONSERVATIVE PARTY"] == 1
    independents = next(p for p in seats.parties if p.party == "INDEPENDENT")
    assert independents.candidates == 3 and independents.seats == 0
    assert "not an official version" in seats.attribution


# --- British Columbia ---------------------------------------------------------------------


def test_bc_parse_sums_votes_and_ignores_by_elections():
    by_year = british_columbia.parse(_bytes("bc_by_va.csv"))
    assert list(by_year) == ["2020"]
    abbotsford, chilliwack = by_year["2020"]
    assert (abbotsford.name, abbotsford.number) == ("Abbotsford South", "ABS")
    assert abbotsford.candidates[0].name == "Bruce Banman" and abbotsford.candidates[0].elected
    assert sum(c.votes for c in abbotsford.candidates) == abbotsford.valid_votes
    assert abbotsford.rejected_ballots is not None and abbotsford.rejected_ballots > 0
    assert [c.votes for c in abbotsford.candidates] == sorted(
        (c.votes for c in abbotsford.candidates), reverse=True
    )
    assert chilliwack.candidates[0].name == "Eli Gagné"


def test_bc_parse_reads_the_voting_place_file():
    by_year = british_columbia.parse(_bytes("bc_by_place.csv"))
    assert list(by_year) == ["2024"]
    vancouver = by_year["2024"][1]
    assert vancouver.name == "Vancouver-Hastings"
    assert vancouver.candidates[0].name == "Niki Sharma" and vancouver.candidates[0].elected
    assert vancouver.candidates[0].party == "BC NDP"


def test_bc_parse_rejects_an_unexpected_file():
    with pytest.raises(UpstreamError):
        british_columbia.parse(b"A,B\n1,2\n")


def test_bc_files_follow_the_year():
    assert british_columbia.file_url("2024") == constants.BC_FILE_BY_PLACE
    assert british_columbia.file_url("2017") == constants.BC_FILE_BY_VA


async def test_bc_results_use_one_download_for_several_calls(httpx_mock):
    httpx_mock.add_response(url=constants.BC_FILE_BY_VA, content=_bytes("bc_by_va.csv"))
    first = await client.get_results("bc", "2020", candidate="gagne")
    assert first.total_rows == 1 and first.rows[0].candidate == "Eli Gagné"
    assert first.rows[0].party == "Libertarian" and first.rows[0].party_code is None
    second = await client.get_results("bc", "2020-10-24", district="abbotsford", winners_only=True)
    assert second.rows[0].candidate == "Bruce Banman" and second.provenance.cached
    assert second.districts[0].rejected_ballots is not None
    assert "Elections BC Open Data Licence" in second.attribution


async def test_bc_year_missing_from_the_file_is_an_error(httpx_mock):
    httpx_mock.add_response(url=constants.BC_FILE_BY_VA, content=_bytes("bc_by_place.csv"))
    with pytest.raises(UpstreamError, match="2017"):
        await client.get_results("bc", "2017")
