"""MCP tools for Senate of Canada recorded votes."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.senate import client
from maple_data_mcp.modules.senate.schemas import SenateVote, SenateVoteList


@tool
async def senate_list_votes(
    session: str | None = None,
    keyword: str | None = None,
    bill: str | None = None,
    limit: int = 50,
    lang: Literal["en", "fr"] = "en",
) -> SenateVoteList:
    """List recorded votes in the Senate of Canada for one session, newest first.

    Use for: Senate votes on a bill (bill like 'C-6' or 'S-205'), votes
    whose title contains a word, or all votes in a session (like '45-1',
    default current; sessions from 42-1), with yeas, nays, abstentions
    and result. House of Commons votes are parliament_search_votes.
    Keywords: Senate vote, senators, recorded division, Senate of Canada,
    upper chamber, third reading, bill, adopted.
    Mots-clés : vote au Sénat, sénateurs, appel nominal, Sénat du Canada,
    chambre haute, troisième lecture, projet de loi, adopté.
    """
    return await client.list_votes(
        session=session, keyword=keyword, bill=bill, lang=lang, limit=limit
    )


@tool
async def senate_get_vote(
    vote_id: int, session: str, lang: Literal["en", "fr"] = "en"
) -> SenateVote:
    """Get how each senator voted on one Senate vote.

    Use for: every senator's yea, nay or abstention, with their group
    (ISG, CSG, PSG, Conservative) and province. vote_id and session come
    from senate_list_votes.
    Keywords: senator vote, Senate ballot, how did senators vote, Senate
    group, ISG, CSG, PSG, abstention.
    Mots-clés : vote des sénateurs, Sénat, groupe sénatorial, abstention,
    appel nominal, GSI, GSC, GPS.
    """
    return await client.get_vote(vote_id, session, lang=lang)
