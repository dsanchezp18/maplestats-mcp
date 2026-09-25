"""MCP tools for CIPO's IP Horizons researcher datasets."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ised.ip_horizons import client
from maplestats_mcp.modules.ised.ip_horizons.schemas import (
    IpHorizonsCatalogue,
    IpHorizonsDictionary,
    IpType,
    PatentRecord,
    PatentSearchResult,
)

Lang = Literal["en", "fr"]
DictionaryType = Literal["patent", "industrial_design"]
PartyType = Literal["owner", "inventor", "applicant", "agent"]


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


@tool
async def ised_ip_horizons_get_patent(
    patent_number: int,
    include_classifications: bool = False,
    lang: Lang = "en",
) -> PatentRecord:
    """Look up one Canadian patent by number in CIPO's IP Horizons data.

    Use for: a Canadian patent or application's title (EN/FR), filing
    and grant dates, status, PCT numbers, and its owners, inventors,
    applicants and agents with their city and country. Set
    include_classifications=True to add its IPC classes, which reads a
    much larger file. Data is as of the latest quarterly release, not
    live. The first call downloads the needed table (tens to hundreds of
    MB) into a local cache; if it times out, the download continues and
    a retry a few minutes later answers from the cache. `lang` has no
    effect: titles come in both languages.
    Keywords: patent lookup, patent number, Canadian patent, CIPO, IP
    Horizons, patent owner, inventor, applicant, filing date, grant
    date, IPC class, intellectual property.
    Mots-clés : recherche de brevet, numéro de brevet, brevet canadien,
    OPIC, Horizons PI, titulaire du brevet, inventeur, demandeur, date
    de dépôt, date d'octroi, classe CIB, propriété intellectuelle.
    """
    del lang
    return await client.get_patent(patent_number, include_classifications=include_classifications)


@tool
async def ised_ip_horizons_search_patents(
    party_name: str | None = None,
    party_type: PartyType | None = None,
    ipc: str | None = None,
    title: str | None = None,
    filed_from: date | None = None,
    filed_to: date | None = None,
    limit: int = 25,
    lang: Lang = "en",
) -> PatentSearchResult:
    """Search Canadian patents by owner/inventor name, IPC class, title or filing date.

    Use for: finding the Canadian patents of a company or inventor
    (party_name, a case-insensitive substring; party_type narrows to
    owner, inventor, applicant or agent), patents in a technology class
    (ipc like 'H01M', 'H01M 8' or 'H01M 8/04'), by title words (English
    or French), or by filing-date range. Filters combine with AND.
    Returns the newest matches by filing date and the total match count
    across all ~3.2 million records since 1869. Data is as of the latest
    quarterly release. Each filter type downloads its table once into a
    local cache on first use; the IPC table is ~740 MB and can take many
    minutes, so a first call may time out while the download continues
    in the background; retry later. Follow up with
    ised_ip_horizons_get_patent for parties and classes. `lang` has no
    effect.
    Keywords: patent search, Canadian patents, patent owner, assignee,
    inventor, company patents, IPC classification, technology class,
    filing date, CIPO, IP Horizons, innovation.
    Mots-clés : recherche de brevets, brevets canadiens, titulaire,
    cessionnaire, inventeur, brevets d'une entreprise, classification
    CIB, domaine technologique, date de dépôt, OPIC, Horizons PI.
    """
    del lang
    return await client.search_patents(
        party_name=party_name,
        party_type=party_type,
        ipc=ipc,
        title=title,
        filed_from=filed_from,
        filed_to=filed_to,
        limit=limit,
    )
