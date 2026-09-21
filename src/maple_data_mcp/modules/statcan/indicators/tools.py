"""MCP tools for StatCan's official Indicators JSON feeds."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.indicators import client, constants
from maple_data_mcp.modules.statcan.indicators.schemas import IndicatorList

Dataset = Literal["all", "economic", "homepage"]


@tool
async def statcan_indicators_get_indicators(
    dataset: Dataset = "all",
    query: str = "",
    geo_code: int | None = None,
    lang: Literal["en", "fr"] = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> IndicatorList:
    """Get current StatCan indicators (population, CPI, GDP, trade, etc.) with growth rates.

    Use for: quick current-value lookups for named indicators (e.g.
    "population", "consumer price index", "GDP", "unemployment rate")
    -- the same feeds that power My StatCan, statcan.gc.ca's home
    page, and The Daily's own indicator widgets. dataset="economic"
    is a curated subset of major economic indicators; "homepage" is
    the subset shown on StatCan's own home page; "all" covers every
    tracked indicator (2,362 confirmed live). Each result carries its
    reference period, a growth-rate summary versus the prior period,
    and a link to the Daily article that released it. geo_code filters
    to one geography (0 = Canada, province/territory codes otherwise
    -- call with a wide query first to see which codes exist in this
    dataset). Keywords: StatCan, indicator, current value, latest
    statistics, growth rate, population, CPI, GDP, unemployment.
    Mots-clés : Statistique Canada, indicateur, valeur actuelle,
    dernières statistiques, taux de croissance, population, IPC, PIB.
    """
    return await client.get_indicators(dataset, query, geo_code=geo_code, lang=lang, limit=limit)
