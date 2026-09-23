"""MCP tools for Canada's provincial and municipal ArcGIS Hub open-data portals.

One tool family serves every portal via a `portal` key rather than 28
near-identical per-city tool families: the underlying API is identical
on every deployment, and a single family keeps `search_tools` results
from being crowded out by dozens of indistinguishable docstrings. The
place names in each docstring below are what lets a query like
"Ottawa bike lanes" still find these tools.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.arcgis_hub import client
from maple_data_mcp.modules.arcgis_hub.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maple_data_mcp.modules.arcgis_hub.schemas import (
    DatasetSearchResult,
    FeatureQueryResult,
    ItemDetail,
    PortalKey,
    PortalList,
)

Lang = Literal["en", "fr"]


@tool
async def arcgis_hub_list_portals(lang: Lang = "en") -> PortalList:
    """List every ArcGIS Hub open-data portal (province, city, region) and its portal key.

    Use for: finding the `portal` key the other arcgis_hub_ tools need,
    and portal-specific caveats. Covers Manitoba (mb), Saskatchewan
    (sk), Prince Edward Island (pe), Hamilton, London, Kitchener,
    Windsor, Saskatoon, Victoria, Surrey, Ottawa, Halifax, Mississauga,
    Peel, Durham, Waterloo Region, Metro Vancouver, York, Markham,
    Newmarket, Aurora, Medicine Hat, Grande Prairie, Grande Prairie
    County, St. Albert, Lethbridge, Airdrie, Strathcona County.
    Keywords: ArcGIS Hub, open data portal, municipal, city, region,
    province, GIS, geospatial, list portals.
    Mots-clés : ArcGIS Hub, portail de données ouvertes, municipal,
    ville, région, province, SIG, géospatial, liste des portails.
    """
    return client.list_portals(lang)


@tool
async def arcgis_hub_search_datasets(
    portal: PortalKey,
    query: str = "",
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetSearchResult:
    """Search one Canadian ArcGIS Hub open-data catalogue (city, region, or province).

    Use for: finding datasets by topic, tag, item type, or free-text
    query on Manitoba, Saskatchewan, Prince Edward Island, Hamilton,
    London, Kitchener, Windsor, Saskatoon, Victoria, Surrey, Ottawa,
    Halifax, Mississauga, Peel, Durham, Waterloo Region, Metro
    Vancouver, York, Markham, Newmarket, Aurora, Medicine Hat, Grande
    Prairie, Grande Prairie County, St. Albert, Lethbridge, Airdrie, or
    Strathcona County open data. Keywords: ArcGIS Hub, open data,
    dataset search, catalogue, municipal, city, region, province, GIS,
    geospatial.
    Mots-clés : ArcGIS Hub, données ouvertes, recherche de jeux de
    données, catalogue, municipal, ville, région, province, SIG,
    géospatial.
    """
    return await client.search_datasets(
        portal, query, tag=tag, item_type=item_type, limit=limit, offset=offset, lang=lang
    )


@tool
async def arcgis_hub_get_dataset(portal: PortalKey, item_id: str, lang: Lang = "en") -> ItemDetail:
    """Get one ArcGIS Hub dataset item's metadata, service URL, and download links.

    Use for: inspecting a dataset found with arcgis_hub_search_datasets
    (same `portal`) before querying its rows or downloading it — Ottawa,
    Halifax, Manitoba, Saskatchewan, PEI, and every other arcgis_hub
    portal. Keywords: ArcGIS Hub, dataset detail, FeatureServer,
    MapServer, metadata, licence, download, CSV, shapefile, GeoJSON, KML.
    Mots-clés : ArcGIS Hub, détail du jeu de données, FeatureServer,
    MapServer, métadonnées, licence, téléchargement, CSV, shapefile,
    GeoJSON, KML.
    """
    return await client.get_dataset(portal, item_id, lang)


@tool
async def arcgis_hub_query_feature_layer(
    portal: PortalKey,
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
    """Query rows from one ArcGIS Hub dataset's FeatureServer/MapServer layer.

    Use for: reading actual feature attribute values (not just
    metadata) from a dataset found with arcgis_hub_search_datasets,
    filtering with an ArcGIS SQL `where` clause, sorting, or including
    geometry. Leave layer_index unset to auto-resolve the item's own
    layer, or the service's first layer or table id (not always 0).
    Keywords: ArcGIS REST, FeatureServer, MapServer, query, rows,
    attributes, filter, where clause, municipal, geospatial, GIS.
    Mots-clés : ArcGIS REST, FeatureServer, MapServer, requête,
    lignes, attributs, filtre, clause where, municipal, géospatial, SIG.
    """
    return await client.query_feature_layer(
        portal,
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
