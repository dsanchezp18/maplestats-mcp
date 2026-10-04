"""MCP tools for StatCan's geo.statcan.gc.ca ArcGIS REST census-geography service."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.geo import client, constants
from maplestats_mcp.modules.statcan.geo.schemas import (
    GeoLayerDetail,
    GeoQueryResult,
    GeoServiceList,
    GeoSpatialLayerDetail,
    GeoSpatialLayerList,
    GeoSpatialQueryResult,
)
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.shared.errors import InvalidInput

Lang = Literal["en", "fr"]
Dataset = Literal["infc", "hna", "qol", "nrn"]


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
    Mots-clés : Statistique Canada, géographie, fichiers des limites,
    géospatial, géographie du recensement, limites cartographiques, fichier
    numérique des limites, couches cartographiques, cartes.
    """
    use_lang(lang)
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
    Mots-clés : Statistique Canada, géographie, couche, schéma, champs,
    attributs, fichier des limites, type de géométrie, structure de la
    couche.
    """
    use_lang(lang)
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
    lat: float | None = None,
    lon: float | None = None,
    bbox: str | None = None,
    distance_m: float | None = None,
    lang: Lang = "en",
) -> GeoQueryResult:
    """Query one geography layer's features by attribute or location, optionally with geometry.

    Use for: finding a geography's DGUID/UID by name (e.g.
    `where="CSDNAME='Toronto'"`), finding which area contains a point
    ("which census tract / dissemination area / CSD is at this lat/lon":
    pass `lat` and `lon`, WGS84 degrees, and pick the layer for the
    level wanted), listing the areas touching a rectangle (`bbox` =
    "min_lon,min_lat,max_lon,max_lat"), or retrieving boundary polygons
    for mapping. `distance_m` widens a point to a radius in metres. A
    spatial filter combines with `where` and `out_fields` (e.g.
    `out_fields="CTUID,DGUID"` keeps the answer small) and is echoed back
    in `spatial_filter`. `where` is a standard SQL-style predicate against the
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
    fsa, cma, arcgis, geospatial, polygon, geojson, point in polygon,
    latitude longitude, census tract lookup, bounding box.
    Mots-clés : Statistique Canada, géographie, requête, limites, DGUID,
    SDR, AD, RTA, RMR, géospatial, polygone, GeoJSON, point dans un
    polygone, latitude et longitude, secteur de recensement, aire de
    diffusion, rectangle englobant.
    """
    use_lang(lang)
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
        lat=lat,
        lon=lon,
        bbox=bbox,
        distance_m=distance_m,
    )


@tool
async def statcan_geo_list_spatial_layers(
    dataset: Dataset,
    province: str | None = None,
    road_class: str | None = None,
    lang: Lang = "en",
) -> GeoSpatialLayerList:
    """List the layers of a StatCan map-app dataset or of the National Road Network.

    Use for: finding the `layer_id` to query. `dataset` picks the service:
    "infc" (Index of Neighbourhood Characteristics / CSGE app: Canadian
    Index of Multiple Deprivation 2021 by dissemination area, Proximity
    Measures, Spatial Access Measures 2022, CanBICS, CanALE, and Linkable
    Open Data Environment facilities: cultural, educational, recreational,
    infrastructure, transit stops), "hna" (Housing Needs Assessment by
    province and census subdivision, change in stock 2021-2023), "qol"
    (Quality of Life indicators 2025 by province, CSD, CMA and census
    division) or "nrn" (National Road Network: one layer per province and
    road class, plus ferry connections, toll points and blocked
    passages). For "nrn", `province` ("ON") and `road_class` ("Local
    roads") narrow the list. Group layers are listed (is_group=true) but
    hold no rows. The infc/hna/qol service addresses are undocumented and
    read from StatCan's map-app config file at runtime; a clear error
    says so if StatCan changes it. Free under the Statistics Canada Open
    Licence. The tool's text is English only, so `lang` has no effect.
    Keywords: statcan, geoanalytics, infc, hna, qol, national road
    network, nrn, housing needs assessment, quality of life, deprivation
    index, proximity measures, transit stops, layers.
    Mots-clés : Statistique Canada, géoanalytique, indice de défavorisation
    multiple, évaluation des besoins en logement, qualité de vie, réseau
    routier national, mesures de proximité, arrêts de transport en commun,
    couches.
    """
    use_lang(lang)
    return await client.list_spatial_layers(dataset, province=province, road_class=road_class)


@tool
async def statcan_geo_get_spatial_layer_detail(
    dataset: Dataset, layer_id: int, lang: Lang = "en"
) -> GeoSpatialLayerDetail:
    """Get one layer's field list, geometry type and record cap (infc, hna, qol, nrn).

    Use for: reading the queryable field names of a layer before building
    a `where` clause for statcan_geo_query_spatial_layer, e.g. the
    dissemination-area fields (DAUID, DGUID, csdname, cmaname and
    indicator columns named AA###) of the infc Census_DA_2021 layer, or the
    roadclass, route name and number fields of an NRN road layer. Take
    `layer_id` from statcan_geo_list_spatial_layers. The tool's text is
    English only, so `lang` has no effect.
    Keywords: statcan, layer schema, fields, geoanalytics, infc, hna,
    qol, national road network, nrn, attribute names, max record count.
    Mots-clés : Statistique Canada, schéma de couche, champs, géoanalytique,
    réseau routier national, noms d'attributs, indice de défavorisation,
    qualité de vie, besoins en logement.
    """
    use_lang(lang)
    return await client.get_spatial_layer_detail(dataset, layer_id)


@tool
async def statcan_geo_query_spatial_layer(
    dataset: Dataset,
    layer_id: int | None = None,
    province: str | None = None,
    road_class: str | None = None,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = False,
    out_sr: int = constants.DEFAULT_OUT_SR,
    result_offset: int = 0,
    result_record_count: int = constants.QUERY_RECORD_COUNT_DEFAULT,
    lat: float | None = None,
    lon: float | None = None,
    bbox: str | None = None,
    distance_m: float | None = None,
    lang: Lang = "en",
) -> GeoSpatialQueryResult:
    """Query rows from the StatCan map-app datasets (infc, hna, qol) or the National Road Network.

    Use for: neighbourhood deprivation (Canadian Index of Multiple
    Deprivation) or proximity/access measures for the dissemination area
    at a lat/lon, the transit stops or facilities within `distance_m`
    metres of a point, housing-need and change-in-stock indicators for a
    municipality (hna), quality-of-life indicators by province, CMA, CSD or
    census division (qol), and road segments of a province by road class
    (nrn). `layer_id` comes from statcan_geo_list_spatial_layers; for
    "nrn" you can give `province` ("ON") and `road_class` ("Local roads")
    instead. Filter by attribute with `where`, by location with `lat` and
    `lon` (WGS84; the row whose area contains the point) or `bbox`
    ("min_lon,min_lat,max_lon,max_lat"), optionally `distance_m` as a
    radius around the point, and cut the columns with `out_fields`
    ("DAUID,DGUID"). Geometry is off by default. At most 2,000 rows come
    back per call (the services allow 2,000 to 50,000); page with
    `result_offset` while `exceeded_transfer_limit` is true. Undocumented
    infc/hna/qol endpoints, read from StatCan's map-app config at runtime
    (see provenance.limits); the NRN host answers HTTP 500 now and then
    and the client retries. Statistics Canada Open Licence. The tool's
    text is English only, so `lang` has no effect.
    Keywords: statcan, deprivation index, cimd, proximity measures,
    spatial access, housing needs assessment, quality of life, transit
    stops, national road network, nrn, road segments, lat lon lookup,
    point in polygon, geoanalytics.
    Mots-clés : Statistique Canada, indice de défavorisation multiple,
    mesures de proximité, accès spatial, évaluation des besoins en logement,
    qualité de vie, arrêts de transport en commun, réseau routier national,
    segments routiers, latitude et longitude, point dans un polygone.
    """
    use_lang(lang)
    if layer_id is None:
        if dataset != "nrn" or not province or not road_class:
            raise InvalidInput(
                say(
                    "Give layer_id (from statcan_geo_list_spatial_layers), or for dataset 'nrn' "
                    "both province and road_class.",
                    "Donnez layer_id (tiré de statcan_geo_list_spatial_layers) ou, pour le jeu de données « nrn », à la fois province et road_class.",
                )
            )
        layer_id = await client.resolve_nrn_layer(province, road_class)
    return await client.query_spatial_layer(
        dataset,
        layer_id,
        where=where,
        out_fields=out_fields,
        return_geometry=return_geometry,
        out_sr=out_sr,
        result_offset=result_offset,
        result_record_count=result_record_count,
        lat=lat,
        lon=lon,
        bbox=bbox,
        distance_m=distance_m,
    )
