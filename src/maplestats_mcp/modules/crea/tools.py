"""MCP tools for CREA's MLS® Home Price Index (links and terms only)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.crea import client
from maplestats_mcp.modules.crea.schemas import CreaHpiLinks

Lang = Literal["en", "fr"]


@tool
async def crea_get_hpi_links(lang: Lang = "en") -> CreaHpiLinks:
    """Where to get The Canadian Real Estate Association's (CREA) MLS® Home
    Price Index and national resale statistics yourself, and the terms that
    apply. Returns no CREA values: CREA's terms allow downloading for
    private, non-commercial analysis, but publishing or displaying the
    content needs CREA's prior written consent, and commercial use is
    forbidden.

    Returns the current monthly MLS® HPI zip URL (confirmed by a HEAD
    request, never downloaded; the HPI tool page when not confirmed), the
    HPI tool, national statistics, quarterly forecasts and housing market
    snapshot pages, the release timing (monthly, around the 15th), the
    attribution line to use, a plain summary of the terms, and open
    alternatives that measure something different: Statistics Canada's New
    Housing Price Index (table 18-10-0205-01) and CHSP sale prices
    (46-10-0030-01) through wds_ tools, CMHC housing starts through cmhc_.
    Use for: MLS home price index download, CREA resale house prices and
    benchmark prices, how to cite CREA, whether CREA data can be published,
    open substitutes for home prices.
    Keywords: CREA, MLS, home price index, HPI, benchmark price, resale,
    house prices, real estate, home sales, housing market, attribution,
    terms of use.
    Mots-clés : Association canadienne de l'immeuble (ACI), MLS, indice des
    prix des propriétés, IPP, prix de référence, revente, prix des maisons,
    immobilier, ventes de maisons, marché de l'habitation, courtiers
    immobiliers, conditions d'utilisation.
    """
    return await client.get_hpi_links(lang=lang)
