"""MCP tools for NRCan annual mineral production statistics."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nrcan_minerals import client
from maplestats_mcp.modules.nrcan_minerals.schemas import MineralProduction, MineralSeries

Lang = Literal["en", "fr"]


@tool
async def nrcan_minerals_get_production(
    year: int | None = None,
    commodity: str = "",
    province: str = "",
    category: Literal["all", "value", "quantity"] = "all",
    limit: int = 500,
    lang: Lang = "en",
) -> MineralProduction:
    """Canada's annual mineral production by commodity and province (NRCan).

    Use for: how much gold, copper, nickel, iron ore, potash, diamonds,
    uranium, lithium, zinc, coal, salt, sand and gravel or stone a province
    or territory produced and shipped in a year, and the value of
    shipments (thousands of dollars), from 1990 to the latest preliminary
    estimate (the default year). `commodity` matches names ('gold',
    'potash'); `province` is a code (ON, QC, BC...) or name, 'Canada' for
    the national total; `category` keeps values or quantities. Each row
    says whether it is preliminary, confidential ('x') or not available.
    Use nrcan_minerals_get_series for one commodity across years. English
    only (NRCan publishes these files in English; lang has no effect).
    Monthly production since 2020 is StatCan table 16-10-0022 (wds_).
    Keywords: mineral production, mining statistics, gold production by
    province, value of mineral shipments, metal production, NRCan mining,
    potash output, critical minerals, preliminary estimate.
    Mots-clés : production minérale, statistiques minières, production d'or
    par province, valeur des expéditions minérales, production de métaux,
    Ressources naturelles Canada (RNCan), mines, potasse, minéraux critiques.
    """
    return await client.get_production(
        year, commodity=commodity, province=province, category=category, limit=limit, lang=lang
    )


@tool
async def nrcan_minerals_get_series(
    commodity: str,
    province: str = "Canada",
    category: Literal["value", "quantity_shipped", "quantity_produced"] = "value",
    from_year: int | None = None,
    to_year: int | None = None,
    lang: Lang = "en",
) -> MineralSeries:
    """One mineral commodity's production across years, 1990 onward (NRCan).

    Use for: a long series of Canadian mine output, such as the value of
    gold shipments in Ontario since 1990, copper quantity shipped in
    British Columbia, or the grand total value of mineral production in
    Canada by year. Reads one file per year (a full 1990-2025 series takes
    about 15 seconds the first time). `commodity` is an exact name or a
    partial one that matches a single commodity in each year ('Grand
    total' for all minerals); years where it is ambiguous or absent are
    listed. Quantity produced exists from 2019 only. Units changed over
    time, so read each point's units. English only (lang has no effect).
    Keywords: mineral production time series, gold output history, mining
    value of shipments by year, copper production trend, Canada mining
    history, annual mineral statistics, NRCan, metal output since 1990.
    Mots-clés : série chronologique production minérale, historique de la
    production d'or, valeur des expéditions par année, tendance de la
    production de cuivre, histoire minière du Canada, statistiques
    annuelles, Ressources naturelles Canada (RNCan), production de métaux
    depuis 1990.
    """
    return await client.get_series(
        commodity,
        province=province,
        category=category,
        from_year=from_year,
        to_year=to_year,
        lang=lang,
    )
