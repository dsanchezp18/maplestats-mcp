"""MCP tools for the Newfoundland and Labrador Statistics Agency."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nl_stats import client, constants
from maplestats_mcp.modules.nl_stats.schemas import FileData, FileList

Lang = Literal["en", "fr"]


@tool
async def nl_stats_list_files(
    topic: str | None = None,
    query: str | None = None,
    limit: int = constants.FILES_LIMIT_MAX,
    lang: Lang = "en",
) -> FileList:
    """List the Excel tables published by the Newfoundland and Labrador Statistics Agency.

    Use for: finding a Newfoundland and Labrador statistics table (quarterly
    population since 1971, labour force by month, consumer price index, GDP,
    international trade, income, health, education, employment insurance,
    minimum wage, census division and St. John's CMA estimates) and its file
    URL for nl_stats_read_file. `topic` is one of the slugs in the result
    (population, labour, cpi, gdp, trade, industry, income, health, education,
    ei, minimumwage, personalfinance, transportation, charitabledonations,
    incomesupport); `query` keeps files whose title, heading or URL contains
    every word. The agency's own descriptions are English only.
    Keywords: Newfoundland and Labrador, NL, Statistics Agency, population,
    labour force, unemployment, CPI, GDP, trade, St. John's, census division,
    Excel, provincial statistics, minimum wage.
    Mots-clés : Terre-Neuve-et-Labrador, agence de la statistique, population,
    population active, chômage, IPC, PIB, commerce, St. John's, division de
    recensement, Excel, statistiques provinciales, salaire minimum.
    """
    return await client.list_files(topic=topic, query=query, limit=limit, lang=lang)


@tool
async def nl_stats_read_file(
    url: str,
    sheet: str | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileData:
    """Read one sheet of a Newfoundland and Labrador Statistics Agency Excel file.

    Use for: getting the numbers in a table found with nl_stats_list_files:
    monthly labour force and CPI series, quarterly population and migration,
    GDP by industry, trade by partner. Reads both .xlsx and legacy .xls.
    Without `sheet`, a workbook whose sheets are named after months (the
    "Current Month" labour files: Jan2026, Feb2026, ...) returns the newest
    month's sheet, any other workbook its first sheet; `sheet_chosen_by` and
    provenance.limits say which, and every sheet name with its row and column
    counts is in the result. The agency's layouts are kept as published: a
    title row can precede the header, and years or months can run across
    columns, so `header_row` is a guess (the first row with three filled
    cells) that you can override with a 1-based row number; `header_rows`
    (1 to 5) joins that many rows per column for a header split over rows
    (e.g. "Employment" above "Total", "Full-Time", "Part-Time", then a units
    row). Every value is text. `contains` keeps rows with that text in any
    cell (case-insensitive), e.g. a year or an industry.
    Keywords: Newfoundland and Labrador, Excel, sheet, table, monthly,
    quarterly, population, labour force, CPI, GDP, trade, xlsx, xls, series.
    Mots-clés : Terre-Neuve-et-Labrador, Excel, feuille, tableau, mensuel,
    trimestriel, population, population active, IPC, PIB, commerce, série.
    """
    return await client.read_file(
        url=url,
        sheet=sheet,
        contains=contains,
        header_row=header_row,
        header_rows=header_rows,
        limit=limit,
        offset=offset,
        lang=lang,
    )
