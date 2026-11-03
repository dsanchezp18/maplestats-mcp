"""MCP tools for GC InfoBase open datasets."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.gc_infobase import client, constants
from maplestats_mcp.modules.gc_infobase.schemas import InfoBaseFileList, InfoBaseRows

Lang = Literal["en", "fr"]


@tool
async def gc_infobase_list_files(query: str | None = None, lang: Lang = "en") -> InfoBaseFileList:
    """List GC InfoBase's federal spending and results files (Treasury Board Secretariat).

    Use for: finding the file for Main Estimates, Public Accounts
    (authorities and expenditures by vote, standard object, transfer
    payments), planned vs actual spending and FTEs by program,
    departmental results indicators, or the inventory of federal
    organizations. `query` filters names; `lang="fr"` returns the French
    files.
    Keywords: GC InfoBase, federal spending by department, Public Accounts,
    Main Estimates, departmental results, FTE, employees, public servants,
    programs, Treasury Board.
    Mots-clés : InfoBase du GC, dépenses fédérales par ministère, Comptes
    publics, Budget principal des dépenses, résultats ministériels, ETP,
    effectifs, fonctionnaires, programmes, budget fédéral.
    """
    return await client.list_files(query, lang)


@tool
async def gc_infobase_query(
    resource_id: str,
    organization: str | None = None,
    fiscal_year: str | None = None,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> InfoBaseRows:
    """Query rows of one GC InfoBase file by organization, fiscal year, and column values.

    Use for: a department's authorities and expenditures, transfer
    payments, program spending and FTEs, or results targets, e.g.
    organization="Canada Revenue Agency", fiscal_year="2023-24".
    `organization` is a substring match; `fiscal_year` matches the start
    year whatever the file's format ("2023-24", "2023-2024", "FY 2023-24");
    `filters` are exact column matches. `resource_id` comes from
    gc_infobase_list_files; use a French file for French column names
    (an English file asked for with lang="fr" keeps its English name and
    rows, and provenance.limits names the French file). Amounts and
    counts come back as numbers (listed in numeric_columns); id and code
    columns stay text.
    For a department's total spending or its number of employees, this is
    the source; proactive disclosure (disclosure_) covers only contracts,
    grants, travel and hospitality.
    Keywords: federal government spending by department, how much a
    department spent, department budget, expenditures, authorities,
    transfer payments, program spending, FTE, full-time equivalents,
    employees by department, number of public servants, headcount,
    federal workforce, public accounts.
    Mots-clés : dépenses fédérales, dépenses par ministère, combien un
    ministère a dépensé, budget ministériel, autorisations, paiements de
    transfert, dépenses de programme, ETP, équivalents temps plein,
    effectifs, nombre de fonctionnaires, fonction publique, comptes publics,
    InfoBase du GC.
    """
    return await client.query(
        resource_id,
        organization=organization,
        fiscal_year=fiscal_year,
        filters=filters,
        columns=columns,
        limit=limit,
        lang=lang,
    )
