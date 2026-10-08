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

from maplestats_mcp.modules.arcgis_hub import client
from maplestats_mcp.modules.arcgis_hub.constants import ROWS_LIMIT_DEFAULT, SEARCH_LIMIT_DEFAULT
from maplestats_mcp.modules.arcgis_hub.schemas import (
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
    and portal-specific caveats. Covers Manitoba (mb), Prince Edward Island (pe), London, Kitchener,
    Windsor, Saskatoon, Victoria, Surrey, Ottawa, Halifax, Mississauga,
    Peel, Durham, Waterloo Region, Metro Vancouver, York, Markham,
    Newmarket, Aurora, Medicine Hat, Grande Prairie, Grande Prairie
    County, St. Albert, Lethbridge, Airdrie, Strathcona County, Parkland
    County, Sturgeon County, Edmonton Metropolitan Region Board, Alberta
    Geological Survey, Red Deer, Cochrane, Okotoks, Oakville, Burlington,
    Milton, Brampton, Kingston, Kelowna, Barrie, Burnaby, Fredericton,
    Greater Sudbury, Guelph, Moncton, Abbotsford, Whitby, Oshawa, Niagara
    Falls, Niagara Region, St. Catharines, Thunder Bay, Peterborough,
    Coquitlam, Saanich, Kamloops, Prince George, Delta, Yellowknife,
    Cambridge, Maple Ridge, Pickering, Sarnia, Saint John, Port Moody,
    White Rock, Penticton, Orangeville, Canmore, BC Energy Regulator,
    Toronto Police Service, Ottawa Police Service, Conservation Halton,
    Credit Valley, Niagara Peninsula, Hamilton and Central Lake Ontario
    conservation authorities, Quinte Conservation, Ontario GeoHub (Land
    Information Ontario) and Parks Canada.
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
    query (zoning, trails, parks, police shootings, crime, roads,
    addresses, boundaries) on a city, region, province, police service,
    conservation authority or federal agency portal: see
    arcgis_hub_list_portals for the full list (Ottawa, Toronto Police,
    Parks Canada, Yellowknife, Manitoba, Halifax, Surrey, Burnaby,
    Kelowna and more). Offset plus limit stops at 10,000.
    Keywords: ArcGIS Hub, open data, dataset search, catalogue,
    municipal, city, region, province, GIS, geospatial, zoning, trails.
    Mots-clés : ArcGIS Hub, données ouvertes, recherche de jeux de
    données, catalogue, municipal, ville, région, province, SIG,
    géospatial, zonage, sentiers.
    """
    return await client.search_datasets(
        portal, query, tag=tag, item_type=item_type, limit=limit, offset=offset, lang=lang
    )


@tool
async def arcgis_hub_get_dataset(portal: PortalKey, item_id: str, lang: Lang = "en") -> ItemDetail:
    """Get one ArcGIS Hub dataset item's metadata, service URL, and download links.

    Use for: inspecting a dataset found with arcgis_hub_search_datasets
    (same `portal`) before querying its rows or downloading it — Ottawa,
    Halifax, Manitoba, PEI, and every other arcgis_hub portal. Download
    links depend on the item: export links in the formats the service
    allows, one stored-file link for a file item, none for an Image
    Service. Keywords: ArcGIS Hub, dataset detail, FeatureServer,
    MapServer, metadata, licence, download, CSV, shapefile, GeoJSON, KML.
    Mots-clés : fiche d'un jeu de données, description d'une couche,
    métadonnées, URL du service FeatureServer, MapServer, licence
    d'utilisation, liens de téléchargement, exporter en CSV, shapefile,
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
