"""MCP tools for StatCan's Drupal-based catalogue searches (Reference resources and Analysis)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.reference import client, constants
from maple_data_mcp.modules.statcan.reference.schemas import ReferenceSearchResult


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
    (paginate with page/count to browse it). Keywords: StatCan,
    definitions, data sources and methods, DSDM, methodology, technical
    reference guide, survey documentation, catalogue number.
    Mots-clés : Statistique Canada, définitions, sources de données et
    méthodes, méthodologie, guide de référence technique, documentation
    d'enquête, numéro au catalogue.
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
    Mots-clés : Statistique Canada, analyse, article analytique,
    coup d'œil sur, revue, périodique, document de travail.
    """
    return await client.search_analysis(query, count=count, page=page, lang=lang)
