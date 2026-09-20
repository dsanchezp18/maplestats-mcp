"""MCP tools for the City of Ottawa's ArcGIS Hub open-data portal."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.arcgis_ottawa import client
from maple_data_mcp.modules.arcgis_ottawa.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maple_data_mcp.modules.arcgis_ottawa.schemas import (
    DatasetSearchResult,
    FeatureQueryResult,
    ItemDetail,
)

Lang = Literal["en", "fr"]


@tool
async def arcgis_ottawa_search_datasets(
    query: str = "",
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search Ottawa's ArcGIS Hub open-data catalogue (Ottawa Open Data).

    Use for: finding Ottawa datasets by topic, tag, item type, or
    free-text query. Keywords: Ottawa, Ottawa Open Data, ArcGIS
    Hub, open data, dataset search, catalogue, government, municipal,
    GIS, geospatial.
    Mots-clés : Ottawa, Ottawa Open Data, ArcGIS Hub,
    données ouvertes, recherche de jeux de données, catalogue,
    gouvernement, municipal, SIG, géospatial.
    """
    return await client.search_datasets(
        query, tag=tag, item_type=item_type, limit=limit, offset=offset, lang=lang
    )


@tool
async def arcgis_ottawa_get_dataset(item_id: str, lang: Lang = "en") -> ItemDetail:
    """Get one Ottawa dataset item's metadata, service URL, and download links.

    Use for: inspecting a dataset found with arcgis_ottawa_search_datasets
    before querying its rows or downloading it. Keywords: Ottawa,
    Ottawa Open Data, ArcGIS Hub, dataset detail, FeatureServer, MapServer,
    metadata, licence, download, CSV, shapefile, GeoJSON, KML.
    Mots-clés : Ottawa, Ottawa Open Data, ArcGIS Hub, détail
    du jeu de données, FeatureServer, MapServer, métadonnées, licence,
    téléchargement, CSV, shapefile, GeoJSON, KML.
    """
    return await client.get_dataset(item_id, lang)


@tool
async def arcgis_ottawa_query_feature_layer(
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
    """Query rows from one Ottawa FeatureServer/MapServer layer.

    Use for: reading actual feature attribute values (not just
    metadata) from a dataset found with arcgis_ottawa_search_datasets,
    filtering with an ArcGIS SQL `where` clause, sorting, or including
    geometry. Leave layer_index unset to auto-resolve the service's own
    first layer or table id (not always 0). Keywords: Ottawa, Ottawa Open Data,
    ArcGIS REST, FeatureServer, MapServer, query, rows, attributes,
    filter, where clause, geospatial, GIS.
    Mots-clés : Ottawa, Ottawa Open Data, ArcGIS REST,
    FeatureServer, MapServer, requête, lignes, attributs, filtre,
    clause where, géospatial, SIG.
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
