"""MCP tools for StatCan's Sustainable Development Goals (SDG) Data Hub."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.sdg import client, constants
from maplestats_mcp.modules.statcan.sdg.schemas import (
    SdgIndicatorData,
    SdgIndicatorMetadata,
    SdgIndicatorSearchResult,
)

Framework = Literal["canada", "global"]
Lang = Literal["en", "fr"]


@tool
async def statcan_sdg_search_indicators(
    framework: Framework,
    query: str = "",
    lang: Lang = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> SdgIndicatorSearchResult:
    """Search StatCan's Sustainable Development Goals indicators by name.

    Use for: finding an indicator's code before requesting its
    metadata or data. `framework` selects which indicator set: "canada"
    (86 indicators, Canada's own national reporting framework) or
    "global" (251 indicators, Canada's reporting against the UN's own
    Global Indicator Framework) -- distinct, differently-numbered
    indicator sets on the same "Open SDG" platform, confirmed live;
    pick the one matching what the caller means by "SDG indicator X.Y.Z".
    Leave `query` empty to list every indicator in that framework. This
    data has no WDS/SDMX cube/PID equivalent -- it is not otherwise
    reachable through any other tool in this codebase.
    Keywords: statcan, SDG, sustainable development goals, indicator,
    UN, 2030 agenda, goal, target.
    Mots-clés : statcan, ODD, objectifs de développement durable,
    indicateur, ONU, programme 2030, objectif, cible.
    """
    return await client.search_indicators(framework, query, lang=lang, limit=limit)


@tool
async def statcan_sdg_get_indicator_metadata(
    framework: Framework, code: str, lang: Lang = "en"
) -> SdgIndicatorMetadata:
    """Get one SDG indicator's goal/target, description, units, and data sources.

    Use for: understanding what an indicator (e.g. "12-1-1") actually
    measures before requesting its data with
    statcan_sdg_get_indicator_data. `code` comes from
    statcan_sdg_search_indicators; the same code can mean a different
    indicator in the "canada" vs. "global" framework, so pass the same
    `framework` used to find it.
    Keywords: statcan, SDG, indicator metadata, goal, target,
    definition, source, sustainable development.
    Mots-clés : statcan, ODD, métadonnées d'indicateur, objectif,
    cible, définition, source, développement durable.
    """
    return await client.get_indicator_metadata(framework, code, lang=lang)


@tool
async def statcan_sdg_get_indicator_data(
    framework: Framework, code: str, lang: Lang = "en"
) -> SdgIndicatorData:
    """Get one SDG indicator's observations (year, value, and any disaggregations).

    Use for: retrieving an SDG indicator's actual time series. Each
    observation's `disaggregations` field carries whatever breakdown
    columns that specific indicator publishes (e.g. Geography, Pillar)
    -- these vary per indicator and are not fixed across the framework,
    confirmed live.
    Keywords: statcan, SDG, indicator data, time series, sustainable
    development goals, observations.
    Mots-clés : statcan, ODD, données d'indicateur, série chronologique,
    objectifs de développement durable, observations.
    """
    return await client.get_indicator_data(framework, code, lang=lang)
