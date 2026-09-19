"""MCP tools for the City of Edmonton Open Data portal."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.socrata_edmonton import client
from maple_data_mcp.modules.socrata_edmonton.constants import (
    ROWS_LIMIT_DEFAULT,
    SEARCH_LIMIT_DEFAULT,
)
from maple_data_mcp.modules.socrata_edmonton.schemas import (
    CategoryList,
    DatasetDetail,
    DatasetSearchResult,
    RowQueryResult,
    TagList,
)

Lang = Literal["en", "fr"]


@tool
async def socrata_edmonton_search_datasets(
    query: str = "",
    category: str | None = None,
    tag: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search Edmonton's open-data catalogue.

    Use for: finding City of Edmonton datasets by topic, category, tag,
    or free-text query. Keywords: Edmonton, Alberta, open data, Socrata,
    dataset search, catalogue, municipal, city, category, tags,
    discovery.
    Mots-clés: Edmonton, Alberta, données ouvertes, Socrata, recherche
    de jeux de données, catalogue, municipal, ville, catégorie,
    étiquettes, découverte.
    """
    return await client.search_datasets(
        query, category=category, tag=tag, limit=limit, offset=offset, lang=lang
    )


@tool
async def socrata_edmonton_get_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDetail:
    """Get one Edmonton dataset's metadata, columns, and download links.

    Use for: inspecting a dataset found with
    socrata_edmonton_search_datasets before querying its rows. Keywords:
    Edmonton, Alberta, Socrata, dataset detail, columns, metadata,
    licence, publisher, download, CSV, views.
    Mots-clés: Edmonton, Alberta, Socrata, détail du jeu de données,
    colonnes, métadonnées, licence, éditeur, téléchargement, CSV,
    vues.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def socrata_edmonton_query_dataset_rows(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    q: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RowQueryResult:
    """Query rows from one Edmonton dataset with a SoQL clause.

    Use for: reading actual data values (not just metadata) from a
    dataset found with socrata_edmonton_search_datasets, filtering with
    a SoQL $where clause, sorting, or full-text search within the
    dataset - e.g. traffic incidents, building permits, crime
    statistics, transit data. Keywords: Edmonton, Alberta, Socrata,
    SODA, SoQL, rows, query, filter, data, select, where, order,
    resource API.
    Mots-clés: Edmonton, Alberta, Socrata, SODA, SoQL, lignes, requête,
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
async def socrata_edmonton_list_categories(lang: Lang = "en") -> CategoryList:
    """List Edmonton's dataset categories and how many datasets each has.

    Use for: discovering topic categories before filtering search.
    Keywords: Edmonton, Alberta, Socrata, categories, domain_category,
    catalogue, open data, topics, classification.
    Mots-clés: Edmonton, Alberta, Socrata, catégories, domaine,
    catalogue, données ouvertes, sujets, classification, thèmes.
    """
    return await client.list_categories(lang)


@tool
async def socrata_edmonton_list_tags(lang: Lang = "en") -> TagList:
    """List Edmonton's free-text dataset tags and how many datasets each has.

    Use for: discovering exact tag values for the search tag filter.
    Keywords: Edmonton, Alberta, Socrata, tags, domain_tags, keywords,
    vocabulary, catalogue, search, discover.
    Mots-clés: Edmonton, Alberta, Socrata, étiquettes, mots-clés,
    vocabulaire, catalogue, recherche, découvrir, terminologie.
    """
    return await client.list_tags(lang)
