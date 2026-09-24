"""MCP tools for House of Commons data from OpenParliament.ca."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.openparliament import client, constants
from maple_data_mcp.modules.openparliament.schemas import (
    Bill,
    BillSearchResult,
    Politician,
    PoliticianSearchResult,
    SpeechSearchResult,
    Vote,
    VoteSearchResult,
)


@tool
async def parliament_search_bills(
    keyword: str | None = None,
    session: str | None = None,
    sponsor: str | None = None,
    private_member: bool | None = None,
    introduced_from: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> BillSearchResult:
    """Search House of Commons and Senate bills in one parliamentary session.

    Use for: finding bills by a word in the title or by number (e.g.
    "housing", "C-2"), bills sponsored by an MP (sponsor slug from
    parliament_search_politicians), private members' bills, or bills
    introduced since a date. session is like '45-1' (default: the
    current session). Newest first. Source is OpenParliament.ca
    (unofficial). Follow up with parliament_get_bill.
    Keywords: bill, legislation, House of Commons, Parliament, LEGISinfo,
    private member's bill, government bill, Senate bill, act.
    Mots-clés : projet de loi, législation, Chambre des communes,
    Parlement, LEGISinfo, projet de loi émanant d'un député, loi, Sénat.
    """
    return await client.search_bills(
        session=session,
        keyword=keyword,
        sponsor=sponsor,
        private_member=private_member,
        introduced_from=introduced_from,
        lang=lang,
        limit=limit,
    )


@tool
async def parliament_get_bill(session: str, number: str, lang: Literal["en", "fr"] = "en") -> Bill:
    """Get one bill's status, sponsor, short title, text link and recorded votes.

    Use for: where a bill stands (e.g. second reading, royal assent),
    who sponsored it, whether it became law, and every House vote on it.
    session like '45-1', number like 'C-2'.
    Keywords: bill status, reading, royal assent, sponsor, LEGISinfo,
    legislation, House vote, Parliament.
    Mots-clés : état du projet de loi, lecture, sanction royale,
    parrain, LEGISinfo, législation, vote, Parlement.
    """
    return await client.get_bill(session, number, lang=lang)


@tool
async def parliament_search_votes(
    session: str | None = None,
    bill: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    result: Literal["Passed", "Failed", "Tie"] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> VoteSearchResult:
    """List recorded (division) votes in the House of Commons, newest first.

    Use for: recent votes, votes in a session or date range (YYYY-MM-DD),
    votes on one bill (session and bill), and passed or failed motions,
    with yea/nay totals. Use parliament_get_vote for party and MP ballots.
    Keywords: vote, division, recorded vote, House of Commons, motion,
    yeas, nays, Parliament, roll call.
    Mots-clés : vote, vote par appel nominal, Chambre des communes,
    motion, pour, contre, Parlement, scrutin.
    """
    return await client.search_votes(
        session=session,
        bill=bill,
        date_from=date_from,
        date_to=date_to,
        result=result,
        lang=lang,
        limit=limit,
    )


@tool
async def parliament_get_vote(
    session: str,
    number: int,
    include_ballots: bool = False,
    lang: Literal["en", "fr"] = "en",
) -> Vote:
    """Get one House of Commons vote with how each party voted.

    Use for: party positions on a vote and, with include_ballots, how
    every MP voted (MP slugs). session like '45-1', number is the vote
    number from parliament_search_votes.
    Keywords: vote breakdown, party vote, ballot, how did MPs vote,
    division, House of Commons, dissent.
    Mots-clés : résultat du vote, vote des partis, vote des députés,
    appel nominal, Chambre des communes, dissidence.
    """
    return await client.get_vote(session, number, include_ballots=include_ballots, lang=lang)


@tool
async def parliament_search_politicians(
    name: str | None = None,
    province: str | None = None,
    party: str | None = None,
    include_former: bool = False,
    limit: int = constants.LIMIT_DEFAULT,
) -> PoliticianSearchResult:
    """Find Members of Parliament by name, province (e.g. 'AB') or party.

    Use for: current MPs, their party and riding, and the slug other
    parliament_ tools take. include_former adds past MPs (name only).
    Keywords: MP, member of Parliament, riding, constituency, House of
    Commons, party, caucus, politician.
    Mots-clés : député, députée, circonscription, Chambre des communes,
    parti, caucus, élu, parlementaire.
    """
    return await client.search_politicians(
        name=name, province=province, party=party, include_former=include_former, limit=limit
    )


@tool
async def parliament_get_politician(slug: str, lang: Literal["en", "fr"] = "en") -> Politician:
    """Get an MP's contact details and party and riding history.

    Use for: an MP's email, phone, ourcommons.ca page and every term
    (party, riding, dates). slug like 'ziad-aboultaif'.
    Keywords: MP profile, contact, email, riding history, party history,
    member of Parliament, term.
    Mots-clés : profil du député, coordonnées, courriel, circonscription,
    historique, parti, mandat.
    """
    return await client.get_politician(slug, lang=lang)


@tool
async def parliament_search_speeches(
    politician: str | None = None,
    debate_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> SpeechSearchResult:
    """Read Hansard and committee speeches by MP, sitting day or date range.

    Use for: what an MP said in the House or in committee (politician
    slug), the full debate of one sitting (debate_date, YYYY-MM-DD), or
    speeches between dates. Text is plain, in English or French.
    Keywords: Hansard, debate, speech, question period, committee
    evidence, transcript, House of Commons, said.
    Mots-clés : hansard, débats, intervention, période des questions,
    témoignages en comité, transcription, Chambre des communes.
    """
    return await client.search_speeches(
        politician=politician,
        debate_date=debate_date,
        date_from=date_from,
        date_to=date_to,
        lang=lang,
        limit=limit,
    )
