"""MCP tools for House of Commons open data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ourcommons import client, constants, expenditures
from maplestats_mcp.modules.ourcommons.schemas import (
    ExpenditureReports,
    MemberExpenditureDetails,
    MemberExpenditures,
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
    accent-insensitive substring matches: `province` (e.g. Alberta, British
    Columbia or Colombie-Britannique, or a code such as BC),
    `party` (Liberal/Libéral, Conservative/Conservateur, Bloc Québécois,
    NDP/NPD, Green Party/Parti vert), `constituency` and `name`. Province
    and party work in English or French with either lang; results show the
    names in the feed's language. The official feed of sitting members.
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


@tool
async def ourcommons_list_expenditure_reports(lang: Lang = "en") -> ExpenditureReports:
    """List the House of Commons' quarterly Members' Expenditures Reports, newest first.

    Each report covers one fiscal quarter (fiscal_year 2027 is 2026-2027; quarter 1 is
    April to June). The reports run from 2020-2021 Q2; pass fiscal_year and quarter to
    ourcommons_get_member_expenditures or ourcommons_get_member_expenditure_details.
    Use for: which periods of MP spending are published, the latest quarter available.
    Keywords: MP expenses, Members' Expenditures Report, House of Commons, proactive
    disclosure, quarterly report, member spending, office budget, fiscal year.
    Mots-clés : dépenses des députés, Rapport sur les dépenses des membres, Chambre des
    communes, divulgation proactive, rapport trimestriel, budget de bureau, exercice
    financier, frais des députés.
    """
    return await expenditures.list_expenditure_reports(lang=lang)


@tool
async def ourcommons_get_member_expenditures(
    fiscal_year: int | None = None,
    quarter: int | None = None,
    name: str | None = None,
    constituency: str | None = None,
    caucus: str | None = None,
    sort_by: Literal["total", "salaries", "travel", "hospitality", "contracts", "name"] = "total",
    limit: int = constants.EXPENDITURES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> MemberExpenditures:
    """MPs' spending in one quarter from the House of Commons Members' Expenditures
    Report: salaries of staff, travel, hospitality and contracts (leases, advertising,
    office operations), in dollars, per member, with totals over the matches.

    Leave fiscal_year and quarter out for the latest report (fiscal_year 2027 is
    2026-2027, quarter 1 is April to June). Filters are accent-insensitive substrings:
    name ("Last, First"), constituency, caucus (Liberal, Conservative, Bloc Québécois,
    NDP, Green, Independent, in English or French). sort_by orders largest first (name
    alphabetically). One quarter per call, no year-to-date. limit is 1-500.
    Use for: which MPs spent most on travel, an MP's office spending, spending by party,
    comparing members' budgets.
    Keywords: MP expenses, member spending, travel expenses, hospitality, contracts,
    office budget, House of Commons, proactive disclosure, Members' Expenditures Report,
    MP salaries.
    Mots-clés : dépenses des députés, frais de déplacement, frais d'accueil, contrats,
    budget de bureau, Chambre des communes, divulgation proactive, salaires du personnel,
    dépenses par parti.
    """
    return await expenditures.get_member_expenditures(
        fiscal_year, quarter, name, constituency, caucus, sort_by, limit, lang
    )


@tool
async def ourcommons_get_member_expenditure_details(
    name: str,
    constituency: str | None = None,
    fiscal_year: int | None = None,
    quarter: int | None = None,
    categories: list[Literal["travel", "hospitality", "contract"]] | None = None,
    lang: Lang = "en",
) -> MemberExpenditureDetails:
    """One MP's itemized expenses in one quarter: every trip (dates, from, places
    visited, purpose, traveller, transport, lodging, meals), hospitality event
    (date, place, attendees, purpose, supplier) and contract (supplier, description,
    date), with the category totals from the quarter's summary.

    name is a substring of "Last, First" that must match one member; add
    constituency when it matches several. Leave fiscal_year and quarter out for the
    latest report. categories picks travel, hospitality and/or contract (default all).
    Travel lines can predate the quarter (late claims) or be negative (corrections).
    Use for: where an MP travelled, who an MP paid for office rent or advertising,
    checking a member's hospitality spending.
    Keywords: MP travel expenses, itemized expenses, hospitality, suppliers, contracts,
    office lease, House of Commons, proactive disclosure, member spending, trips.
    Mots-clés : frais de déplacement d'un député, dépenses détaillées, frais d'accueil,
    fournisseurs, contrats, bail de bureau, Chambre des communes, divulgation proactive,
    voyages.
    """
    return await expenditures.get_member_expenditure_details(
        name, constituency, fiscal_year, quarter, list(categories) if categories else None, lang
    )
