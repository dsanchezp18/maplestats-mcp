"""Tests for the House of Commons open data client against feeds saved 2026-09-30.

roles_89156.xml and roles_9.xml are live member role feeds (a sitting MP and a
former member from 1997 to 2002) unchanged; standings_en.xml and
standings_fr.xml are the live party standings; members_en.xml and
ministry_en.xml keep the first 12 and 6 entries of the live feeds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.ourcommons import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_members_filter_by_province_and_party_accent_insensitive(httpx_mock):
    httpx_mock.add_response(
        url=constants.MEMBERS_URL.format(lang="en"), content=_bytes("members_en.xml")
    )
    everyone = await client.list_members(limit=100)
    assert everyone.total_members == 12 and not everyone.truncated
    first = everyone.members[0]
    assert (first.person_id, first.last_name) == (89156, "Aboultaif")
    assert first.constituency == "Edmonton Manning" and first.province == "Alberta"
    assert first.elected and first.elected.year == 2025

    alberta = await client.list_members(province="ALBERTA")
    assert alberta.total_members >= 1
    assert all(m.province == "Alberta" for m in alberta.members)
    assert (await client.list_members(party="conservative")).total_members >= 1
    assert (await client.list_members(name="ziad aboultaif")).total_members == 1


async def test_members_filters_accept_english_names_on_the_french_feed(httpx_mock):
    # members_fr.xml keeps 12 entries of the live French feed (2026-10-03):
    # 5 "NPD", 1 "Parti vert", 6 in "Colombie-Britannique". Before, party="NDP"
    # with lang="fr" matched 0.
    httpx_mock.add_response(
        url=constants.MEMBERS_URL.format(lang="fr"),
        content=_bytes("members_fr.xml"),
        is_reusable=True,
    )
    ndp = await client.list_members(party="NDP", lang="fr")
    assert ndp.total_members == 5 and {m.party for m in ndp.members} == {"NPD"}
    assert (await client.list_members(party="New Democratic Party", lang="fr")).total_members == 5
    green = await client.list_members(party="Green Party", lang="fr")
    assert [m.party for m in green.members] == ["Parti vert"]
    bc = await client.list_members(province="British Columbia", lang="fr")
    assert bc.total_members == 6 and {m.province for m in bc.members} == {"Colombie-Britannique"}
    assert (await client.list_members(province="bc", party="ndp", lang="fr")).total_members == 3
    assert (await client.list_members(party="Liberal", lang="fr")).total_members == 2


async def test_members_filters_accept_french_names_on_the_english_feed(httpx_mock):
    httpx_mock.add_response(
        url=constants.MEMBERS_URL.format(lang="en"),
        content=_bytes("members_en.xml"),
        is_reusable=True,
    )
    everyone = await client.list_members(limit=100)
    conservatives = await client.list_members(party="Conservateur")
    assert conservatives.total_members == sum(m.party == "Conservative" for m in everyone.members)
    assert conservatives.total_members >= 1
    alberta = await client.list_members(province="AB")
    assert alberta.total_members == sum(m.province == "Alberta" for m in everyone.members)
    # A plain substring still narrows as before ("Party" is only "Green Party").
    assert (await client.list_members(party="Party")).total_members == sum(
        m.party == "Green Party" for m in everyone.members
    )


async def test_members_limit_truncates(httpx_mock):
    httpx_mock.add_response(
        url=constants.MEMBERS_URL.format(lang="en"), content=_bytes("members_en.xml")
    )
    result = await client.list_members(limit=2)
    assert len(result.members) == 2 and result.truncated and result.total_members == 12
    assert result.provenance.limits


async def test_roles_for_a_sitting_member(httpx_mock):
    url = constants.ROLES_URL.format(lang="en", person_id=89156)
    httpx_mock.add_response(url=url, content=_bytes("roles_89156.xml"))
    roles = await client.get_member_roles(89156)
    assert (roles.first_name, roles.last_name) == ("Ziad", "Aboultaif")
    assert roles.seats[0].constituency == "Edmonton Manning" and roles.seats[0].end is None
    assert roles.committee_roles[0].committee == "Foreign Affairs and International Development"
    assert len(roles.associations) == 74
    assert [
        (e.election_date.year if e.election_date else None, e.result)
        for e in roles.election_history
    ][:2] == [
        (2025, "Re-Elected"),
        (2021, "Re-Elected"),
    ]
    assert roles.election_history[-1].result == "Elected"
    assert roles.provenance.url == url


async def test_roles_for_a_former_member(httpx_mock):
    url = constants.ROLES_URL.format(lang="en", person_id=9)
    httpx_mock.add_response(url=url, content=_bytes("roles_9.xml"))
    roles = await client.get_member_roles(9)
    assert roles.last_name == "Baker" and len(roles.seats) == 2
    end, start = roles.seats[0].end, roles.seats[1].start
    assert end and end.year == 2002 and start and start.year == 1997
    position = roles.parliamentary_positions[0]
    assert position.title.startswith("Secretary of State")
    assert position.start and position.start.year == 1999


async def test_unknown_person_id_is_not_found(httpx_mock):
    url = constants.ROLES_URL.format(lang="en", person_id=2500)
    httpx_mock.add_response(url=url, status_code=302, headers={"location": "/error"})
    with pytest.raises(NotFound):
        await client.get_member_roles(2500)


async def test_invalid_inputs():
    with pytest.raises(InvalidInput):
        await client.get_member_roles(0)
    with pytest.raises(InvalidInput):
        await client.list_members(lang="de")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.list_members(limit=0)


async def test_party_standings_totals(httpx_mock):
    httpx_mock.add_response(
        url=constants.STANDINGS_URL.format(lang="en"), content=_bytes("standings_en.xml")
    )
    standings = await client.get_party_standings()
    assert standings.total_seats == 343
    assert standings.by_party[0].party == "Liberal"
    assert sum(t.seats for t in standings.by_party) == 343
    assert any(r.province == "Alberta" and r.party == "Conservative" for r in standings.by_province)


async def test_party_standings_in_french(httpx_mock):
    httpx_mock.add_response(
        url=constants.STANDINGS_URL.format(lang="fr"), content=_bytes("standings_fr.xml")
    )
    standings = await client.get_party_standings(lang="fr")
    assert "Libéral" in {t.party for t in standings.by_party}


async def test_ministry_in_precedence_order(httpx_mock):
    httpx_mock.add_response(
        url=constants.MINISTRY_URL.format(lang="en"), content=_bytes("ministry_en.xml")
    )
    ministry = await client.get_ministry()
    assert len(ministry.ministers) == 6
    first = ministry.ministers[0]
    assert first.title == "Prime Minister" and first.order_of_precedence == 1
    assert first.honorific == "Right Hon."
    orders = [m.order_of_precedence for m in ministry.ministers]
    assert orders == sorted(orders)
