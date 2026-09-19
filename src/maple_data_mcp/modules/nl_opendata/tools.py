"""MCP tools for Open Data Newfoundland and Labrador."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.nl_opendata import client
from maple_data_mcp.modules.nl_opendata.constants import SEARCH_LIMIT_DEFAULT
from maple_data_mcp.modules.nl_opendata.schemas import DatasetDetail, DatasetSearchResult, TagList

Lang = Literal["en", "fr"]
DatasetType = Literal["all", "tabular", "spatial"]
SortOrder = Literal["name", "released_desc", "released_asc"]


@tool
async def nl_opendata_search_datasets(
    query: str = "",
    dataset_type: DatasetType = "all",
    tag_id: str | None = None,
    sort: SortOrder = "name",
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search Newfoundland and Labrador's official open-data catalogue.

    Use for: finding tabular or spatial datasets by title, publisher, creator,
    or a known topic-tag id. The upstream catalogue has no JSON search API or
    server-side pagination, so MapleData fetches its small HTML listings and
    applies text filtering and offset/limit pagination locally. Use
    nl_opendata_list_tags first when a topic tag id is needed. Keywords:
    Newfoundland, Labrador, NL, open data, dataset search, catalogue, tabular,
    spatial, geospatial, government, CSV, XLS, KMZ, shapefile, topic tag.
    Mots-clés: Terre-Neuve, Labrador, données ouvertes, recherche de jeux de
    données, catalogue, tabulaire, spatial, géospatial, gouvernement, CSV, XLS,
    KMZ, shapefile, mot-clé thématique.
    """
    return await client.search_datasets(
        query,
        dataset_type=dataset_type,
        tag_id=tag_id,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def nl_opendata_get_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDetail:
    """Get full metadata and official file links for one Newfoundland and Labrador dataset.

    Use for: inspecting a dataset found with nl_opendata_search_datasets,
    reading its creator, publisher, geography, time coverage, release and
    modification dates, rights, topics, revisions, formats, file sizes, and
    binary download URLs. Keywords: Newfoundland, Labrador, open data,
    dataset details, metadata, creator, publisher, geography, time coverage,
    rights, licence, topic, revision, format, file, download, CSV, XLS, KMZ.
    Mots-clés: Terre-Neuve, Labrador, données ouvertes, détail du jeu de
    données, métadonnées, créateur, éditeur, géographie, période, droits,
    licence, sujet, révision, format, fichier, téléchargement, CSV, XLS, KMZ.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def nl_opendata_list_tags(lang: Lang = "en") -> TagList:
    """List topic tags exposed by Newfoundland and Labrador's Explore page.

    Use for: discovering the portal's tag ids before calling
    nl_opendata_search_datasets with tag_id. Keywords: Newfoundland, Labrador,
    open data, topic tags, keywords, vocabulary, catalogue, Explore, filter,
    demographics, health, justice, transportation, environment.
    Mots-clés: Terre-Neuve, Labrador, données ouvertes, mots-clés thématiques,
    vocabulaire, catalogue, explorer, filtre, démographie, santé, justice,
    transport, environnement.
    """
    return await client.list_tags(lang)
