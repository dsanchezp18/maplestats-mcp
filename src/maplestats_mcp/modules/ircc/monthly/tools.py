"""MCP tools for IRCC's monthly open data tables."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ircc.monthly import client, constants
from maplestats_mcp.modules.ircc.monthly.schemas import (
    IrccQueryResult,
    IrccTableCatalogue,
    IrccTableDescription,
    Period,
)

Lang = Literal["en", "fr"]
Sort = Literal["period", "value_desc"]


@tool
async def ircc_monthly_list_tables(
    query: str = "",
    include_archived: bool = False,
    lang: Lang = "en",
) -> IrccTableCatalogue:
    """List IRCC's monthly immigration statistics tables (Monthly IRCC Updates).

    Use for: finding the table to query for monthly counts of permanent
    residents (admissions by province, census metropolitan area, census
    subdivision, country of citizenship, immigration category,
    occupation, age, gender, French-speaking), Express Entry admissions
    and invited candidates, study permit holders (including by
    designated learning institution), work permit holders (TFWP,
    International Mobility Program, post-graduation work permits),
    transitions from temporary to permanent residence, and asylum
    claimants. `query` keeps tables whose id, title or dataset contain
    every word. Archived series (Syrian, Afghan, resettled refugees) are
    left out unless include_archived. Pass a table_id to
    ircc_monthly_describe_table, then ircc_monthly_query.
    Keywords: immigration, permanent residents, admissions, newcomers,
    study permits, international students, work permits, temporary
    foreign workers, asylum claimants, refugees, IRCC monthly data.
    Mots-clés : immigration, résidents permanents, admissions,
    nouveaux arrivants, permis d'études, étudiants étrangers, permis de
    travail, travailleurs étrangers temporaires, demandeurs d'asile,
    réfugiés, données mensuelles d'IRCC.
    """
    return await client.list_tables(query, include_archived=include_archived, lang=lang)


@tool
async def ircc_monthly_describe_table(table_id: str, lang: Lang = "en") -> IrccTableDescription:
    """Describe one IRCC monthly table: its dimensions, values and time span.

    Use for: learning the dimension keys (e.g. 'province_territory',
    'immigration_category_main_category', 'country_of_citizenship') and
    their exact values before filtering or grouping with
    ircc_monthly_query, and the first and last month covered (most
    tables run from January 2015 to the latest month). table_id comes
    from ircc_monthly_list_tables, e.g. 'ODP-PR-PT_IMMCAT'. Downloads the
    whole file (up to about 30 MB), cached for hours.
    Keywords: IRCC table columns, dimensions, categories, province,
    country of citizenship, immigration category, coverage, codebook.
    Mots-clés : colonnes du tableau IRCC, dimensions, catégories,
    province, pays de citoyenneté, catégorie d'immigration, période
    couverte, dictionnaire de données.
    """
    return await client.describe_table(table_id, lang=lang)


@tool
async def ircc_monthly_query(
    table_id: str,
    filters: dict[str, str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    period: Period | None = None,
    group_by: list[str] | None = None,
    sort: Sort = "period",
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> IrccQueryResult:
    """Query and total an IRCC monthly immigration table.

    Use for: monthly, quarterly or yearly counts of permanent residents,
    study and work permit holders, temporary-to-permanent transitions or
    asylum claimants, for a province, city (CMA or census subdivision),
    country of citizenship, immigration category or occupation.
    `filters` maps a dimension key to one value in English or French,
    e.g. {"province_territory": "Alberta"}. `period` sums to 'month',
    'quarter' or 'year' (default: the table's finest). `group_by` lists
    the dimensions to keep; others are summed over (group_by=[] gives
    one total per period; omitted keeps every dimension). sort
    'value_desc' ranks the largest groups (top countries); 'period' keeps
    the most recent `limit` rows in time order. Counts are rounded to 5
    and 1-4 are suppressed ('--'), counted as 0 and reported per row in
    suppressed_cells, so sums are approximate.
    Keywords: immigrants per month, permanent resident admissions by
    province, new permanent residents, international students by
    country, work permits by province, asylum claims, immigration trend,
    IRCC time series.
    Mots-clés : immigrants par mois, admissions de résidents permanents
    par province, nouveaux résidents permanents, étudiants étrangers par
    pays, permis de travail par province, demandes d'asile, tendance de
    l'immigration, série chronologique IRCC.
    """
    return await client.query_table(
        table_id,
        filters,
        year_from=year_from,
        year_to=year_to,
        period=period,
        group_by=group_by,
        sort=sort,
        limit=limit,
        lang=lang,
    )
