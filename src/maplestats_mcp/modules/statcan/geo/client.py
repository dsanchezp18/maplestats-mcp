"""HTTP client for StatCan's geo.statcan.gc.ca ArcGIS REST census-geography service.

This is a plain ArcGIS *Server* deployment (a folder/service/layer
tree browsed directly), not one of the ArcGIS *Hub* sites
`shared/arcgis.py` was originally built for -- but its actual REST
query mechanics (a FeatureServer/MapServer layer query, the same
embedded-`{"error": ...}` response shape) are identical, so this
client reuses that module's `get_json`/`query_layer` rather than
duplicating them. See shared/arcgis.py's module docstring for the
platform-level quirks those two functions handle.
"""

from __future__ import annotations

import re

from maplestats_mcp.modules.statcan.geo import constants
from maplestats_mcp.modules.statcan.geo.schemas import (
    GeoFeature,
    GeoLayerDetail,
    GeoLayerField,
    GeoQueryResult,
    GeoServiceList,
    GeoServiceSummary,
)
from maplestats_mcp.shared.arcgis import ArcGISHubConfig, get_json, query_layer
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.json_utils import list_or_empty

CONFIG = ArcGISHubConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain="geo.statcan.gc.ca",
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)

# `year` and `service` are interpolated directly into the request path
# and the cache key -- validated against an allow-list rather than
# trusted, the same reasoning as rdaas/client.py's _resource_id.
_VALID_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_path_segment(value: str, label: str) -> str:
    if not _VALID_PATH_SEGMENT.match(value):
        raise InvalidInput(f"{label} {value!r} must contain only letters, digits, '_', or '-'.")
    return value


def _service_language(name: str) -> str:
    """Every boundary product is published twice, once per language.

    Confirmed live: 2021 names French services "Fichier(s)_..." and
    intercensal years suffix codes with "_e"/"_f" (e.g. lcsd000a19r_e,
    lsdr000a19r_f).
    """
    base = name.rsplit("/", 1)[-1].lower()
    return "fr" if base.startswith("fichier") or base.endswith("_f") else "en"


async def list_services(year: str, lang: str | None = None) -> GeoServiceList:
    year = _validate_path_segment(year, "year")
    cache_key = f"statcan-geo:services:{year}"

    async def fetch():
        return await get_json(CONFIG, "list_services", f"{constants.BASE_URL}/{year}")

    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SERVICES_SECONDS, fetch)
    services = [
        GeoServiceSummary(
            name=s["name"], service_type=s["type"], language=_service_language(s["name"])
        )
        for s in list_or_empty(body, "services")
    ]
    if lang:
        services = [s for s in services if s.language == lang]
    return GeoServiceList(
        year=year,
        services=services,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/{year}",
            cached=was_cached,
            schema_name="statcan_geo.GeoServiceList",
            coverage="years 2019-2025 confirmed live; nothing older is served here",
        ),
    )


async def get_layer_detail(year: str, service: str, layer_id: int) -> GeoLayerDetail:
    year = _validate_path_segment(year, "year")
    service = _validate_path_segment(service, "service")
    if layer_id < 0:
        raise InvalidInput(f"layer_id must be >= 0, got {layer_id}.")
    cache_key = f"statcan-geo:layer:{year}:{service}:{layer_id}"
    url = f"{constants.BASE_URL}/{year}/{service}/MapServer/{layer_id}"

    async def fetch():
        return await get_json(CONFIG, "get_layer_detail", url)

    body, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_LAYER_DETAIL_SECONDS, fetch
    )
    fields = [
        GeoLayerField(name=f["name"], field_type=f["type"], alias=f.get("alias"))
        for f in list_or_empty(body, "fields")
    ]
    spatial_ref = body.get("spatialReference") or body.get("extent", {}).get("spatialReference", {})
    return GeoLayerDetail(
        year=year,
        service=service,
        layer_id=layer_id,
        name=body.get("name", ""),
        geometry_type=body.get("geometryType"),
        fields=fields,
        max_record_count=body.get("maxRecordCount"),
        spatial_reference_wkid=spatial_ref.get("wkid") or spatial_ref.get("latestWkid"),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_geo.GeoLayerDetail",
        ),
    )


async def query_layer_features(
    year: str,
    service: str,
    layer_id: int,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = False,
    out_sr: int = constants.DEFAULT_OUT_SR,
    result_offset: int = 0,
    result_record_count: int = constants.QUERY_RECORD_COUNT_DEFAULT,
) -> GeoQueryResult:
    """Query one geography layer's features by attribute (and, if
    `return_geometry`, by returning polygon boundaries reprojected to
    `out_sr`, WGS84 lat/lon by default -- the service's native spatial
    reference is EPSG:3347, Statistics Canada Lambert).

    Results are capped at `result_record_count` (each layer's own
    upstream `maxRecordCount`, confirmed 6000 for 2021's Cartographic
    boundary layers, is the true ceiling per request regardless of
    what is asked for); `exceeded_transfer_limit` on the result tells
    the caller whether to page further with `result_offset`.
    """
    year = _validate_path_segment(year, "year")
    service = _validate_path_segment(service, "service")
    if layer_id < 0:
        raise InvalidInput(f"layer_id must be >= 0, got {layer_id}.")
    if result_offset < 0:
        raise InvalidInput(f"result_offset must be >= 0, got {result_offset}.")
    if result_record_count < 1 or result_record_count > constants.QUERY_RECORD_COUNT_MAX:
        raise InvalidInput(
            f"result_record_count must be between 1 and {constants.QUERY_RECORD_COUNT_MAX}, "
            f"got {result_record_count}."
        )

    service_url = f"{constants.BASE_URL}/{year}/{service}/MapServer"
    body = await query_layer(
        CONFIG,
        service_url,
        layer_id,
        where=where,
        out_fields=out_fields,
        return_geometry=return_geometry,
        limit=result_record_count,
        offset=result_offset,
        output_format="geojson",
        out_sr=out_sr if return_geometry else None,
    )

    features = [
        GeoFeature(attributes=f.get("properties", {}), geometry=f.get("geometry"))
        for f in list_or_empty(body, "features")
    ]
    exceeded = bool(body.get("exceededTransferLimit"))
    return GeoQueryResult(
        year=year,
        service=service,
        layer_id=layer_id,
        where=where,
        features=features,
        returned_count=len(features),
        exceeded_transfer_limit=exceeded,
        result_offset=result_offset,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{service_url}/{layer_id}/query",
            cached=False,
            schema_name="statcan_geo.GeoQueryResult",
            coverage=f"{len(features)} features returned"
            + (" (more available; page with result_offset)" if exceeded else ""),
        ),
    )
