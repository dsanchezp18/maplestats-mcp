"""MCP tools for CIHI's Indicator Library."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cihi import client, constants
from maplestats_mcp.modules.cihi.schemas import (
    IndicatorData,
    IndicatorDetail,
    IndicatorSearchResult,
)

Lang = Literal["en", "fr"]


@tool
async def cihi_search_indicators(query: str = "", lang: Lang = "en") -> IndicatorSearchResult:
    """Search CIHI's Indicator Library of ~200 health-system indicators.

    Use for: finding an indicator's slug, e.g. "stroke mortality",
    "readmission", "wait times", "emergency department", "hospital
    stays", "public spending". Every word must appear in the English
    name; read French content with lang="fr" on the other cihi_ tools.
    Keywords: CIHI, health indicators, hospital, mortality, readmission,
    wait times, emergency department, health system performance.
    Mots-clés : ICIS, indicateurs de santé, hôpital, mortalité,
    réadmission, temps d'attente, urgences, rendement du système de santé.
    """
    del lang
    return await client.search_indicators(query)


@tool
async def cihi_get_indicator(indicator: str, lang: Lang = "en") -> IndicatorDetail:
    """Get a CIHI indicator's description, data availability, update date, and topics.

    Use for: understanding what an indicator measures and which years
    and places it covers before reading its data. `indicator` is a slug
    from cihi_search_indicators; `lang="fr"` returns the French page.
    Keywords: CIHI, indicator definition, methodology, data availability,
    update frequency, health system.
    Mots-clés : ICIS, définition de l'indicateur, méthodologie,
    disponibilité des données, fréquence de mise à jour.
    """
    return await client.get_indicator(indicator, lang)


@tool
async def cihi_get_indicator_data(
    indicator: str,
    place: str | None = None,
    filters: dict[str, str] | None = None,
    table: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> IndicatorData:
    """Read a CIHI indicator's data table (by place, reporting level, year, and breakdown).

    Use for: rates and values such as 30-day stroke mortality in
    Alberta, or readmission rates by hospital. `place` is a substring
    of "Place or organization"; `filters` match columns exactly, e.g.
    {"Reporting level": "Province/Territory", "Time frame": "2024–2025",
    "Level 1 breakdown": "Not applicable"}. The last `limit` matching
    rows in file order come back. `lang="fr"` reads CIHI's
    French file, with French column names.
    Keywords: CIHI, health data, hospital mortality rate, readmission
    rate, province, hospital, fiscal year, risk-adjusted rate.
    Mots-clés : ICIS, données sur la santé, taux de mortalité,
    taux de réadmission, province, hôpital, exercice, taux ajusté.
    """
    return await client.get_indicator_data(
        indicator, place=place, filters=filters, table=table, limit=limit, lang=lang
    )
