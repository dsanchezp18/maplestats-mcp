"""Tests for the candidate-level historical results (Sevi, Who Runs?).

The file is built here with the live file's real column layout and rows taken
from it (a 2000 Newfoundland riding and a 1867 Halifax row), since the live
file is 16.6 MB.
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.elections_results import candidates
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_HEADER = (
    "id\tparliament\tyear\ttype_elxn\telected\tcandidate_name\tedate\tincumbent\tgender"
    "\tbirth_year\tcountry_birth\tlgbtq2_out\tindigenousorigins\toccupation\tlawyer"
    "\tcensuscategory\triding_id\triding\tprovince\tvotes\tpercent_votes\tacclaimed"
    "\tswitcher\tmultiple_candidacy\tparty_raw\tparty_minor_group\tparty_major_group"
    "\tgov_party_raw\tgov_minor_group\tgov_major_group\tnum_candidates"
)


def _line(**values: str) -> str:
    row: dict[str, str] = {name: "" for name in _HEADER.split("\t")}
    row.update(values)
    return "\t".join(row[c] for c in _HEADER.split("\t"))


_ROWS = [
    _line(
        id="5100",
        parliament="37",
        year="2000",
        type_elxn="General",
        elected="Not elected",
        candidate_name='"DAY, Judy"',
        edate="2000-11-27",
        incumbent="Not incumbent",
        gender="F",
        occupation="retired registered nurse",
        riding="ST. JOHN'S EAST",
        province="Newfoundland and Labrador",
        votes="254",
        percent_votes="0.57263952",
        acclaimed="Not acclaimed",
        party_raw="Independent",
    ),
    _line(
        id="7",
        parliament="37",
        year="2000",
        type_elxn="General",
        elected="Elected",
        candidate_name="HEARN, Loyola",
        edate="2000-11-27",
        incumbent="Incumbent",
        gender="M",
        riding="ST. JOHN'S WEST",
        province="Newfoundland and Labrador",
        votes="11392",
        percent_votes="35.481358",
        acclaimed="Not acclaimed",
        party_raw="Progressive Conservative",
    ),
    _line(
        id="26093",
        parliament="1",
        year="1867",
        type_elxn="General",
        elected="Elected",
        candidate_name="POWER,",
        edate="1867-08-07",
        riding="HALIFAX",
        province="Nova Scotia",
        votes="2367",
        percent_votes="26.125828",
        acclaimed="Not acclaimed",
        party_raw="Anti-Confederate",
    ),
    _line(
        id="9",
        parliament="37",
        year="2002",
        type_elxn="By-election",
        elected="Elected",
        candidate_name="ZED, Quebec",
        riding="MONTRÉAL",
        province="Quebec",
        votes="",
        percent_votes="",
        acclaimed="Acclaimed",
        party_raw="Liberal",
    ),
]
_BODY = "\n".join([_HEADER, *_ROWS]).encode("utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def dataset(httpx_mock):
    httpx_mock.add_response(
        url=candidates.DATASET_FILE_URL,
        status_code=303,
        headers={"location": "https://storage.example/who-runs.tab"},
    )
    httpx_mock.add_response(url="https://storage.example/who-runs.tab", content=_BODY)


async def test_candidate_rows_carry_names_party_and_votes(dataset):
    result = await candidates.get_candidates(election=37)
    assert result.total_candidates == 2 and result.elected_in_selection == 1
    first = result.candidates[0]
    assert first.candidate_name == "DAY, Judy" and first.party == "Independent"
    assert first.votes == 254 and first.vote_share_percent == pytest.approx(0.5726, abs=1e-3)
    assert first.incumbent is False and first.gender == "F" and not first.elected
    assert "CC0" in result.licence and "10.7910/DVN/ABFNSQ" in result.citation


async def test_filters_and_winners_only(dataset):
    result = await candidates.get_candidates(year=2000, riding="st. john's", winners_only=True)
    assert [c.candidate_name for c in result.candidates] == ["HEARN, Loyola"]
    assert result.candidates[0].incumbent is True


async def test_first_election_and_blank_fields(dataset):
    result = await candidates.get_candidates(election=1, province="nova")
    assert result.candidates[0].riding == "HALIFAX"
    assert result.candidates[0].incumbent is None and result.candidates[0].gender is None


async def test_by_elections_are_separate_and_accent_insensitive(dataset):
    general = await candidates.get_candidates(year=2002)
    assert general.total_candidates == 0
    by = await candidates.get_candidates(year=2002, election_type="by-election", riding="montreal")
    assert by.candidates[0].acclaimed and by.candidates[0].votes is None
    every = await candidates.get_candidates(election_type="all", limit=2)
    assert every.total_candidates == 4 and every.truncated


async def test_validation_errors():
    with pytest.raises(InvalidInput):
        await candidates.get_candidates(election=0)
    with pytest.raises(InvalidInput):
        await candidates.get_candidates(limit=0)
    with pytest.raises(InvalidInput):
        await candidates.get_candidates(offset=-1)


async def test_unexpected_layout_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=candidates.DATASET_FILE_URL, content=b"a\tb\n1\t2\n")
    with pytest.raises(UpstreamError):
        await candidates.get_candidates()
