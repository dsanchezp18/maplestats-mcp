"""MCP tools for Canada's Socrata (SODA) open-data portals.

One tool family serves every portal via a `portal` key; see
modules/arcgis_hub/tools.py for why per-portal tool families were
collapsed.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.socrata import client
from maplestats_mcp.modules.socrata.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maplestats_mcp.modules.socrata.schemas import (
    CategoryList,
    DatasetDetail,
    DatasetSearchResult,
    PortalKey,
    PortalList,
    RowQueryResult,
    TagList,
)

Lang = Literal["en", "fr"]


@tool
async def socrata_list_portals(lang: Lang = "en") -> PortalList:
    """List every Socrata open-data portal and its portal key.

    Use for: finding the `portal` key other socrata_ tools need — Nova
    Scotia (ns), New Brunswick (nb), Calgary, Edmonton, Winnipeg.
    Keywords: Socrata, SODA, open data portal, Nova Scotia, New
    Brunswick, Calgary, Edmonton, Winnipeg, list portals.
    Mots-clés : Socrata, SODA, portail de données ouvertes,
    Nouvelle-Écosse, Nouveau-Brunswick, Calgary, Edmonton, Winnipeg,
    liste des portails.
    """
    return client.list_portals(lang)


@tool
async def socrata_search_datasets(
    portal: PortalKey,
    query: str = "",
    category: str | None = None,
    tag: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search a Socrata open-data catalogue (Nova Scotia, New Brunswick, Calgary, Edmonton, Winnipeg).

    Use for: finding datasets by topic, category, tag, or free-text
    query. Keywords: Nova Scotia, New Brunswick, Calgary, Edmonton,
    Winnipeg, open data, Socrata, dataset search, catalogue,
    government, province, city, category, tags.
    Mots-clés : Nouvelle-Écosse, Nouveau-Brunswick, Calgary, Edmonton,
    Winnipeg, données ouvertes, Socrata, recherche de jeux de données,
    catalogue, gouvernement, province, ville, catégorie, étiquettes.
    """
    return await client.search_datasets(
        portal, query, category=category, tag=tag, limit=limit, offset=offset, lang=lang
    )


@tool
async def socrata_get_dataset(
    portal: PortalKey, dataset_id: str, lang: Lang = "en"
) -> DatasetDetail:
    """Get one Socrata dataset's metadata, columns, and download links.

    Use for: inspecting a dataset found with socrata_search_datasets
    (same `portal`) before querying its rows. Keywords: Socrata,
    dataset detail, columns, metadata, licence, publisher, download,
    CSV, views, Nova Scotia, New Brunswick, Calgary, Edmonton, Winnipeg.
    Mots-clés : Socrata, détail du jeu de données, colonnes,
    métadonnées, licence, éditeur, téléchargement, CSV, vues.
    """
    return await client.get_dataset(portal, dataset_id, lang)


@tool
async def socrata_query_dataset_rows(
    portal: PortalKey,
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    q: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RowQueryResult:
    """Query rows from one Socrata dataset with a SoQL clause.

    Use for: reading actual data values (not just metadata) from a
    dataset found with socrata_search_datasets, filtering with a SoQL
    $where clause, sorting, or full-text search within the dataset.
    Keywords: Socrata, SODA, SoQL, rows, query, filter, data, select,
    where, order, resource API.
    Mots-clés : Socrata, SODA, SoQL, lignes, requête, filtrer, données,
    sélection, tri, recherche dans les données.
    """
    return await client.query_dataset_rows(
        portal,
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
async def socrata_list_categories(portal: PortalKey, lang: Lang = "en") -> CategoryList:
    """List one Socrata portal's dataset categories and how many datasets each has.

    Use for: discovering topic categories before filtering search.
    Keywords: Socrata, categories, domain_category, catalogue, open data,
    topics, classification, themes.
    Mots-clés : Socrata, catégories, domaine, catalogue, données ouvertes,
    sujets, classification, thèmes.
    """
    return await client.list_categories(portal, lang)


@tool
async def socrata_list_tags(portal: PortalKey, lang: Lang = "en") -> TagList:
    """List one Socrata portal's free-text dataset tags and how many datasets each has.

    Use for: discovering exact tag values for the search tag filter.
    Keywords: Socrata, tags, domain_tags, keywords, vocabulary,
    catalogue, search, discover.
    Mots-clés : Socrata, étiquettes, mots-clés, vocabulaire, catalogue,
    recherche, découvrir, terminologie.
    """
    return await client.list_tags(portal, lang)
