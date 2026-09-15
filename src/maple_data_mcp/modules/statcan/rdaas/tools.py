"""MCP tools for StatCan's Reference Data as a Service (RDaaS).

Delivers classifications, codesets, and concordances (e.g. NAICS, the
Standard Geographical Classification) as structured data — the concrete
version of the project goal to make StatCan documentation/classification
material first-class and agent-accessible, not scraped PDFs.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.rdaas import client
from maple_data_mcp.modules.statcan.rdaas.schemas import (
    ClassificationCategoriesDetailed,
    ClassificationDetail,
    ClassificationExclusions,
    ClassificationIndexEntry,
    ClassificationIndexes,
    ClassificationSearchResult,
    CodeMapList,
    ConcordanceDetail,
    ConcordanceSearchResult,
    SearchFilters,
    TermExclusion,
)

Lang = Literal["en", "fr"]


@tool
async def rdaas_search_classifications(
    query: str = "",
    start: int = 0,
    limit: int = 10,
    lang: Lang = "en",
) -> ClassificationSearchResult:
    """Search StatCan's classifications (e.g. NAICS, the Standard
    Geographical Classification, occupational classifications).

    Use for: finding the classification id for a topic before requesting
    its full detail, categories, or concordances.
    Keywords: statcan, naics, classification, search, rdaas, standard,
    geographical, occupational, codes.
    """
    return await client.search_classifications(query, start=start, limit=limit, lang=lang)


@tool
async def rdaas_get_classification_search_filters(lang: Lang = "en") -> SearchFilters:
    """Get the valid audience/status filter values for classification search.

    Use for: discovering what values `audience`/`status` accept before
    filtering a search.
    Keywords: statcan, rdaas, filters, search, audience, status,
    classification.
    """
    return await client.get_classification_search_filters()


@tool
async def rdaas_get_classification(
    classification_id: str, lang: Lang = "en"
) -> ClassificationDetail:
    """Get full detail for one StatCan classification: background,
    version, harmonization status, and its level structure.

    Use for: understanding a classification (e.g. NAICS) before drilling
    into its categories.
    Keywords: statcan, classification, detail, naics, rdaas, levels,
    version, background.
    """
    return await client.get_classification(classification_id, lang=lang)


@tool
async def rdaas_get_classification_categories_detailed(
    classification_id: str, lang: Lang = "en"
) -> ClassificationCategoriesDetailed:
    """Get the detailed category tree for one classification.

    Use for: listing every code/category within a classification (e.g.
    all NAICS sectors and subsectors).
    Keywords: statcan, classification, categories, codes, naics, rdaas,
    tree, detailed.
    """
    return await client.get_classification_categories_detailed(classification_id, lang=lang)


@tool
async def rdaas_get_classification_exclusions(
    classification_id: str, lang: Lang = "en"
) -> ClassificationExclusions:
    """Get documented exclusions (terms explicitly NOT covered) for one classification.

    Use for: checking whether a term is deliberately excluded from a
    classification rather than simply missing.
    Keywords: statcan, exclusions, classification, rdaas, excluded,
    terms, naics.
    """
    return await client.get_classification_exclusions(classification_id, lang=lang)


@tool
async def rdaas_get_classification_indexes(classification_id: str) -> ClassificationIndexes:
    """List all index entries (alternate terms mapped to a code) for one classification.

    Use for: finding which code a plain-language term maps to.
    Keywords: statcan, index, classification, rdaas, terms, alternate
    names, naics.
    """
    return await client.get_classification_indexes(classification_id)


@tool
async def rdaas_get_classification_index_entry(
    classification_id: str, index_id: int
) -> ClassificationIndexEntry:
    """Get one specific index entry by its small integer index_id (not
    its @id URL — use the indexId field from rdaas_get_classification_indexes).

    Use for: retrieving a single term-to-code mapping already identified
    via rdaas_get_classification_indexes.
    Keywords: statcan, index entry, classification, rdaas, term, code.
    """
    return await client.get_classification_index_entry(classification_id, index_id)


@tool
async def rdaas_get_term_exclusion(term_exclusion_id: str, lang: Lang = "en") -> TermExclusion:
    """Get one term-exclusion record by id.

    Use for: retrieving detail on a specific excluded term identified
    elsewhere.
    Keywords: statcan, term exclusion, rdaas, excluded, definition.
    """
    return await client.get_term_exclusion(term_exclusion_id, lang=lang)


@tool
async def rdaas_search_concordances(
    query: str = "",
    start: int = 0,
    limit: int = 10,
    lang: Lang = "en",
) -> ConcordanceSearchResult:
    """Search StatCan's concordances: correspondence tables between two
    classification versions (e.g. NAICS 2012 to NAICS 2017).

    Use for: finding a concordance id before requesting its code maps.
    Keywords: statcan, concordance, correspondence, rdaas, naics,
    version, mapping.
    """
    return await client.search_concordances(query, start=start, limit=limit, lang=lang)


@tool
async def rdaas_get_concordance_search_filters(lang: Lang = "en") -> SearchFilters:
    """Get the valid audience/status filter values for concordance search.

    Use for: discovering what values `audience`/`status` accept before
    filtering a concordance search.
    Keywords: statcan, rdaas, filters, search, concordance, audience,
    status.
    """
    return await client.get_concordance_search_filters()


@tool
async def rdaas_get_concordance(concordance_id: str, lang: Lang = "en") -> ConcordanceDetail:
    """Get detail for one concordance: its source and target classifications.

    Use for: confirming which two classification versions a concordance
    connects before requesting its code maps.
    Keywords: statcan, concordance, detail, rdaas, source, target,
    classification.
    """
    return await client.get_concordance(concordance_id, lang=lang)


@tool
async def rdaas_get_concordance_maps(concordance_id: str, lang: Lang = "en") -> CodeMapList:
    """Get the full code-to-code mapping table for one concordance.

    Use for: converting a code from one classification version to its
    equivalent(s) in another version.
    Keywords: statcan, code map, concordance, rdaas, mapping, convert,
    naics.
    """
    return await client.get_concordance_maps(concordance_id, lang=lang)
