"""MCP tools for Corporations Canada's federal corporation lookup API."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ised.corporations import client
from maple_data_mcp.modules.ised.corporations.schemas import CorporationDetail

Lang = Literal["en", "fr"]


@tool
async def ised_corporations_get_corporation(
    id_or_business_number: str, lang: Lang = "en"
) -> CorporationDetail:
    """Look up one federal corporation by its Corporations Canada id or business number.

    Use for: getting a federal (not provincial) corporation's current
    status, legal/operating names, registered addresses, director
    limits, annual-return filing history, and incorporation/by-law
    activities, given its numeric corporation id or 9-digit business
    number (as found in another dataset or a filing). This is a
    single-record lookup, not a name search -- there is no documented
    endpoint to search by corporation name. Keywords: Corporations
    Canada, ISED, ISDE, federal corporation, business number, BN,
    corporate registry, director, annual return, incorporation,
    by-laws, company status.
    Mots-clés : Corporations Canada, ISDE, société fédérale, numéro
    d'entreprise, NE, registre des sociétés, administrateur, rapport
    annuel, incorporation, règlements, statut de l'entreprise.
    """
    return await client.get_corporation(id_or_business_number, lang)
