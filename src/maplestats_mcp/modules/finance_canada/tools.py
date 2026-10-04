"""MCP tools for Finance Canada's Fiscal Reference Tables and The Fiscal Monitor."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.finance_canada import client, monitor
from maplestats_mcp.modules.finance_canada.schemas import (
    FrtTable,
    FrtTableList,
    MonitorIssueList,
    MonitorTables,
)

Lang = Literal["en", "fr"]


@tool
async def finance_frt_list_tables(
    edition: int | None = None, query: str = "", lang: Lang = "en"
) -> FrtTableList:
    """List the tables in Finance Canada's Fiscal Reference Tables.

    Use for: finding long historical series of government finances in
    Canada: federal revenues, program expenses, budgetary deficit or
    surplus, public debt charges, accumulated deficit and interest-bearing
    debt since 1966-67 (Public Accounts); each province's and territory's
    revenues, federal transfers, spending, deficit and net debt since
    1990-91; revenue, expense and balance sheets of all levels of
    government (national accounts, since 1991); and G7 comparisons of
    revenue, spending, balance, net and gross debt (% of GDP, since 1980).
    Editions 2019 to 2025 (default the newest), each about 55 tables.
    `query` filters titles and column names ('debt', 'Alberta', 'G7').
    Then read one with finance_frt_get_table.
    Keywords: Fiscal Reference Tables, federal deficit history, federal
    debt, provincial net debt, government revenue and spending, public
    debt charges, debt-to-GDP, fiscal history Canada.
    Mots-clés : tableaux de référence financiers, historique du déficit
    fédéral, dette fédérale, dette nette provinciale, revenus et dépenses
    publics, frais de la dette publique, ratio dette-PIB, finances
    publiques, ministère des Finances Canada.
    """
    return await client.list_frt_tables(edition, query=query, lang=lang)


@tool
async def finance_frt_get_table(
    table: int,
    edition: int | None = None,
    last: int | None = None,
    lang: Lang = "en",
) -> FrtTable:
    """Read one Fiscal Reference Tables table: every year, every column.

    Use for: the numbers behind a federal or provincial fiscal question,
    such as federal revenues and expenses by year (Table 1), personal and
    corporate income tax revenue (Table 3), public debt charges (Table 13),
    a province's deficit and net debt (Tables 18 to 30, Alberta is 26),
    all provinces combined (31, 32), or G7 net debt (54). Rows are keyed by
    the published column names with the fiscal or calendar year first;
    units are listed in `info.units` (millions of dollars, per cent of
    GDP) and footnotes in `notes`. `last` keeps only the most recent rows.
    Keywords: federal budget balance by year, deficit history table,
    provincial deficit, net debt by province, federal revenue by source,
    program spending history, public accounts data, G7 government debt.
    Mots-clés : solde budgétaire fédéral par année, tableau historique du
    déficit, déficit provincial, dette nette par province, revenus fédéraux
    par source, dépenses de programmes, comptes publics, dette publique du
    G7, ministère des Finances Canada.
    """
    return await client.get_frt_table(table, edition=edition, last=last, lang=lang)


@tool
async def finance_fiscal_monitor_list_issues(lang: Lang = "en") -> MonitorIssueList:
    """List the monthly issues of The Fiscal Monitor (Finance Canada).

    Use for: which months of federal fiscal results are published, with
    each issue's release date and page, newest first, since January 2021.
    Some issues cover two months (April and May) and are listed under
    their first month. Read one with finance_fiscal_monitor_get_tables.
    Keywords: Fiscal Monitor, monthly federal fiscal results, federal
    deficit this year, year-to-date budgetary balance, Finance Canada
    monthly report, federal revenues monthly, government of Canada
    finances, fiscal update.
    Mots-clés : revue financière, résultats financiers mensuels, déficit
    fédéral cumulatif, solde budgétaire depuis le début de l'exercice,
    rapport mensuel des Finances, revenus fédéraux mensuels, finances du
    gouvernement du Canada, mise à jour financière, ministère des Finances
    Canada.
    """
    return await monitor.list_issues(lang=lang)


@tool
async def finance_fiscal_monitor_get_tables(
    period: str = "", table: str = "", lang: Lang = "en"
) -> MonitorTables:
    """Read The Fiscal Monitor's tables for a month (federal year to date).

    Use for: the federal government's budgetary balance for the month and
    the fiscal year to date, revenues by source (personal, corporate and
    non-resident income tax, GST, EI premiums), expenses by type (Old Age
    Security, Canada Health Transfer, Canada Child Benefit, public debt
    charges), expenses by object, and the financial source or requirement,
    each against the same period a year earlier, plus the data behind the
    issue's charts. `period` is YYYY-MM (default the newest issue); `table`
    picks one ('2', 'Table 3', 'Chart 1'), else all are returned. Numbers
    are in $ millions unless the column says otherwise; negatives appear
    as negatives.
    Keywords: federal deficit year to date, monthly budget balance,
    federal revenues and expenses, Fiscal Monitor tables, GST revenue,
    public debt charges monthly, Canada federal finances, financial
    requirement.
    Mots-clés : déficit fédéral cumulatif, solde budgétaire mensuel, revenus
    et charges fédéraux, tableaux de la revue financière, recettes de TPS,
    frais de la dette publique, finances fédérales, besoins financiers,
    ministère des Finances Canada.
    """
    return await monitor.get_tables(period, table=table, lang=lang)
