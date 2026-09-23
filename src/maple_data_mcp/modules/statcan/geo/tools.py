"""MCP tools for StatCan's geo.statcan.gc.ca ArcGIS REST census-geography service."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.geo import client, constants
from maple_data_mcp.modules.statcan.geo.schemas import (
    GeoLayerDetail,
    GeoQueryResult,
    GeoServiceList,
)

Lang = Literal["en", "fr"]


@tool
async def statcan_geo_list_services(year: str, lang: Lang = "en") -> GeoServiceList:
    """List StatCan's census-geography boundary services for one year.

    Use for: discovering what geography boundary products exist for a
    given year before drilling into a service's layers. A census year
    (e.g. "2021") publishes a full suite (Cartographic/Digital boundary
    files, Agricultural/Population ecumene boundary files, Road
    Network File, each in English and French) with every geography
    level; an intercensal year publishes only a smaller CSD-level
    update and the Road Network File -- this genuinely varies year to
    year and is discovered live, not hardcoded. Years 2019-2025
    confirmed live; nothing older is served here (use
    statcan_census_profile_archive_* for older bulk boundary/data
    downloads instead). Only the `lang` edition of each product is
    listed: French services (e.g. "Fichiers_des_limites_cartographiques")
    carry French layer names and field aliases.
    Keywords: statcan, geography, boundary files, geospatial, arcgis,
    census geography, cartographic, digital boundary file.
    Mots-clés : statcan, géographie, fichiers de limites, géospatial,
    arcgis, géographie du recensement, limites cartographiques,
    fichier numérique des limites.
    """
    return await client.list_services(year, lang)


@tool
async def statcan_geo_get_layer_detail(
    year: str, service: str, layer_id: int, lang: Lang = "en"
) -> GeoLayerDetail:
    """Get one geography layer's field schema, geometry type, and record cap.

    Use for: inspecting a layer's queryable fields (e.g. CSDUID, DGUID,
    CSDNAME, PRUID) and its maxRecordCount before calling
    statcan_geo_query_layer -- `service` is a name from
    statcan_geo_list_services (e.g. "Cartographic_boundary_files"),
    `layer_id` a small integer identifying one geography level within
    that service (e.g. layer 9 = CSD, layer 12 = DA for 2021's
    Cartographic boundary files -- layer numbering is not fixed across
    years/services and should be discovered, not assumed). The language
    comes from `service` itself, so `lang` has no effect here.
    Keywords: statcan, geography, layer, schema, fields, arcgis,
    boundary file, geometry type.
    Mots-clés : statcan, géographie, couche, schéma, champs, arcgis,
    fichier de limites, type de géométrie.
    """
    del lang
    return await client.get_layer_detail(year, service, layer_id)


@tool
async def statcan_geo_query_layer(
    year: str,
    service: str,
    layer_id: int,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = False,
    out_sr: int = constants.DEFAULT_OUT_SR,
    result_offset: int = 0,
    result_record_count: int = constants.QUERY_RECORD_COUNT_DEFAULT,
    lang: Lang = "en",
) -> GeoQueryResult:
    """Query one geography layer's features by attribute, optionally with geometry.

    Use for: finding a geography's DGUID/UID by name (e.g.
    `where="CSDNAME='Toronto'"`), or retrieving boundary polygons for
    mapping. `where` is a standard SQL-style predicate against the
    layer's own field names from statcan_geo_get_layer_detail (e.g.
    "PRUID='35' AND CSDNAME LIKE '%Toronto%'"); leave the default
    "1=1" to match every feature in the layer. Leave `return_geometry`
    false (the default) for a lightweight attribute-only query --
    polygon boundaries can be large, and most lookups only need the
    UID/DGUID/name columns. When `return_geometry` is true, geometry
    is reprojected to `out_sr` (WGS84 lat/lon, EPSG:4326, by default --
    the service's native spatial reference is EPSG:3347, Statistics
    Canada Lambert). Each layer enforces its own maxRecordCount as a
    hard per-request cap regardless of `result_record_count` (6000
    confirmed for 2021's Cartographic boundary layers); check
    `exceeded_transfer_limit` on the result and page further with
    `result_offset` if more features remain. Confirmed live: this host
    intermittently returns HTTP 500 on an otherwise-valid request
    (roughly one in three to five calls, a load-balanced backend with
    some unhealthy nodes) -- already mitigated by this client's normal
    retry behavior, so a rare persisting failure is a genuine outage,
    not a malformed request. The language comes from `service`, so
    `lang` has no effect here.
    Keywords: statcan, geography, query, boundary, dguid, csd, da,
    fsa, cma, arcgis, geospatial, polygon, geojson.
    Mots-clés : statcan, géographie, requête, limites, dguid, sdr, ad,
    rta, rmr, arcgis, géospatial, polygone, geojson.
    """
    del lang
    return await client.query_layer_features(
        year,
        service,
        layer_id,
        where=where,
        out_fields=out_fields,
        return_geometry=return_geometry,
        out_sr=out_sr,
        result_offset=result_offset,
        result_record_count=result_record_count,
    )
