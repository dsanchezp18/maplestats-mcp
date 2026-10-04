"""MCP tools for provincial general election results (QC, AB, BC, SK, MB)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.elections_provincial import client, constants
from maplestats_mcp.modules.elections_provincial.schemas import (
    ElectionList,
    ElectionResults,
    ProvinceCode,
    SeatSummary,
    VotingAreaResults,
)

Lang = Literal["en", "fr"]


@tool
async def elections_provincial_list_elections(
    province: ProvinceCode | None = None, lang: Lang = "en"
) -> ElectionList:
    """List the provincial general elections with results here (QC, AB, BC, SK, Manitoba).

    Use for: seeing which provincial general elections can be read (Quebec 1973 to
    2022, Alberta 2008 to 2023, British Columbia 2005 to 2024, Saskatchewan 2011 to
    2024, Manitoba 1999 to 2023), with polling day, seats, what each row holds, and
    which provinces are not available and why (Ontario: Elections Ontario's terms
    forbid scraping). No upstream call is made.
    Keywords: provincial election, general election, results, Quebec, Alberta,
    British Columbia, Saskatchewan, Manitoba, Ontario, Elections Quebec, Elections
    Alberta, Elections BC, Elections Saskatchewan, Elections Manitoba, legislature,
    riding, electoral district, electoral division, MLA, MNA.
    Mots-clés : élection provinciale, élections générales, résultats, Québec,
    Alberta, Colombie-Britannique, Saskatchewan, Manitoba, Ontario, Élections Québec,
    circonscription, division électorale, député, Assemblée nationale, scrutin.
    """
    return client.list_elections(province, lang)


@tool
async def elections_provincial_get_results(
    province: ProvinceCode,
    election: str | None = None,
    district: str | None = None,
    party: str | None = None,
    candidate: str | None = None,
    winners_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ElectionResults:
    """Get provincial general election results by electoral district (QC, AB, BC, SK, MB).

    Use for: who won a provincial riding (winners_only), every candidate's votes
    and share in a district (Quebec, British Columbia, Saskatchewan, Manitoba), votes
    by party in an Alberta electoral division (the winner is named), district
    electors, turnout and rejected ballots where published. `province` is qc, ab,
    bc, sk or mb; `election` is the polling day (2022-10-03) or just its year
    (2022), and defaults to the latest. `district` (name or number or code), `party`
    (name or abbreviation, e.g. CAQ, UCP, NDP, PC) and `candidate` are
    accent-insensitive substring filters. Ontario is not available. By-elections
    are not included. `lang` changes nothing here: district, party and
    candidate names are given as each source publishes them.
    Keywords: provincial election results, riding, electoral district,
    electoral division, candidate, votes, winner, elected, MLA, MNA, party, CAQ,
    Parti Quebecois, Liberal, UCP, NDP, BC NDP, Saskatchewan Party, Sask Party,
    Progressive Conservative, Manitoba NDP, Saskatchewan, Manitoba, Quebec,
    Alberta, British Columbia.
    Mots-clés : résultats électoraux provinciaux, circonscription, candidat,
    votes, gagnant, élu, député, parti, CAQ, Parti québécois, libéral, Québec
    solidaire, Saskatchewan Party, progressiste-conservateur, Saskatchewan,
    Manitoba, Québec, Alberta, Colombie-Britannique.
    """
    return await client.get_results(
        province=province,
        election=election,
        district=district,
        party=party,
        candidate=candidate,
        winners_only=winners_only,
        limit=limit,
        offset=offset,
    )


@tool
async def elections_provincial_get_seats(
    province: ProvinceCode,
    election: str | None = None,
    lang: Lang = "en",
) -> SeatSummary:
    """Get seats and votes by party for one provincial general election (QC, AB, BC, SK, MB).

    Use for: the seat count and popular vote of each party in a provincial
    election (for example the CAQ's 90 of 125 Quebec seats in 2022, the UCP's 49
    of 87 in Alberta in 2023, the BC NDP's 47 of 93 in 2024, the Saskatchewan
    Party's 34 of 61 in 2024, the Manitoba NDP's 34 of 57 in 2023), computed from
    the district results, with candidates per party and share of valid votes.
    `province` is qc, ab, bc, sk or mb; `election` is the polling day or its year,
    and defaults to the latest. `lang` changes nothing here: party names are
    given as each source publishes them.
    Keywords: seats by party, popular vote, vote share, election outcome,
    legislature, majority, minority, provincial election, Quebec, Alberta,
    British Columbia, Saskatchewan, Manitoba, seat count.
    Mots-clés : sièges par parti, vote populaire, part des votes, résultat
    électoral, législature, majorité, minorité, élection provinciale, Québec,
    Alberta, Colombie-Britannique, Saskatchewan, Manitoba, nombre de sièges.
    """
    return await client.get_seats(province=province, election=election)


@tool
async def elections_provincial_get_voting_areas(
    district: str,
    province: ProvinceCode = "mb",
    election: str | None = None,
    voting_area: str | None = None,
    party: str | None = None,
    candidate: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> VotingAreaResults:
    """Get poll-by-poll results by voting area in one Manitoba electoral division.

    Use for: every candidate's votes in each voting area (poll) of a Manitoba
    electoral division, with the polling place, registered voters, rejected and
    declined ballots per area, and the advance, absentee, homebound and write-in
    polls, for the general elections of 1999 to 2023 (Elections Manitoba's
    statements of votes by voting area). `district` names one division (an
    accent-insensitive substring such as "fort rouge"); `election` is the polling
    day or its year and defaults to 2023; `voting_area` (e.g. 12 or Adv-1),
    `party` and `candidate` filter the rows. The response compares the areas' sum
    with the division's official total, which differs for a few divisions.
    `lang` changes nothing here (names are as Elections Manitoba publishes them).
    Keywords: poll by poll results, voting area, polling division, poll,
    polling station, advance poll, Manitoba election, Elections Manitoba,
    electoral division, neighbourhood vote, precinct results, MLA.
    Mots-clés : résultats par bureau de vote, section de vote, bureau de scrutin,
    vote par anticipation, élection manitobaine, Élections Manitoba,
    circonscription, division électorale, résultats détaillés, député.
    """
    return await client.get_voting_areas(
        province=province,
        district=district,
        election=election,
        voting_area=voting_area,
        party=party,
        candidate=candidate,
        limit=limit,
        offset=offset,
    )
