"""MCP tools for the Canadian Trademarks Database (CIPO) search API."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ised.cipo import client, constants
from maplestats_mcp.modules.ised.cipo.schemas import TrademarkSearchResult

Lang = Literal["en", "fr"]

SearchField = Literal[
    "all",
    "trademark",
    "trademark_description",
    "owner_name",
    "old_owner_name",
    "goods",
    "services",
    "application_number",
    "original_application_number",
    "registration_number",
    "international_registration_number",
    "nice_classification",
    "cipo_status",
    "disclaimer",
    "vienna_code",
    "vienna_description",
]


@tool
async def ised_cipo_search_trademarks(
    search_field: SearchField,
    criteria: str = "",
    max_return: int = constants.MAX_RETURN_DEFAULT,
    lang: Lang = "en",
) -> TrademarkSearchResult:
    """Search the Canadian Trademarks Database (CIPO) by one field.

    Use for: finding registered/pending/expunged/abandoned Canadian
    trademarks by owner name, mark text, goods/services description,
    application or registration number, Nice classification, Vienna
    design-code, or CIPO status. Returns application number, mark name
    and type, current status, Nice classes, and any logo image URLs. An
    empty criteria is a deliberate match-all against the entire register
    (over 2 million records). Results are ranked by the upstream API and
    max_return only caps how many top-ranked matches come back in one
    call -- there is no way to page past that count. The search API
    answers in English only (status and mark-type labels), confirmed
    live 2026-09-23, so `lang` has no effect. Keywords: CIPO,
    ISED, trademark, brand, mark, owner, applicant, Nice classification,
    Vienna code, trademark status, registered, abandoned, expunged.
    Mots-clés : OPIC, ISDE, recherche de marques de commerce, marque de
    commerce, marque, propriétaire,
    demandeur, classification de Nice, code de Vienne, statut de la
    marque, enregistrée, abandonnée, radiée.
    """
    del lang
    return await client.search_trademarks(search_field, criteria, max_return=max_return)
