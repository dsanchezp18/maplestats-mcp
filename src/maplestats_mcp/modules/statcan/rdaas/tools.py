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
    audience: list[str] | None = None,
    status: list[str] | None = None,
    lang: Lang = "en",
) -> ClassificationSearchResult:
    """Search StatCan's classifications (e.g. NAICS, the Standard
    Geographical Classification, occupational classifications).

    Use for: finding the classification id for a topic before requesting
    its full detail, categories, or concordances. `audience` and `status`
    (lists) filter results; valid values come from rdaas_get_search_filters
    (e.g. status ["RELEASED"] for current versions only).
    Keywords: statcan, naics, classification, search, rdaas, standard,
    geographical, occupational, codes, NOC, national occupational
    classification, occupation, SOC, industry classification.
    Mots-clés : Statistique Canada, classification, recherche, SCIAN, codes
    SCIAN, Système de classification des industries de l'Amérique du Nord,
    CNP, codes de professions, Classification nationale des professions,
    Classification géographique type, CGT, norme de classification,
    profession, métier.
    """
    return await client.search_classifications(
        query, start=start, limit=limit, audience=audience, status=status, lang=lang
    )


@tool
async def rdaas_get_search_filters(
    kind: Literal["classification", "concordance"], lang: Lang = "en"
) -> SearchFilters:
    """Get the valid audience/status filter values for classification or
    concordance search (`kind`).

    Use for: discovering what values `audience`/`status` accept; pass
    them as the `audience`/`status` arguments of rdaas_search_classifications
    or rdaas_search_concordances.
    Keywords: statcan, rdaas, filters, search, audience, status,
    classification, concordance, Statistics Canada.
    Mots-clés : Statistique Canada, filtres de recherche, public cible,
    statut, classification, concordance, valeurs valides, critères de
    recherche, normes statistiques.
    """
    if kind == "concordance":
        return await client.get_concordance_search_filters()
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
    Mots-clés : Statistique Canada, classification, détail, SCIAN, CNP,
    niveaux hiérarchiques, version, structure de la classification, norme
    statistique.
    """
    return await client.get_classification(classification_id, lang=lang)


@tool
async def rdaas_get_classification_categories_detailed(
    classification_id: str,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
    lang: Lang = "en",
) -> ClassificationCategoriesDetailed:
    """Get the detailed category tree for one classification.

    Use for: listing every code/category within a classification (e.g.
    all NAICS sectors and subsectors). Paged: `limit` (default 100, max
    1000) and `offset`; `query` keeps categories whose code or descriptor
    contains the text. total_count and provenance.limits say what was left
    out. Confirmed live: RDaaS itself
    returns no category data for the CURRENT released NAICS
    (2022.1.0) specifically -- retired NAICS versions and the NAICS
    Trade Variant return full data, so this is not a NAICS-wide gap.
    If you hit this empty case on current NAICS, use
    rdaas_get_concordance_maps on the "NAICS Canada 2017.3.0 to
    2022.1.0" concordance instead -- its target_code/target_descriptor
    fields are the same current-NAICS codes and descriptions.
    Keywords: statcan, classification, categories, codes, naics, rdaas,
    tree, detailed.
    Mots-clés : Statistique Canada, classification, catégories, codes,
    SCIAN, CNP, arborescence, hiérarchie, liste détaillée des codes.
    """
    return await client.get_classification_categories_detailed(
        classification_id, lang=lang, query=query, limit=limit, offset=offset
    )


@tool
async def rdaas_get_classification_exclusions(
    classification_id: str, lang: Lang = "en"
) -> ClassificationExclusions:
    """Get documented exclusions (terms explicitly NOT covered) for one classification.

    Use for: checking whether a term is deliberately excluded from a
    classification rather than simply missing.
    Keywords: statcan, exclusions, classification, rdaas, excluded, terms,
    naics, Statistics Canada.
    Mots-clés : Statistique Canada, exclusions, classification, termes
    exclus, activités exclues, SCIAN, CNP, non couvert.
    """
    return await client.get_classification_exclusions(classification_id, lang=lang)


@tool
async def rdaas_get_classification_indexes(
    classification_id: str,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
    lang: Lang = "en",
) -> ClassificationIndexes:
    """List all index entries (alternate terms mapped to a code) for one classification.

    Use for: finding which code a plain-language term maps to. Pass
    `query` (matches the term or the code description) -- the NAICS 2022
    index has tens of thousands of entries (8 MB), so the list is paged:
    `limit` (default 100, max 1000) and `offset`; total_count and
    provenance.limits say what was left out.
    Keywords: statcan, index, classification, rdaas, terms, alternate names,
    naics, Statistics Canada.
    Mots-clés : Statistique Canada, index, classification, termes,
    appellations, titres d'index, SCIAN, CNP, correspondance de termes.
    """
    return await client.get_classification_indexes(
        classification_id, lang=lang, query=query, limit=limit, offset=offset
    )


@tool
async def rdaas_get_classification_index_entry(
    classification_id: str, index_id: int, lang: Lang = "en"
) -> ClassificationIndexEntry:
    """Get one specific index entry by its small integer index_id (not
    its @id URL — use the indexId field from rdaas_get_classification_indexes).

    Use for: retrieving a single term-to-code mapping already identified
    via rdaas_get_classification_indexes.
    Keywords: statcan, index entry, classification, rdaas, term, code,
    Statistics Canada, NAICS.
    Mots-clés : Statistique Canada, entrée d'index, titre d'index,
    classification, terme, code, correspondance, identifiant, appellation.
    """
    return await client.get_classification_index_entry(classification_id, index_id, lang=lang)


@tool
async def rdaas_get_term_exclusion(term_exclusion_id: str, lang: Lang = "en") -> TermExclusion:
    """Get one term-exclusion record by id.

    Use for: retrieving detail on a specific excluded term identified
    elsewhere.
    Keywords: statcan, term exclusion, rdaas, excluded, definition,
    lookup, classification, reference data.
    Mots-clés : Statistique Canada, exclusion de terme, terme exclu,
    activité exclue, définition, recherche, classification, données de
    référence.
    """
    return await client.get_term_exclusion(term_exclusion_id, lang=lang)


@tool
async def rdaas_search_concordances(
    query: str = "",
    start: int = 0,
    limit: int = 10,
    audience: list[str] | None = None,
    status: list[str] | None = None,
    lang: Lang = "en",
) -> ConcordanceSearchResult:
    """Search StatCan's concordances: correspondence tables between two
    classification versions (e.g. NAICS 2012 to NAICS 2017).

    Use for: finding a concordance id before requesting its code maps.
    `audience` and `status` (lists) filter results; valid values come from
    rdaas_get_search_filters.
    Keywords: statcan, concordance, correspondence, rdaas, naics, version,
    mapping, Statistics Canada.
    Mots-clés : Statistique Canada, concordance, tableau de correspondance,
    SCIAN, version, conversion de codes, recherche, passage entre versions.
    """
    return await client.search_concordances(
        query, start=start, limit=limit, audience=audience, status=status, lang=lang
    )


@tool
async def rdaas_get_concordance(concordance_id: str, lang: Lang = "en") -> ConcordanceDetail:
    """Get detail for one concordance: its source and target classifications.

    Use for: confirming which two classification versions a concordance
    connects before requesting its code maps.
    Keywords: statcan, concordance, detail, rdaas, source, target,
    classification, Statistics Canada.
    Mots-clés : Statistique Canada, concordance, détail, classification
    source, classification cible, correspondance, versions, SCIAN.
    """
    return await client.get_concordance(concordance_id, lang=lang)


@tool
async def rdaas_get_concordance_maps(concordance_id: str, lang: Lang = "en") -> CodeMapList:
    """Get the full code-to-code mapping table for one concordance.

    Use for: converting a code from one classification version to its
    equivalent(s) in another version.
    Keywords: statcan, code map, concordance, rdaas, mapping, convert,
    naics, Statistics Canada.
    Mots-clés : Statistique Canada, correspondance de codes, concordance,
    conversion, SCIAN, table de conversion, codes, passage d'une version à
    l'autre.
    """
    return await client.get_concordance_maps(concordance_id, lang=lang)
