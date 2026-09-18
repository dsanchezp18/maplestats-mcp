"""MCP tools for Saskatchewan GeoHub."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.arcgis_sk import client
from maple_data_mcp.modules.arcgis_sk.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maple_data_mcp.modules.arcgis_sk.schemas import (
    DatasetSearchResult,
    FeatureQueryResult,
    ItemDetail,
)

Lang = Literal["en", "fr"]


@tool
async def arcgis_sk_search_datasets(
    query: str = "",
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search Saskatchewan's ArcGIS Hub open-data catalogue (Saskatchewan GeoHub).

    Use for: finding Saskatchewan datasets by topic, tag, item type, or
    free-text query. Keywords: Saskatchewan, Saskatchewan GeoHub, geoportal, ArcGIS
    Hub, open data, dataset search, catalogue, government, province,
    GIS, geospatial.
    """
    return await client.search_datasets(
        query, tag=tag, item_type=item_type, limit=limit, offset=offset, lang=lang
    )


@tool
async def arcgis_sk_get_dataset(item_id: str, lang: Lang = "en") -> ItemDetail:
    """Get one Saskatchewan dataset item's metadata, service URL, and download links.

    Use for: inspecting a dataset found with arcgis_sk_search_datasets
    before querying its rows or downloading it. Keywords: Saskatchewan,
    Saskatchewan GeoHub, ArcGIS Hub, dataset detail, FeatureServer, MapServer,
    metadata, licence, download, CSV, shapefile, GeoJSON, KML.
    """
    return await client.get_dataset(item_id, lang)


@tool
async def arcgis_sk_query_feature_layer(
    item_id: str,
    layer_index: int | None = None,
    where: str | None = None,
    out_fields: str = "*",
    order_by: str | None = None,
    return_geometry: bool = False,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FeatureQueryResult:
    """Query rows from one Saskatchewan FeatureServer/MapServer layer.

    Use for: reading actual feature attribute values (not just
    metadata) from a dataset found with arcgis_sk_search_datasets,
    filtering with an ArcGIS SQL `where` clause, sorting, or including
    geometry. Leave layer_index unset to auto-resolve the service's own
    first layer or table id (not always 0). Keywords: Saskatchewan, Saskatchewan GeoHub,
    ArcGIS REST, FeatureServer, MapServer, query, rows, attributes,
    filter, where clause, geospatial, GIS.
    """
    return await client.query_feature_layer(
        item_id,
        layer_index=layer_index,
        where=where,
        out_fields=out_fields,
        order_by=order_by,
        return_geometry=return_geometry,
        limit=limit,
        offset=offset,
        lang=lang,
    )
