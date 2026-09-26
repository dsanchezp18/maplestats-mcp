"""MCP tools for Competition Bureau merger reviews."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.competition_bureau import client, constants
from maplestats_mcp.modules.competition_bureau.schemas import MergerSearchResult, Outcome

Lang = Literal["en", "fr"]


@tool
async def competition_bureau_search_mergers(
    party: str = "",
    naics: str | None = None,
    outcome: Outcome | None = None,
    concluded_from: str | None = None,
    concluded_to: str | None = None,
    include_ongoing: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> MergerSearchResult:
    """Search Competition Bureau Canada merger reviews, 2015 to this week.

    Use for: which mergers and acquisitions the Competition Bureau
    reviewed and how each ended: advance ruling certificate (ARC), no
    action letter (NAL), consent agreement (CA), judicial decision (JD),
    abandoned (TA), other, or still ongoing. Filter by party name (every
    word must appear), NAICS industry prefix (e.g. '2111' oil and gas
    extraction, '52' finance), outcome, and concluded month range
    (YYYY-MM). Covers the weekly report (reviews opened since November
    2023, with opened and concluded dates) and the archived report
    (concluded January 2015 to April 2023, month only). Returns newest
    first, with outcome counts for all matches. Not every merger: parties
    may ask to keep one off the report, and May-October 2023 is missing.
    lang sets the outcome labels.
    Keywords: merger review, acquisition, Competition Bureau, antitrust,
    competition law, advance ruling certificate, no action letter,
    consent agreement, NAICS, M&A, concentration.
    Mots-clés : examen de fusion, acquisition, Bureau de la concurrence,
    droit de la concurrence, certificat de décision préalable, lettre de
    non-intervention, consentement, SCIAN, fusions et acquisitions.
    """
    return await client.search_mergers(
        party,
        naics=naics,
        outcome=outcome,
        concluded_from=concluded_from,
        concluded_to=concluded_to,
        include_ongoing=include_ongoing,
        limit=limit,
        lang=lang,
    )
