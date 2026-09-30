"""Tests for the historical (1867 to 2015) riding results.

The workbook is built here with the live file's real column layout and
values taken from it (Avalon in the 38th and 42nd general elections,
Addington in the 1st), since the live file is 3.3 MB.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.elections_results import historical
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

_HEADER = (
    ["parliament_number", "election_date", "election_year", "parliament_duration", "sitting_days"]
    + ["cansim_pop_national", "house_size", "cabinet_size", "votes_national", "province_number"]
    + ["province_name", "cansim_pop_province", "constituency_name", "super_constituency", "urban"]
    + ["pop_local", "electors_local", "rejected_local", "ballots_local", "candidates_local"]
    + ["seats_local", "incumbent_party", "incumbent_number", "incumbent_won", "acclamation"]
    + [f"{c}{i}" for i in range(1, 14) for c in ("k", "v")]
    + ["old_name"]
)


def _row(values: dict[str, object], pairs: list[tuple[str, int]]) -> list[object]:
    row: dict[str, object] = dict.fromkeys(_HEADER)
    row.update(values)
    for i, (party, votes) in enumerate(pairs, start=1):
        row[f"k{i}"], row[f"v{i}"] = party, votes
    for i in range(len(pairs) + 1, 14):
        row[f"k{i}"], row[f"v{i}"] = None, 0
    return [row[c] for c in _HEADER]


def _workbook() -> bytes:
    workbook = Workbook()
    raw = workbook.active
    raw.title = historical.RAW_SHEET
    raw.append(_HEADER)
    raw.append(
        _row(
            {
                "parliament_number": 1,
                "election_date": 18670807,
                "province_name": "Ontario",
                "constituency_name": "ADDINGTON",
                "electors_local": 2768,
                "ballots_local": 2114,
                "candidates_local": 7,
                "seats_local": 1,
                "acclamation": 0,
            },
            [("Cons", 1120), ("Lib_Cons", 991), ("Unknown", 2)],
        )
    )
    raw.append(
        _row(
            {
                "parliament_number": 38,
                "election_date": 20040628,
                "province_name": "Newfoundland and Labrador",
                "constituency_name": "AVALON",
                "electors_local": 63745,
                "rejected_local": 336,
                "ballots_local": 31762,
                "candidates_local": 4,
                "seats_local": 1,
                "acclamation": 0,
            },
            [("Lib", 18335), ("C", 9211), ("NDP", 3450), ("GP", 430)],
        )
    )
    raw.append(
        _row(
            {
                "parliament_number": 42,
                "election_date": 20151019,
                "province_name": "Quebec",
                "constituency_name": "ACCLAIMED EXAMPLE",
                "old_name": "OLD EXAMPLE",
                "seats_local": 1,
                "acclamation": 1,
            },
            [("Lib", 0)],
        )
    )
    parties = workbook.create_sheet(historical.PARTY_SHEET)
    for _ in range(3):
        parties.append([None] * 8)
    for mnemonic, name in (
        ("Lib", "Liberal"),
        ("C", "Conservative Party of Canada"),
        ("NDP", "New Democratic Party"),
        ("Cons", "Conservative (Cons and C) and Progressive Conservative (PC)"),
    ):
        parties.append([None] * 6 + [mnemonic, name])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def workbook(httpx_mock):
    httpx_mock.add_response(
        url=historical.DATASET_FILE_URL,
        status_code=303,
        headers={"location": "https://storage.example/winer.xlsx"},
    )
    httpx_mock.add_response(url="https://storage.example/winer.xlsx", content=_workbook())


async def test_riding_rows_carry_votes_names_and_leading_party(workbook):
    result = await historical.get_historical(election=38)
    assert result.total_ridings == 1
    riding = result.ridings[0]
    assert riding.constituency == "AVALON" and str(riding.election_date) == "2004-06-28"
    assert riding.leading_party == "Lib" and riding.ballots_cast == 31762
    assert [(r.party, r.votes) for r in riding.results][:2] == [("Lib", 18335), ("C", 9211)]
    assert riding.results[1].party_name == "Conservative Party of Canada"
    assert "CC0" in result.licence and "10.5683/SP2/1N4Y1G" in result.citation


async def test_first_election_and_unknown_party_names(workbook):
    result = await historical.get_historical(election=1, province="ontario")
    riding = result.ridings[0]
    assert riding.results[0].party == "Cons"
    assert riding.results[2].party_name is None


async def test_acclamation_has_no_leading_party(workbook):
    result = await historical.get_historical(constituency="old example")
    assert result.ridings[0].acclamation and result.ridings[0].leading_party is None
    assert result.ridings[0].results == []


async def test_party_filter_matches_mnemonic_or_name(workbook):
    assert (await historical.get_historical(party="ndp")).total_ridings == 1
    assert (await historical.get_historical(party="new democratic")).total_ridings == 1
    assert (await historical.get_historical(party="Bloc")).total_ridings == 0


async def test_paging(workbook):
    first = await historical.get_historical(limit=1)
    assert first.total_ridings == 3 and first.truncated
    assert first.provenance.limits


async def test_out_of_range_election_is_invalid_input():
    for bad in (0, 43, 45):
        with pytest.raises(InvalidInput):
            await historical.get_historical(election=bad)
