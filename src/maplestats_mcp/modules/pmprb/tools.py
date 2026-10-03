"""MCP tools for the Patented Medicine Prices Review Board."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.pmprb import client, constants
from maplestats_mcp.modules.pmprb.schemas import (
    MedicineStatus,
    PmprbMedicineList,
    PmprbTableList,
    PmprbTableResult,
)

Lang = Literal["en", "fr"]


@tool
async def pmprb_list_report_tables(
    year: int | None = None, query: str = "", lang: Lang = "en"
) -> PmprbTableList:
    """List the data tables in PMPRB's annual reports on patented medicine prices.

    Use for: finding patented drug price statistics from the Patented
    Medicine Prices Review Board, 2018 to 2024 reports: the Patented
    Medicines Price Index (PMPI) against CPI since 2005, how Canadian list
    prices compare with the PMPRB11 and OECD countries (median and highest
    international price ratios), patented medicine sales since 1990 and
    their drivers, sales by therapeutic class, biosimilar uptake, R&D
    spending and R&D-to-sales ratios by company, province and type of
    research, and price review outcomes. With `year`, lists that report's
    tables (each chart's data table included); with only `query`, searches
    titles and columns across every year; with neither, lists the reports.
    Pass a year and a table's label or index to pmprb_get_report_table.
    Keywords: PMPRB, patented medicine prices, drug prices, pharmaceutical
    prices, international price comparison, PMPI, pharmaceutical R&D,
    drug sales, patented drugs.
    Mots-clés : CEPMB, prix des médicaments brevetés, prix des
    médicaments, comparaison internationale des prix, IPMB, dépenses de
    R-D pharmaceutique, ventes de médicaments, médicaments brevetés.
    """
    return await client.list_report_tables(year, query=query, lang=lang)


@tool
async def pmprb_get_report_table(year: int, table: str, lang: Lang = "en") -> PmprbTableResult:
    """Read a table from a PMPRB annual report, with numbers parsed.

    Use for: the figures behind a PMPRB table or chart: PMPI and CPI index
    and rates of change by year, foreign-to-Canadian price ratios by
    country, patented medicine sales and share of GDP by year, R&D
    expenditures by company or province. `year` is the report year (2018
    to 2024); `table` is a title start like 'Figure 1' or 'Table 5'
    ('Tableau 5' works too) or the index from pmprb_list_report_tables.
    A title can own several tables (a chart drawn from two, or sub-tables
    with their own caption); all are returned. Numbers drop '$' and '%',
    so read units from the column name or label.
    Keywords: PMPRB table, patented medicine price index, price ratio by
    country, patented drug sales, R&D-to-sales ratio, pharmaceutical
    statistics, annual report data, drug price trends.
    Mots-clés : tableau du CEPMB, indice des prix des médicaments
    brevetés, ratio des prix par pays, ventes de médicaments brevetés,
    ratio R-D/ventes, statistiques pharmaceutiques, rapport annuel,
    tendances des prix des médicaments.
    """
    return await client.get_report_table(year, table, lang=lang)


@tool
async def pmprb_search_patented_medicines(
    query: str = "",
    company: str = "",
    atc: str = "",
    status: MedicineStatus | None = None,
    year: Literal[2020, 2021] = 2021,
    limit: int = constants.MEDICINES_DEFAULT_LIMIT,
    lang: Lang = "en",
) -> PmprbMedicineList:
    """Search the list of patented medicines reported to PMPRB (2020 or 2021).

    Use for: whether a drug was under PMPRB price jurisdiction, which
    company reported it, and its price review status: within guidelines,
    does not trigger an investigation, under investigation, under review,
    voluntary compliance undertaking, notice of hearing. About 1,200 drug
    products a year with DIN, brand name, medicinal ingredient, ATC class
    and dosage form. `query` matches DIN, brand, ingredient or company;
    `atc` is a class prefix (L04 immunosuppressants); counts by status come
    with every result. PMPRB published no list after 2021.
    Keywords: patented medicines list, DIN, drug price review, excessive
    pricing investigation, PMPRB jurisdiction, patentee, rights holder,
    brand name drug, ATC code.
    Mots-clés : liste des médicaments brevetés, DIN, examen du prix,
    enquête sur les prix excessifs, compétence du CEPMB, breveté,
    titulaire de droits, médicament de marque, code ATC.
    """
    return await client.search_patented_medicines(
        query, company=company, atc=atc, status=status, year=year, limit=limit, lang=lang
    )
