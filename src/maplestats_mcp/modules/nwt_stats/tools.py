"""MCP tools for the NWT Bureau of Statistics (statsnwt.ca)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nwt_stats import client, constants
from maplestats_mcp.modules.nwt_stats.schemas import FileList, FileRows

Lang = Literal["en", "fr"]


@tool
async def nwt_stats_list_files(
    topic: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    """List the Excel tables on one NWT Bureau of Statistics topic page.

    Use for: browsing what the Northwest Territories Bureau of Statistics
    publishes on a topic and getting each file's URL for nwt_stats_read_file.
    Without `topic`, returns the 49 topic slugs with titles and page links
    (gdp, business-dynamics, exports-imports, labour-force, earnings-wages,
    income, cpi, community-price-index, population, population-communities,
    population-projections, vital-statistics, housing, crime, language,
    alcohol-cannabis, traditional-activities, census-2021 ... census-1996,
    community-data with a statistical profile per community, surveys, and
    more). With `topic`, lists that page's .xlsx and .xls files with the
    agency's own title, the heading above the link (release date, survey,
    quarter or community) and nearby text. Titles are English only (`lang`
    changes the topic titles and the licence line).
    Keywords: Northwest Territories, NWT, Bureau of Statistics, statsnwt,
    Yellowknife, territorial statistics, Excel tables, topics, census,
    community profile, population, labour force.
    Mots-clés : Territoires du Nord-Ouest, T.N.-O., Bureau de la statistique,
    statistiques territoriales, tableaux Excel, sujets, recensement, profil
    des collectivités, Yellowknife, population, marché du travail.
    """
    return await client.list_files(topic=topic, limit=limit, offset=offset, lang=lang)


@tool
async def nwt_stats_search_files(
    query: str,
    topic: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> FileList:
    """Search the NWT Bureau of Statistics Excel tables by words in their titles.

    Use for: finding a Northwest Territories table without knowing its topic:
    GDP by industry, exports, business conditions by quarter, labour force by
    community, average weekly earnings, consumer price index, community price
    index, population by community, births and deaths, housing core need,
    crime incidents, Indigenous languages, cannabis and alcohol sales, a 2021
    Census table, a community's statistical profile (e.g. "Aklavik",
    "Hay River profile"). Keeps files whose title, nearby text, heading, topic
    or file name contains every word of `query` (case and accents ignored).
    The first search reads every topic page (about a minute); later ones are
    cached for six hours. `topic` narrows to one page.
    Keywords: Northwest Territories, NWT, search tables, statistics, GDP,
    CPI, community price index, population by community, census, labour,
    housing, cannabis, Excel.
    Mots-clés : Territoires du Nord-Ouest, chercher un tableau, statistiques
    des T.N.-O., PIB, IPC, indice des prix des collectivités, population par
    collectivité, recensement, emploi, logement, cannabis, Excel.
    """
    return await client.search_files(query=query, topic=topic, limit=limit, lang=lang)


@tool
async def nwt_stats_read_file(
    url: str,
    sheet: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    """Read one sheet of an NWT Bureau of Statistics Excel file (.xlsx or .xls).

    Use for: getting the numbers of a table found with nwt_stats_list_files or
    nwt_stats_search_files. Every sheet is listed with its size; a one-sheet
    file (or one sheet holding most of the cells) is read directly, otherwise
    no rows come back until `sheet` names one. Layouts are kept as published:
    a title above the table, years across columns, a two-row header (pass
    `header_rows=2`), notes at the bottom. `header_row` (1-based) overrides
    the guessed header and `header_row_candidates` suggests others.
    `filters` keeps rows whose column equals a value (case-insensitive),
    `contains` keeps rows with that text in any cell, `columns` picks
    columns; all values are text. Only links on statsnwt.ca are read.
    Keywords: Northwest Territories, NWT, Excel, sheet, workbook, xlsx, xls,
    table rows, header row, GDP, population, CPI, census.
    Mots-clés : Territoires du Nord-Ouest, T.N.-O., fichier Excel, feuille de
    calcul, classeur, lignes du tableau, ligne d'en-tête, PIB, population,
    IPC, recensement.
    """
    return await client.read_file(
        url=url,
        sheet=sheet,
        header_row=header_row,
        header_rows=header_rows,
        filters=filters,
        contains=contains,
        columns=columns,
        limit=limit,
        offset=offset,
        lang=lang,
    )
