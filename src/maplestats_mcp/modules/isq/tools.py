"""MCP tools for the Institut de la statistique du Québec's detailed tables."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.isq import client, constants
from maplestats_mcp.modules.isq.schemas import IsqSearchResult, IsqTable

Lang = Literal["en", "fr"]


@tool
async def isq_search_tables(
    query: str,
    lang: Literal["en", "fr", "all"] = "all",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> IsqSearchResult:
    """Search the Institut de la statistique du Québec's detailed tables.

    Use for: finding Québec statistics ISQ publishes and StatCan does not:
    regional and MRC or municipal data (population, disposable income),
    Québec health surveys (youth in secondary school, care experience),
    culture and communications (cinema attendance, performing arts, books,
    music, visual arts), arts council grants, investment and R&D surveys,
    agriculture, and ISQ tabulations of StatCan data for Québec. Matches
    every word of `query` (French or English, accents optional) against
    about 7,000 table page names. lang 'fr' or 'en' keeps one language's
    pages (many tables are French only). Pass a result's `table` to
    isq_get_table.
    Keywords: Quebec statistics, ISQ, regional data, MRC, administrative
    region, health survey, culture statistics, cinema, disposable income,
    Québec tables.
    Mots-clés : statistiques du Québec, ISQ, Institut de la statistique,
    données régionales, MRC, région administrative, enquête de santé,
    statistiques de la culture, cinéma, revenu disponible, tableaux.
    """
    return await client.search_tables(query, lang=lang, limit=limit)


@tool
async def isq_get_table(
    table: str,
    offset: int = 0,
    max_rows: int = constants.ROWS_DEFAULT,
    lang: Lang = "fr",
) -> IsqTable:
    """Read one Institut de la statistique du Québec table: metadata and data.

    Use for: getting the values of a table found with isq_search_tables.
    `table` is the page slug, the ISQ table number, or the page URL; lang
    picks which language's page a slug belongs to (French by default,
    since every table has a French page). Dynamic tables return `rows`,
    one dict per row keyed by column label (header levels joined with
    ' / ', e.g. '2025' or 'Moins de 1 verre / (%)'), numbers parsed from
    French format, and `flags` with ISQ's signs per value (r revised, p
    provisional, x confidential, F unreliable; see flag_legend), plus the
    table's notes and sources. Static tables return `cells` as published
    and an Excel link. Page through long tables with offset and max_rows.
    Keywords: Quebec table data, ISQ values, time series, regional
    statistics, survey estimates, confidence interval, MRC data.
    Mots-clés : données du tableau, ISQ, valeurs, série chronologique,
    statistiques régionales, estimations d'enquête, intervalle de
    confiance, MRC.
    """
    return await client.get_table(table, offset=offset, max_rows=max_rows, lang=lang)
