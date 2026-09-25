"""MCP tools for StatCan's Reference Data as a Service (RDaaS).

Delivers classifications, codesets, and concordances (e.g. NAICS, the
Standard Geographical Classification) as structured data — the concrete
version of the project goal to make StatCan documentation/classification
material first-class and agent-accessible, not scraped PDFs.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.rdaas import client
from maplestats_mcp.modules.statcan.rdaas.schemas import (
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
    Mots-clés : statcan, scian, classification, recherche, rdaas, norme,
    géographique, professionnelle, codes.
    """
    return await client.search_classifications(query, start=start, limit=limit, lang=lang)


@tool
async def rdaas_get_classification_search_filters(lang: Lang = "en") -> SearchFilters:
    """Get the valid audience/status filter values for classification search.

    Use for: discovering what values `audience`/`status` accept before
    filtering a search.
    Keywords: statcan, rdaas, filters, search, audience, status,
    classification.
    Mots-clés : statcan, rdaas, filtres, recherche, public cible, statut,
    classification, valeurs valides.
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
    Mots-clés : statcan, classification, détail, scian, rdaas, niveaux,
    version, contexte.
    """
    return await client.get_classification(classification_id, lang=lang)


@tool
async def rdaas_get_classification_categories_detailed(
    classification_id: str, lang: Lang = "en"
) -> ClassificationCategoriesDetailed:
    """Get the detailed category tree for one classification.

    Use for: listing every code/category within a classification (e.g.
    all NAICS sectors and subsectors). Confirmed live: RDaaS itself
    returns no category data for the CURRENT released NAICS
    (2022.1.0) specifically -- retired NAICS versions and the NAICS
    Trade Variant return full data, so this is not a NAICS-wide gap.
    If you hit this empty case on current NAICS, use
    rdaas_get_concordance_maps on the "NAICS Canada 2017.3.0 to
    2022.1.0" concordance instead -- its target_code/target_descriptor
    fields are the same current-NAICS codes and descriptions.
    Keywords: statcan, classification, categories, codes, naics, rdaas,
    tree, detailed.
    Mots-clés : statcan, classification, catégories, codes, scian,
    rdaas, arborescence, détaillé.
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
    Mots-clés : statcan, exclusions, classification, rdaas, exclu,
    termes, scian, non couvert.
    """
    return await client.get_classification_exclusions(classification_id, lang=lang)


@tool
async def rdaas_get_classification_indexes(
    classification_id: str, lang: Lang = "en"
) -> ClassificationIndexes:
    """List all index entries (alternate terms mapped to a code) for one classification.

    Use for: finding which code a plain-language term maps to.
    Keywords: statcan, index, classification, rdaas, terms, alternate
    names, naics.
    Mots-clés : statcan, index, classification, rdaas, termes, noms
    alternatifs, scian, correspondance de termes.
    """
    return await client.get_classification_indexes(classification_id, lang=lang)


@tool
async def rdaas_get_classification_index_entry(
    classification_id: str, index_id: int, lang: Lang = "en"
) -> ClassificationIndexEntry:
    """Get one specific index entry by its small integer index_id (not
    its @id URL — use the indexId field from rdaas_get_classification_indexes).

    Use for: retrieving a single term-to-code mapping already identified
    via rdaas_get_classification_indexes.
    Keywords: statcan, index entry, classification, rdaas, term, code.
    Mots-clés : statcan, entrée d'index, classification, rdaas, terme,
    code, correspondance, identifiant.
    """
    return await client.get_classification_index_entry(classification_id, index_id, lang=lang)


@tool
async def rdaas_get_term_exclusion(term_exclusion_id: str, lang: Lang = "en") -> TermExclusion:
    """Get one term-exclusion record by id.

    Use for: retrieving detail on a specific excluded term identified
    elsewhere.
    Keywords: statcan, term exclusion, rdaas, excluded, definition,
    lookup, classification, reference data.
    Mots-clés : statcan, exclusion de terme, rdaas, terme exclu,
    définition, recherche, classification, données de référence.
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
    Mots-clés : statcan, concordance, correspondance, rdaas, scian,
    version, conversion, recherche.
    """
    return await client.search_concordances(query, start=start, limit=limit, lang=lang)


@tool
async def rdaas_get_concordance_search_filters(lang: Lang = "en") -> SearchFilters:
    """Get the valid audience/status filter values for concordance search.

    Use for: discovering what values `audience`/`status` accept before
    filtering a concordance search.
    Keywords: statcan, rdaas, filters, search, concordance, audience,
    status.
    Mots-clés : statcan, rdaas, filtres, recherche, concordance,
    public cible, statut, valeurs valides.
    """
    return await client.get_concordance_search_filters()


@tool
async def rdaas_get_concordance(concordance_id: str, lang: Lang = "en") -> ConcordanceDetail:
    """Get detail for one concordance: its source and target classifications.

    Use for: confirming which two classification versions a concordance
    connects before requesting its code maps.
    Keywords: statcan, concordance, detail, rdaas, source, target,
    classification.
    Mots-clés : statcan, concordance, détail, rdaas, source, cible,
    classification, connexion.
    """
    return await client.get_concordance(concordance_id, lang=lang)


@tool
async def rdaas_get_concordance_maps(concordance_id: str, lang: Lang = "en") -> CodeMapList:
    """Get the full code-to-code mapping table for one concordance.

    Use for: converting a code from one classification version to its
    equivalent(s) in another version.
    Keywords: statcan, code map, concordance, rdaas, mapping, convert,
    naics.
    Mots-clés : statcan, correspondance de codes, concordance, rdaas,
    conversion, scian, table de conversion, codes.
    """
    return await client.get_concordance_maps(concordance_id, lang=lang)
