"""Tests for the election results client against real payloads saved 2026-09-29.

The CSV fixtures are the first rows of Elections Canada's live files with
their headers and byte order marks: candidates_45.csv, district_45.csv and
votes_45.csv from the 45th general election, and candidates_38.csv (the
38th's Windows-1252 file with a different column layout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.elections_results import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _url(election: int, table: int) -> str:
    return client.file_url(constants.ELECTIONS[election], table)


def test_file_urls_follow_each_elections_layout():
    assert _url(45, 12) == (
        "https://www.elections.ca/res/rep/off/ovrGE45/62/data_donnees/table_tableau12.csv"
    )
    assert _url(38, 12) == "https://www.elections.ca/scripts/OVR2004/23/data/table12.csv"
    assert _url(40, 3).endswith("/scripts/OVR2008/31/data/table_tableau03.csv")


def test_list_elections_covers_38_to_45_in_both_languages():
    listing = client.list_elections("en")
    assert [e.election for e in listing.elections] == [45, 44, 43, 42, 41, 40, 39, 38]
    assert listing.elections[0].date == "2025-04-28"
    assert {t.table for t in listing.tables} >= {"candidates", "district_results", "seats"}
    assert "Cloudflare" in listing.not_covered[0]
    assert "Cloudflare" in client.list_elections("fr").not_covered[0]


def test_list_elections_links_pages_in_the_callers_language():
    # elections.ca serves the same pages in French under lang=f (checked live
    # 2026-10-03); lang="fr" used to return the lang=e pages.
    english = client.list_elections("en")
    french = client.list_elections("fr")
    assert english.elections[0].page.endswith("45gedata&document=summary&lang=e")
    assert french.elections[0].page.endswith("45gedata&document=summary&lang=f")
    assert all("lang=e" not in e.page for e in french.elections)
    assert french.provenance.url.endswith("document=ge&lang=f")
    assert english.provenance.url.endswith("document=ge&lang=e")


async def test_unknown_election_or_table_is_invalid_input():
    with pytest.raises(InvalidInput):
        await client.get_table(37, "candidates")
    with pytest.raises(InvalidInput):
        await client.get_table(45, "nonsense")
    with pytest.raises(InvalidInput):
        await client.get_table(45, "candidates", limit=0)


async def test_candidates_filter_by_district_accent_insensitive(httpx_mock):
    httpx_mock.add_response(url=_url(45, 12), content=_bytes("candidates_45.csv"))
    result = await client.get_table(45, "candidates", district="cape spear")
    assert result.total_rows == 5
    assert {r["Electoral District Number/Numéro de circonscription"] for r in result.rows} == {
        "10002"
    }
    assert result.date == "2025-04-28"
    assert result.provenance.url == _url(45, 12)


async def test_district_number_matches_exactly(httpx_mock):
    httpx_mock.add_response(url=_url(45, 12), content=_bytes("candidates_45.csv"))
    result = await client.get_table(45, "candidates", district="10001")
    assert result.total_rows == 4


async def test_winners_only_keeps_the_majority_rows(httpx_mock):
    httpx_mock.add_response(url=_url(45, 12), content=_bytes("candidates_45.csv"))
    result = await client.get_table(45, "candidates", winners_only=True)
    names = [r["Candidate/Candidat"] for r in result.rows]
    assert result.total_rows == 3
    assert any("Paul Connors" in n for n in names)


async def test_thirty_eighth_election_uses_its_own_columns(httpx_mock):
    httpx_mock.add_response(url=_url(38, 12), content=_bytes("candidates_38.csv"))
    result = await client.get_table(38, "candidates", district="Avalon", winners_only=True)
    assert result.total_rows == 1
    assert "Efford" in result.rows[0]["Candidate/Candidat"]
    assert "Electoral District/Circonscription" in result.columns


async def test_party_filter_and_pagination(httpx_mock):
    httpx_mock.add_response(url=_url(45, 12), content=_bytes("candidates_45.csv"))
    result = await client.get_table(45, "candidates", party="Conservative", limit=1)
    assert result.total_rows >= 3 and result.truncated
    assert len(result.rows) == 1
    assert result.provenance.limits and "of" in result.provenance.limits


async def test_french_errors_and_provenance(httpx_mock):
    httpx_mock.add_response(url=_url(45, 12), content=_bytes("candidates_45.csv"))
    result = await client.get_table(45, "candidates", party="Conservative", limit=1, lang="fr")
    prov = result.provenance
    assert (prov.limits or "").startswith("Lignes 1 à 1 sur")
    assert "tels que publiés" in (prov.limits or "")
    assert prov.coverage == "45e élection générale (2025-04-28), tableau 12."
    assert (prov.licence or "").startswith("Licence du gouvernement ouvert – Canada")
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: elections_results\xa0: "):
        await client.get_table(37, "candidates", lang="fr")
    listing = client.list_elections("fr")
    assert listing.provenance.coverage == "38e à 45e élections générales (2004 à 2025)."
    with pytest.raises(InvalidInput, match=r"^elections_results: election must be one of"):
        await client.get_table(37, "candidates")


async def test_province_filter_needs_a_province_column(httpx_mock):
    httpx_mock.add_response(url=_url(45, 8), content=_bytes("votes_45.csv"))
    with pytest.raises(InvalidInput, match="province"):
        await client.get_table(45, "votes_by_party", province="Alberta")


async def test_winners_only_rejects_other_tables(httpx_mock):
    httpx_mock.add_response(url=_url(45, 11), content=_bytes("district_45.csv"))
    with pytest.raises(InvalidInput, match="candidates"):
        await client.get_table(45, "district_results", winners_only=True)


async def test_district_results_carry_the_elected_candidate(httpx_mock):
    httpx_mock.add_response(url=_url(45, 11), content=_bytes("district_45.csv"))
    result = await client.get_table(45, "district_results", district="Avalon")
    assert result.total_rows == 1
    assert "Connors" in result.rows[0]["Elected Candidate/Candidat élu"]


async def test_html_error_page_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=_url(45, 12), content=b"<!DOCTYPE html><html><body>Error page</body></html>"
    )
    with pytest.raises(NotFound):
        await client.get_table(45, "candidates")


async def test_table_redirect_to_another_host_is_refused(httpx_mock):
    httpx_mock.add_response(
        url=_url(45, 12), status_code=302, headers={"Location": "https://evil.example/t.csv"}
    )
    with pytest.raises(UpstreamError, match="evil.example"):
        await client.get_table(45, "candidates")
    assert [r.url.host for r in httpx_mock.get_requests()] == ["www.elections.ca"]


# Rows in the shape of candidates_45.csv for provinces its first rows do not reach.
_ELSEWHERE = (
    '"Alberta/Alberta","Calgary Centre","48001","Ann Smith Liberal/Libéral",'
    '"Calgary, Alta./Alb.","Teacher/Enseignant",100,50,10,5\r\n'
    '"Ontario/Ontario","Ajax","35001","Raj Patel Conservative/Conservateur",'
    '"Ajax, Ont.","Lawyer/Avocat",100,50,10,5\r\n'
    '"Yukon/Yukon","Yukon","60001","Dana Fox NDP-New Democratic Party/NPD-Nouveau Parti '
    'démocratique","Whitehorse, Y.T./Yn","Nurse/Infirmier",100,50,10,5\r\n'
    '"Northwest Territories/Territoires du Nord-Ouest","Northwest Territories","61001",'
    '"Lee Wong Liberal/Libéral","Yellowknife, N.W.T./T.N.-O.","Pilot/Pilote",100,50,10,5\r\n'
)


async def test_province_filter_takes_codes_and_whole_names(httpx_mock):
    # province="AB" used to be a substring of "Labrador" and returned Newfoundland and
    # Labrador; "ON" matched Yukon, "NT" matched Ontario, and "NL" and "YT" matched nothing.
    httpx_mock.add_response(
        url=_url(45, 12), content=_bytes("candidates_45.csv") + _ELSEWHERE.encode()
    )

    async def provinces(given: str) -> set[str]:
        result = await client.get_table(45, "candidates", province=given)
        return {r["Province"].split("/")[0] for r in result.rows}

    nl = "Newfoundland and Labrador"
    assert await provinces("AB") == {"Alberta"}
    assert await provinces("ON") == {"Ontario"}
    assert await provinces("NT") == {"Northwest Territories"}
    assert await provinces("NL") == {nl}
    assert await provinces("yt") == {"Yukon"}
    assert await provinces("48") == {"Alberta"}
    assert await provinces("10") == {nl}
    assert await provinces("Terre-Neuve-et-Labrador") == {nl}
    assert await provinces("Territoires du Nord-Ouest") == {"Northwest Territories"}
    assert await provinces("Alberta") == {"Alberta"}


# Candidates whose surnames are words of a party's name, in a province the fixture lacks.
_LOOKALIKES = (
    '"Alberta/Alberta","Calgary Centre","48001","Gail Greenwood Liberal/Libéral",'
    '"Calgary, Alta./Alb.","Teacher/Enseignant",100,50,10,5\r\n'
    '"Alberta/Alberta","Calgary Centre","48001","Tim Green Liberal/Libéral",'
    '"Calgary, Alta./Alb.","Teacher/Enseignant",100,50,10,5\r\n'
)


async def test_party_filter_reads_the_party_not_the_candidates_name(httpx_mock):
    # The candidate cell holds the name and the party ("Tim Green Liberal/Libéral"), so a
    # party="Green" filter on the whole cell also returned every Green, Greene and
    # Greenwood who ran for another party.
    httpx_mock.add_response(
        url=_url(45, 12), content=_bytes("candidates_45.csv") + _LOOKALIKES.encode()
    )

    async def names(given: str) -> list[str]:
        result = await client.get_table(45, "candidates", party=given)
        return [r["Candidate/Candidat"] for r in result.rows]

    assert await names("Green") == ["Kaelem Tingate Green Party/Parti Vert"]
    assert len(await names("Liberal")) == 5
    assert len(await names("Libéral")) == 5
    assert len(await names("Conservative")) == 3
    # The French name of the party is searched too.
    assert await names("Parti Vert") == ["Kaelem Tingate Green Party/Parti Vert"]


async def test_party_filter_reads_the_elected_candidate_cell(httpx_mock):
    greenwood = (
        '"Alberta/Alberta","Calgary Centre",48001,100000,80000,200,50000,99,500,1,50500,63,'
        '"Greenwood, Gail Liberal/Libéral"\r\n'
    )
    httpx_mock.add_response(
        url=_url(45, 11), content=_bytes("district_45.csv") + greenwood.encode()
    )
    green = await client.get_table(45, "district_results", party="Green")
    assert green.total_rows == 0
    liberal = await client.get_table(45, "district_results", party="Liberal")
    assert {r["Electoral District Name/Nom de circonscription"] for r in liberal.rows} == {
        "Avalon",
        "Cape Spear",
        "Labrador",
        "Calgary Centre",
    }
