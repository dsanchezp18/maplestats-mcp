"""MCP tools for StatCan's Drupal-based catalogue searches (Reference resources and Analysis)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.reference import client, constants
from maplestats_mcp.modules.statcan.reference.schemas import ReferenceSearchResult


@tool
async def statcan_reference_search_documents(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Reference resources catalogue: definitions, data sources, and methods.

    Use for: finding methodology guides, technical reference documents,
    survey documentation, geographic file specifications, and other
    "Definitions, data sources and methods"-style publications --
    distinct from actual data (WDS/SDMX/RDaaS) and from The Daily's
    release bulletin (statcan_daily_*). Covers 2,031 documents. Each
    result carries a catalogue number (e.g. "16-511-X"), a category
    (e.g. "Surveys and statistical programs – Documentation",
    "Geographic files and documentation"), a description, and a
    release date. An empty query returns the full unfiltered catalogue
    (paginate with page/count to browse it). Keywords: StatCan, definitions,
    data sources and methods, DSDM, methodology, technical reference guide,
    survey documentation, catalogue number.
    Mots-clés : Statistique Canada, définitions, sources de données et
    méthodes, méthodologie, guide de référence technique, documentation
    d'enquête, numéro au catalogue, publications techniques.
    """
    return await client.search_documents(query, count=count, page=page, lang=lang)


@tool
async def statcan_reference_search_analysis(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Analysis catalogue: analytical articles, journals and periodicals.

    Use for: finding analytical publications, "Stats in brief" (many
    of these are also Daily articles republished with a catalogue
    number), and journal/periodical series -- distinct from
    statcan_reference_search_documents (methodology/definitions
    catalogue), from actual data (WDS/SDMX/RDaaS), and from The
    Daily's release bulletin (statcan_daily_*). Covers 10,841+
    documents. Each result carries a catalogue number (e.g.
    "46-28-0001"), a category (e.g. "Journals and periodicals"), a
    description, and a release date. An empty query returns the full
    unfiltered catalogue (paginate with page/count to browse it).
    Keywords: StatCan, analysis, analytical article, stats in brief,
    journal, periodical, working paper, insights.
    Mots-clés : Statistique Canada, analyse, article analytique, coup d'œil
    sur, revue, périodique, document de travail, études.
    """
    return await client.search_analysis(query, count=count, page=page, lang=lang)


@tool
async def statcan_reference_search_data(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Data catalogue: tables plus PUMFs, geographic and other bulk files.

    Use for: finding a data product's catalogue number, especially one
    with no WDS/SDMX discovery path of its own -- most notably Public
    Use Microdata Files (PUMFs; category "Public use microdata", e.g.
    catalogue number 71M0001X for the Labour Force Survey PUMF,
    98M0001X for the Census). Most other results here are ordinary
    table PIDs also reachable via statcan_wds_*/statcan_sdmx_*, so
    prefer those tools for routine table search -- use this one when
    the product itself (a PUMF, a boundary file, a bulk archive) is
    the target, not a table's time series. Covers 13,342+ items. For a
    PUMF, pass its catalogue_number to statcan_pumf_list_files for the
    download ZIPs. An empty query returns the full unfiltered catalogue (paginate with
    page/count to browse it). Keywords: StatCan, PUMF, public use microdata
    file, geographic boundary file, bulk data, data product, Statistics
    Canada, download.
    Mots-clés : Statistique Canada, FMGD, fichier de microdonnées à grande
    diffusion, fichier de limites géographiques, données en bloc, produit de
    données, téléchargement, cartes géographiques.
    """
    return await client.search_data(query, count=count, page=page, lang=lang)
