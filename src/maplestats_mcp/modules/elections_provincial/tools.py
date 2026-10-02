"""MCP tools for provincial general election results (Quebec, Alberta, British Columbia)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.elections_provincial import client, constants
from maplestats_mcp.modules.elections_provincial.schemas import (
    ElectionList,
    ElectionResults,
    ProvinceCode,
    SeatSummary,
)

Lang = Literal["en", "fr"]


@tool
async def elections_provincial_list_elections(
    province: str | None = None, lang: Lang = "en"
) -> ElectionList:
    """List the provincial general elections with results here (Quebec, Alberta, British Columbia).

    Use for: seeing which provincial general elections can be read (Quebec 1973 to
    2022, Alberta 2008 to 2023, British Columbia 2005 to 2024), with polling day,
    seats, what each row holds, and which provinces are not available and why
    (Ontario: Elections Ontario's terms forbid scraping). No upstream call is made.
    Keywords: provincial election, general election, results, Quebec, Alberta,
    British Columbia, Ontario, Elections Quebec, Elections Alberta, Elections BC,
    legislature, riding, electoral district, MLA, MNA.
    Mots-clés : élection provinciale, élections générales, résultats, Québec,
    Alberta, Colombie-Britannique, Ontario, Élections Québec, circonscription,
    division électorale, député, Assemblée nationale, scrutin.
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
    """Get provincial general election results by electoral district (Quebec, Alberta, BC).

    Use for: who won a provincial riding (winners_only), every candidate's votes
    and share in a district (Quebec and British Columbia), votes by party in an
    Alberta electoral division (the winner is named), district electors,
    turnout and rejected ballots where published. `province` is qc, ab or bc;
    `election` is the polling day (2022-10-03) or just its year (2022), and
    defaults to the latest. `district` (name or number or code), `party` (name or
    abbreviation, e.g. CAQ, UCP, NDP) and `candidate` are accent-insensitive
    substring filters. Ontario is not available. By-elections are not included.
    Keywords: provincial election results, riding, electoral district,
    candidate, votes, winner, elected, MLA, MNA, party, CAQ, Parti Quebecois,
    Liberal, UCP, NDP, BC NDP, Quebec, Alberta, British Columbia.
    Mots-clés : résultats électoraux provinciaux, circonscription, candidat,
    votes, gagnant, élu, député, parti, CAQ, Parti québécois, libéral, Québec
    solidaire, Québec, Alberta, Colombie-Britannique.
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
    """Get seats and votes by party for one provincial general election (Quebec, Alberta, BC).

    Use for: the seat count and popular vote of each party in a provincial
    election (for example the CAQ's 90 of 125 Quebec seats in 2022, the UCP's 49
    of 87 in Alberta in 2023, the BC NDP's 47 of 93 in 2024), computed from the
    district results, with candidates per party and share of valid votes.
    `province` is qc, ab or bc; `election` is the polling day or its year, and
    defaults to the latest.
    Keywords: seats by party, popular vote, vote share, election outcome,
    legislature, majority, minority, provincial election, Quebec, Alberta,
    British Columbia, seat count.
    Mots-clés : sièges par parti, vote populaire, part des votes, résultat
    électoral, législature, majorité, minorité, élection provinciale, Québec,
    Alberta, Colombie-Britannique, nombre de sièges.
    """
    return await client.get_seats(province=province, election=election)
