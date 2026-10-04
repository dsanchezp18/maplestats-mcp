"""MCP tools for BC Stats Excel tables."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bc_stats import client, constants
from maplestats_mcp.modules.bc_stats.schemas import FileData, FileList

Lang = Literal["en", "fr"]


@tool
async def bc_stats_list_files(
    query: str | None = None,
    dataset: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    """List the Excel (.xlsx) tables BC Stats publishes on the BC data catalogue.

    Use for: finding a British Columbia statistics workbook that has no queryable
    DataStore rows (monthly Labour Force Survey data tables, GDP by industry, BC
    Economic Accounts, monthly and annual tourism indicators, population estimates
    and projections, consumer price index, bankruptcies, business counts,
    international commodity exports, housing starts, building permits) and its file
    URL for bc_stats_read_file. Each file carries the agency's own title, its
    licence, update cycle, size, and the formats the dataset also has. `query`
    keeps files whose title or dataset title contains every word; `dataset` keeps
    one catalogue dataset by name or title. Use ckan_ tools with portal=bc for
    CSV resources and the rest of the catalogue.
    Keywords: BC Stats, British Columbia, Excel, xlsx, Labour Force Survey, GDP by
    industry, tourism indicators, population projections, CPI, bankruptcies,
    provincial statistics, data catalogue.
    Mots-clés : BC Stats, Colombie-Britannique, Excel, xlsx, Enquête sur la
    population active, PIB par industrie, indicateurs touristiques, projections de
    population, IPC, faillites, statistiques provinciales, catalogue de données.
    """
    return await client.list_files(
        query=query, dataset=dataset, limit=limit, offset=offset, lang=lang
    )


@tool
async def bc_stats_read_file(
    url: str,
    sheet: str | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileData:
    """Read one sheet of a BC Stats Excel file listed by bc_stats_list_files.

    Use for: getting the numbers in a BC Stats workbook: monthly labour force
    characteristics (employment, unemployment rate, by age, industry, CMA),
    GDP by industry in current and chained dollars, tourism indicators, BC
    population estimates and projections to 2046, CPI by category, bankruptcies by
    CMA. Without `sheet`, the first sheet that is not a notes page ('READ ME',
    'Notes', 'Contents') is returned and provenance.limits names it (every
    sheet name with its row and column counts is in the result). Layouts are kept as
    published: title rows can precede the table, headers can span several rows and
    years can run across columns, so `header_row` is a guess (the first row with
    three filled cells) that you can override with a 1-based row number; every
    value is text. `contains` keeps rows with that text in any cell
    (case-insensitive), e.g. a year or an industry; use `offset` and `limit` to
    page. The result carries the file's licence; attribute BC Stats.
    Keywords: BC Stats, British Columbia, Excel, sheet, xlsx, Labour Force Survey,
    unemployment rate, GDP by industry, tourism, population projections, CPI,
    monthly, annual, table.
    Mots-clés : BC Stats, Colombie-Britannique, Excel, feuille, xlsx, Enquête sur
    la population active, taux de chômage, PIB par industrie, tourisme,
    projections de population, IPC, mensuel, annuel, tableau.
    """
    return await client.read_file(
        url=url,
        sheet=sheet,
        contains=contains,
        header_row=header_row,
        limit=limit,
        offset=offset,
        lang=lang,
    )
