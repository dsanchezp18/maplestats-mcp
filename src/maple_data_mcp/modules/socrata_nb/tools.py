"""MCP tools for Open Data New Brunswick."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.socrata_nb import client
from maple_data_mcp.modules.socrata_nb.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maple_data_mcp.modules.socrata_nb.schemas import (
    CategoryList,
    DatasetDetail,
    DatasetSearchResult,
    RowQueryResult,
    TagList,
)

Lang = Literal["en", "fr"]


@tool
async def socrata_nb_search_datasets(
    query: str = "",
    category: str | None = None,
    tag: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search New Brunswick's open-data catalogue.

    Use for: finding New Brunswick datasets by topic, category, tag, or
    free-text query. Keywords: New Brunswick, open data, Socrata, dataset
    search, catalogue, government, province, category, tags, discovery.
    Mots-clés: Nouveau-Brunswick, données ouvertes, Socrata, recherche
    de jeux de données, catalogue, gouvernement, province, catégorie,
    étiquettes, découverte.
    """
    return await client.search_datasets(
        query, category=category, tag=tag, limit=limit, offset=offset, lang=lang
    )


@tool
async def socrata_nb_get_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDetail:
    """Get one New Brunswick dataset's metadata, columns, and download links.

    Use for: inspecting a dataset found with socrata_nb_search_datasets
    before querying its rows. Keywords: New Brunswick, Socrata, dataset
    detail, columns, metadata, licence, publisher, download, CSV, views.
    Mots-clés: Nouveau-Brunswick, Socrata, détail du jeu de données,
    colonnes, métadonnées, licence, éditeur, téléchargement, CSV,
    vues.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def socrata_nb_query_dataset_rows(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    q: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RowQueryResult:
    """Query rows from one New Brunswick dataset with a SoQL clause.

    Use for: reading actual data values (not just metadata) from a
    dataset found with socrata_nb_search_datasets, filtering with a
    SoQL $where clause, sorting, or full-text search within the
    dataset. Keywords: New Brunswick, Socrata, SODA, SoQL, rows, query,
    filter, data, select, where, order, resource API.
    Mots-clés: Nouveau-Brunswick, Socrata, SODA, SoQL, lignes, requête,
    filtrer, données, sélection, tri, recherche dans les données,
    Resource API.
    """
    return await client.query_dataset_rows(
        dataset_id,
        select=select,
        where=where,
        order=order,
        q=q,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def socrata_nb_list_categories(lang: Lang = "en") -> CategoryList:
    """List New Brunswick's dataset categories and how many datasets each has.

    Use for: discovering topic categories before filtering search.
    Keywords: New Brunswick, Socrata, categories, domain_category,
    catalogue, open data, topics, classification.
    Mots-clés: Nouveau-Brunswick, Socrata, catégories, domaine, catalogue,
    données ouvertes, sujets, classification, thèmes.
    """
    return await client.list_categories(lang)


@tool
async def socrata_nb_list_tags(lang: Lang = "en") -> TagList:
    """List New Brunswick's free-text dataset tags and how many datasets each has.

    Use for: discovering exact tag values for the search tag filter.
    Keywords: New Brunswick, Socrata, tags, domain_tags, keywords,
    vocabulary, catalogue, search, discover.
    Mots-clés: Nouveau-Brunswick, Socrata, étiquettes, mots-clés,
    vocabulaire, catalogue, recherche, découvrir, terminologie.
    """
    return await client.list_tags(lang)
