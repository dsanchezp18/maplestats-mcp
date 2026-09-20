"""MCP tools for the City of Vancouver's Opendatasoft open-data portal."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.opendatasoft_vancouver import client
from maple_data_mcp.modules.opendatasoft_vancouver.constants import (
    RECORDS_LIMIT_DEFAULT,
    SEARCH_LIMIT_DEFAULT,
)
from maple_data_mcp.modules.opendatasoft_vancouver.schemas import (
    DatasetDetail,
    DatasetSearchResult,
    RecordQueryResult,
)

Lang = Literal["en", "fr"]


@tool
async def opendatasoft_vancouver_search_datasets(
    query: str = "",
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search Vancouver's Opendatasoft open-data catalogue.

    Use for: finding City of Vancouver datasets by topic or free-text
    query. Keywords: Vancouver, Opendatasoft, open data, dataset
    search, catalogue, government, municipal, British Columbia,
    discovery.
    Mots-clés : Vancouver, Opendatasoft, données ouvertes, recherche
    de jeux de données, catalogue, gouvernement, municipal,
    Colombie-Britannique, découverte.
    """
    return await client.search_datasets(query, limit=limit, offset=offset, lang=lang)


@tool
async def opendatasoft_vancouver_get_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDetail:
    """Get one Vancouver dataset's metadata, fields, and download links.

    Use for: inspecting a dataset found with
    opendatasoft_vancouver_search_datasets before querying its records
    or downloading it. Keywords: Vancouver, Opendatasoft, dataset
    detail, fields, metadata, licence, publisher, download, CSV, JSON,
    GeoJSON.
    Mots-clés : Vancouver, Opendatasoft, détail du jeu de données,
    champs, métadonnées, licence, éditeur, téléchargement, CSV, JSON,
    GeoJSON.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def opendatasoft_vancouver_query_records(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order_by: str | None = None,
    query: str | None = None,
    limit: int = RECORDS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RecordQueryResult:
    """Query records from one Vancouver dataset with ODSQL filtering/sorting.

    Use for: reading actual data values (not just metadata) from a
    dataset found with opendatasoft_vancouver_search_datasets, filtering
    with a raw ODSQL `where` clause (e.g. "service_category_1 =
    'Housing'"), sorting with `order_by`, or a full-text `query` match
    within the dataset's own fields. Keywords: Vancouver, Opendatasoft,
    ODSQL, records, query, filter, rows, data, select, where, order,
    Explore API.
    Mots-clés : Vancouver, Opendatasoft, ODSQL, enregistrements,
    requête, filtrer, lignes, données, sélection, tri, Explore API.
    """
    return await client.query_records(
        dataset_id,
        select=select,
        where=where,
        order_by=order_by,
        query=query,
        limit=limit,
        offset=offset,
        lang=lang,
    )
