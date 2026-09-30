"""MCP tools for House of Commons open data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ourcommons import client, constants
from maplestats_mcp.modules.ourcommons.schemas import (
    MemberList,
    MemberRoles,
    Ministry,
    PartyStandings,
)

Lang = Literal["en", "fr"]


@tool
async def ourcommons_list_members(
    province: str | None = None,
    party: str | None = None,
    constituency: str | None = None,
    name: str | None = None,
    limit: int = constants.MEMBERS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> MemberList:
    """List current Members of Parliament from the House of Commons, filtered by place, party or name.

    Use for: finding who represents a riding, all MPs of a party or province,
    or an MP's person id (needed by ourcommons_get_member_roles). Filters are
    accent-insensitive substring matches: `province` (e.g. Alberta),
    `party` (Liberal, Conservative, Bloc Québécois, NDP, Green Party),
    `constituency` and `name`. The official feed of sitting members.
    Keywords: Member of Parliament, MP, riding, constituency, House of Commons,
    party, caucus, representative, federal, who represents, ourcommons.
    Mots-clés : député, députée, circonscription, Chambre des communes, parti,
    caucus, représentant, fédéral, qui représente, ourcommons.
    """
    return await client.list_members(
        province=province,
        party=party,
        constituency=constituency,
        name=name,
        limit=limit,
        lang=lang,
    )


@tool
async def ourcommons_get_member_roles(person_id: int, lang: Lang = "en") -> MemberRoles:
    """Get one Member of Parliament's full record: seats, caucus, committees, positions and elections.

    Use for: an MP's career on the House of Commons record: every seat held
    with dates, party changes, parliamentary positions (Speaker, secretary,
    critic), committee memberships, parliamentary associations, and the
    election candidate history with results (Elected, Re-Elected, Defeated).
    `person_id` comes from ourcommons_list_members (or the id in a member's
    ourcommons.ca page address); former members work too, with history from
    the 1990s.
    Keywords: MP career, member roles, committee membership, election history,
    caucus, parliamentary secretary, Speaker, re-elected, defeated, person id.
    Mots-clés : carrière d'un député, rôles, comités, historique électoral,
    caucus, secrétaire parlementaire, président de la Chambre, réélu, défait.
    """
    return await client.get_member_roles(person_id=person_id, lang=lang)


@tool
async def ourcommons_get_party_standings(lang: Lang = "en") -> PartyStandings:
    """Get current party standings in the House of Commons, by party and by province or territory.

    Use for: seats held now by each party (Liberal, Conservative, Bloc,
    NDP, Green, independents), and how each province or territory's seats
    split between parties. Vacant seats appear as party 'Vacant'.
    Keywords: party standings, seats, House of Commons, current, Liberal,
    Conservative, majority, minority, province, distribution of seats.
    Mots-clés : répartition des sièges, partis, Chambre des communes, actuel,
    libéral, conservateur, majorité, minorité, province.
    """
    return await client.get_party_standings(lang=lang)


@tool
async def ourcommons_get_ministry(lang: Lang = "en") -> Ministry:
    """Get the current Ministry (federal Cabinet) in order of precedence, with titles and start dates.

    Use for: who is Prime Minister and which minister holds which portfolio
    now, with the date each took office and their province.
    Keywords: Cabinet, Ministry, ministers, Prime Minister, portfolio, order
    of precedence, federal government, minister of finance.
    Mots-clés : Conseil des ministres, ministère, ministres, premier ministre,
    portefeuille, ordre de préséance, gouvernement fédéral, ministre des Finances.
    """
    return await client.get_ministry(lang=lang)
