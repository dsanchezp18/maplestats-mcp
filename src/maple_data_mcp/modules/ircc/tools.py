"""MCP tools for IRCC's Express Entry rounds-of-invitations feed."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ircc import client
from maple_data_mcp.modules.ircc.constants import ROUNDS_LIMIT_DEFAULT
from maple_data_mcp.modules.ircc.schemas import ExpressEntryRoundDetail, ExpressEntryRoundsResult

Lang = Literal["en", "fr"]


@tool
async def ircc_list_express_entry_rounds(
    program: str | None = None,
    since: date | None = None,
    limit: int = ROUNDS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> ExpressEntryRoundsResult:
    """List Express Entry rounds of invitations, newest first.

    Use for: tracking CRS (Comprehensive Ranking System) cutoff score
    history, invitations issued per round, and candidate-pool score
    distribution over time. `program` filters by a case-insensitive
    substring match against the round's name and invited program(s), e.g.
    "Canadian Experience Class" or "Provincial Nominee". `since` (an
    ISO date) filters to rounds on or after that date. The upstream feed
    has no server-side filtering, so MapleData fetches the full history
    once (cached for hours, since new rounds appear roughly weekly) and
    filters/limits locally. Keywords: Express Entry, rounds of
    invitations, CRS, Comprehensive Ranking System, cutoff score, draw,
    invitations issued, immigration, permanent residence, Canadian
    Experience Class, Federal Skilled Worker, Provincial Nominee Program,
    category-based selection, IRCC.
    Mots-clés: Entrée express, rondes d'invitations, SCG, système de
    classement global, score limite, tirage, invitations émises,
    immigration, résidence permanente, catégorie de l'expérience
    canadienne, travailleurs qualifiés, programme des candidats des
    provinces, sélection fondée sur les catégories, IRCC.
    """
    return await client.list_express_entry_rounds(program, since, limit, lang)


@tool
async def ircc_get_express_entry_round(
    draw_number: str, lang: Lang = "en"
) -> ExpressEntryRoundDetail:
    """Get one Express Entry round of invitations by its draw number.

    Use for: looking up a specific round found with
    ircc_list_express_entry_rounds, or a round number a user already
    knows. `draw_number` is a string, not an int: most rounds are plain
    numbers ("444"), but two rounds IRCC ran on the same day
    (2018-05-30) are published as "91a" and "91b" rather than separate
    sequential numbers. Keywords: Express Entry, round, draw number,
    invitation, CRS cutoff, immigration, permanent residence, IRCC.
    Mots-clés: Entrée express, ronde, numéro de tirage, invitation,
    score limite SCG, immigration, résidence permanente, IRCC.
    """
    return await client.get_express_entry_round(draw_number, lang)


@tool
async def ircc_get_latest_express_entry_round(lang: Lang = "en") -> ExpressEntryRoundDetail:
    """Get the most recent Express Entry round of invitations.

    Use for: answering "what is the current CRS cutoff score" or "when
    was the last Express Entry draw" without knowing a draw number.
    Keywords: Express Entry, latest round, current CRS cutoff, most
    recent draw, today, this week, immigration, permanent residence,
    IRCC.
    Mots-clés: Entrée express, dernière ronde, score limite SCG actuel,
    tirage le plus récent, aujourd'hui, cette semaine, immigration,
    résidence permanente, IRCC.
    """
    return await client.get_latest_express_entry_round(lang)
