"""Tests for Saskatchewan results against files cut from the live ones (saved 2026-10-02).

sk_2024.csv (Windows-1252, 'Last, First' names, two constituencies), sk_2020.csv (UTF-8
with a byte order mark, thousands commas in vote counts, a vote-by-mail row), sk_2016.csv
(Windows-1252, different header spellings) and sk_2011.xlsx (two sheets of the statement
of votes workbook, one with the source's 'Sasktoon' misspelling, polls cut to four rows).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.elections_provincial import client, constants, saskatchewan
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import UpstreamError

_HERE = Path(__file__).parent


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def test_listing_has_the_four_general_elections():
    listing = client.list_elections("sk")
    assert [(e.date, e.seats) for e in listing.elections] == [
        ("2024-10-28", 61),
        ("2020-10-26", 61),
        ("2016-04-04", 61),
        ("2011-11-07", 58),
    ]
    assert listing.elections[0].province_name == "Saskatchewan"
    assert listing.elections[0].detail == "candidate"
    assert listing.elections[0].source_url == constants.SK_FILES["2024"]
    assert any("Saskatchewan" in note and "risk" in note for note in listing.notes)


def test_2024_file_flips_names_and_picks_the_winner():
    districts = saskatchewan.parse_csv(_bytes("sk_2024.csv"))
    assert [d.name for d in districts] == ["Athabasca", "Saskatoon Nutana"]
    athabasca = districts[0]
    assert athabasca.number == "ATH" and athabasca.rejected_ballots == 1
    # Parties with no candidate and no votes (BPSK, IND, PC, SPP, SUP) are left out.
    assert [c.party_code for c in athabasca.candidates] == ["NDP", "SP", "SGP"]
    winner = athabasca.candidates[0]
    assert winner.name == "Leroy Laliberte" and winner.elected and winner.votes == 415
    assert winner.party == "New Democratic Party" and winner.share == 75.73
    assert athabasca.valid_votes == 548
    assert sum(c.elected for c in athabasca.candidates) == 1


def test_2020_file_reads_thousands_commas_and_the_byte_order_mark():
    districts = saskatchewan.parse_csv(_bytes("sk_2020.csv"))
    assert [d.name for d in districts] == ["Arm River", "Regina Lakeview"]
    lakeview = districts[1]
    # The vote-by-mail row writes the NDP count as "1,489".
    assert lakeview.candidates[0].name == "Carla Beck" and lakeview.candidates[0].votes == 2559
    assert lakeview.candidates[0].party_code == "NDP"
    assert districts[0].candidates[0].name == "Dana Skoropad"
    assert districts[0].candidates[0].party == "Saskatchewan Party"


def test_2016_file_uses_its_own_header_spellings():
    districts = saskatchewan.parse_csv(_bytes("sk_2016.csv"))
    assert [d.name for d in districts] == ["Arm River", "Saskatoon Riversdale"]
    riversdale = districts[1]
    assert [c.party_code for c in riversdale.candidates] == ["NDP", "SP", "LIB", "GP"]
    assert riversdale.candidates[0].elected and riversdale.rejected_ballots == 3
    assert riversdale.candidates[3].party == "Green Party"


def test_2011_workbook_sums_the_poll_rows_and_fixes_the_misspelled_sheet():
    districts = saskatchewan.parse_xlsx(_bytes("sk_2011.xlsx"))
    assert [d.name for d in districts] == ["Athabasca", "Saskatoon Nutana"]
    athabasca = districts[0]
    assert athabasca.number is None
    assert [(c.name, c.party_code, c.votes) for c in athabasca.candidates] == [
        ("Buckley Belanger", "NDP", 71),
        ("Bobby Woods", "SP", 49),
        ("George A. Durocher", "GP", 11),
    ]
    assert athabasca.candidates[0].elected and athabasca.valid_votes == 131


def test_unreadable_files_raise():
    with pytest.raises(UpstreamError, match="expected columns"):
        saskatchewan.parse_csv(b"a,b\n1,2\n")
    with pytest.raises(UpstreamError, match="no rows"):
        saskatchewan.parse_csv(_bytes("sk_2016.csv").splitlines()[0] + b"\r\n")


async def test_get_results_and_seats_over_the_mocked_download(httpx_mock):
    httpx_mock.add_response(url=constants.SK_FILES["2024"], content=_bytes("sk_2024.csv"))
    result = await client.get_results("sk", "2024", district="nutana", winners_only=True)
    assert result.total_rows == 1
    row = result.rows[0]
    assert row.district == "Saskatoon Nutana" and row.candidate == "Erika Ritchie"
    assert row.party_code == "NDP" and row.votes == 3938 and row.elected
    assert "Elections Saskatchewan" in result.attribution
    assert result.provenance.limits is not None and "risk" in result.provenance.limits
    assert result.provenance.url == constants.SK_FILES["2024"]

    # The second call reads the cached parse, so no second download is mocked.
    seats = await client.get_seats("sk", "2024-10-28")
    assert seats.seats_contested == 2 and seats.seats_decided == 2
    assert (seats.parties[0].party, seats.parties[0].seats) == ("New Democratic Party", 2)
    assert seats.provenance.limits is not None and "risk" in seats.provenance.limits


async def test_2011_workbook_is_read_through_the_client(httpx_mock):
    httpx_mock.add_response(url=constants.SK_FILES["2011"], content=_bytes("sk_2011.xlsx"))
    result = await client.get_results("sk", "2011", party="sp")
    assert {r.district for r in result.rows} == {"Athabasca", "Saskatoon Nutana"}
    assert all(r.party_code == "SP" for r in result.rows)
