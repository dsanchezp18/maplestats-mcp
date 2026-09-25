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
    Keywords: GC InfoBase, federal spending, Public Accounts, Main
    Estimates, departmental results, FTE, programs, Treasury Board.
    Mots-clés : InfoBase du GC, dépenses fédérales, Comptes publics,
    Budget principal des dépenses, résultats ministériels, ETP, programmes.
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
    gc_infobase_list_files; use a French file for French column names.
    Keywords: federal spending, department budget, expenditures,
    authorities, transfer payments, program spending, FTE, public accounts.
    Mots-clés : dépenses fédérales, budget ministériel, autorisations,
    paiements de transfert, dépenses de programme, ETP, comptes publics.
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
