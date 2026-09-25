"""MCP tools for CIPO's IP Horizons researcher datasets."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ised.ip_horizons import client
from maplestats_mcp.modules.ised.ip_horizons.schemas import (
    IpHorizonsCatalogue,
    IpHorizonsDictionary,
    IpType,
)

Lang = Literal["en", "fr"]
DictionaryType = Literal["patent", "industrial_design"]


@tool
async def ised_ip_horizons_list_files(
    ip_type: IpType,
    table: str | None = None,
    latest_only: bool = True,
    lang: Lang = "en",
) -> IpHorizonsCatalogue:
    """List CIPO's IP Horizons bulk data files for patents, industrial designs or trademarks.

    Use for: finding the download links for Canada's complete patent,
    industrial design or trademark registers as researcher bulk data,
    by table (e.g. patent 'main', 'claim', 'abstract', 'disclosure',
    'interested_party', 'priority_claim', 'ipc_classification') and
    patent-number range. Each file is a ZIP of one pipe-delimited UTF-8
    CSV, refreshed quarterly; large tables are split by patent number.
    latest_only=True keeps each table's newest release folder only.
    Pair with ised_ip_horizons_get_dictionary for column meanings; for a
    live search of individual trademarks use ised_cipo_search_trademarks.
    Resource names on open.canada.ca are inconsistent, so table and
    range come from each download URL. Both languages share one file
    set, so `lang` has no effect.
    Keywords: IP Horizons, CIPO, patent data, bulk download, industrial
    design, trademark data, intellectual property, inventor, applicant,
    IPC classification, patent claims, researcher dataset.
    Mots-clés : Horizons PI, OPIC, données sur les brevets,
    téléchargement en vrac, dessin industriel, marques de commerce,
    propriété intellectuelle, inventeur, demandeur, classification CIB,
    revendications.
    """
    del lang
    return await client.list_files(ip_type, table=table, latest_only=latest_only)


@tool
async def ised_ip_horizons_get_dictionary(
    ip_type: DictionaryType,
    table: str | None = None,
    lang: Lang = "en",
) -> IpHorizonsDictionary:
    """Get the IP Horizons data dictionary for CIPO patent or industrial design bulk data.

    Use for: understanding the columns of the IP Horizons patent or
    industrial design tables before downloading them: each variable's
    English and French name, type and description, grouped by table
    (e.g. patent 'main', 'interested_party', 'ipc_classification'),
    plus coverage-period, delimiter and encoding notes. CIPO publishes
    no dictionary for the trademark files. Every field carries both
    languages, so `lang` has no effect.
    Keywords: IP Horizons, CIPO, data dictionary, codebook, patent
    variables, industrial design, column definitions, field
    descriptions, metadata, schema.
    Mots-clés : Horizons PI, OPIC, dictionnaire de données, livre de
    codes, variables des brevets, dessin industriel, définitions des
    colonnes, description des champs, métadonnées.
    """
    del lang
    return await client.get_dictionary(ip_type, table=table)
