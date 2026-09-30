"""MCP tools for federal general election results (Elections Canada)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.elections_results import client, constants, historical
from maplestats_mcp.modules.elections_results.schemas import ElectionList, ElectionTable, TableName

Lang = Literal["en", "fr"]


@tool
async def elections_results_list_elections(lang: Lang = "en") -> ElectionList:
    """List the federal general elections and result tables available (38th to 45th, 2004 to 2025).

    Use for: seeing which federal general elections have official results here
    (with polling dates), which tables exist (turnout, seats, votes by party,
    riding results, every candidate), and what is not covered (elections before
    2004, by-elections, poll-by-poll). No upstream call is made.
    Keywords: federal election, general election, results, Elections Canada,
    official voting results, 2025, 2021, 2019, 2015, vote, riding, turnout.
    Mots-clés : élection fédérale, élections générales, résultats, Élections
    Canada, résultats officiels du vote, circonscription, participation,
    scrutin.
    """
    return client.list_elections(lang)


@tool
async def elections_results_get_table(
    election: int,
    table: TableName,
    province: str | None = None,
    district: str | None = None,
    party: str | None = None,
    winners_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ElectionTable:
    """Get official federal election results from Elections Canada for one general election.

    Use for: who won a riding (table candidates with winners_only, or
    district_results for the elected candidate), every candidate's votes and
    share of votes in a riding, provincial turnout (turnout), seats by party
    and gender (seats), valid votes and vote share by party and province
    (votes_by_party, vote_share_by_party), and returning officers. `election` is
    the general election number (45 = April 28, 2025, 44 = 2021, 43 = 2019,
    42 = 2015, 41 = 2011, 40 = 2008, 39 = 2006, 38 = 2004). `province`,
    `district` (name in either language, or riding number) and `party` are
    accent-insensitive substring filters; a filter needs a matching column in
    that table. Rows are text exactly as published, in English and French.
    Keywords: election results, riding, electoral district, candidate, votes,
    winner, elected, MP, party, Liberal, Conservative, NDP, Bloc, Green,
    seats, turnout, federal, Elections Canada.
    Mots-clés : résultats électoraux, circonscription, candidat, votes, gagnant,
    élu, député, parti, libéral, conservateur, NPD, Bloc québécois, sièges,
    participation, fédéral, Élections Canada.
    """
    return await client.get_table(
        election=election,
        table=table,
        province=province,
        district=district,
        party=party,
        winners_only=winners_only,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def elections_results_get_historical(
    election: int | None = None,
    province: str | None = None,
    constituency: str | None = None,
    party: str | None = None,
    limit: int = historical.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> historical.HistoricalResult:
    """Get federal election results by riding for every general election since 1867 (1st to 42nd).

    Use for: historical federal results before 2004 (or to compare 1867 to
    2015): each riding's electors, ballots, rejected ballots, candidates,
    seats, and votes by party, largest first, with the party that led the
    vote. `election` is the general election number (1 = 1867, 20 = 1945,
    36 = 1997, 42 = 2015); leave it out to search every election.
    `province`, `constituency` (also matches the riding's older name) and
    `party` (a mnemonic such as Lib, C, NDP, BQ, or part of a party name)
    are accent-insensitive filters. Source: the Winer and Ferris data set on
    Scholars Portal Dataverse (CC0), which holds party totals, not candidate
    names, and ends in 2015; use elections_results_get_table for official
    Elections Canada results of the 38th to 45th.
    Keywords: historical election results, federal, Confederation, 1867,
    riding, constituency, party, Liberal, Conservative, CCF, Progressive
    Conservative, Social Credit, Bloc, votes, turnout, history.
    Mots-clés : résultats électoraux historiques, fédéral, Confédération,
    1867, circonscription, parti, libéral, conservateur, CCF, Crédit social,
    Bloc, votes, participation, histoire.
    """
    return await historical.get_historical(
        election=election,
        province=province,
        constituency=constituency,
        party=party,
        limit=limit,
        offset=offset,
    )
