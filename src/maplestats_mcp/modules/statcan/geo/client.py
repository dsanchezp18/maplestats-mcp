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

import contextlib
import re

from maplestats_mcp.modules.statcan.geo import constants
from maplestats_mcp.modules.statcan.geo.schemas import (
    GeoFeature,
    GeoLayerDetail,
    GeoLayerField,
    GeoQueryResult,
    GeoServiceList,
    GeoServiceSummary,
    GeoSpatialLayer,
    GeoSpatialLayerDetail,
    GeoSpatialLayerList,
    GeoSpatialQueryResult,
    SpatialFilter,
)
from maplestats_mcp.modules.statcan.lang import current_lang, say, use_lang
from maplestats_mcp.shared.arcgis import ArcGISHubConfig, get_json, query_layer
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.json_utils import list_or_empty

CONFIG = ArcGISHubConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain="geo.statcan.gc.ca",
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    # Confirmed live 2026-09-26: one of geo.statcan.gc.ca's backends answered
    # HTTP 500 to every request, and each connection stays on one backend,
    # so all retries on a reused connection failed together (a live smoke
    # run did). A new connection per request spreads retries across
    # backends; failures then became independent (about 1 in 4).
    fresh_connection_per_request=True,
)

# `year` and `service` are interpolated directly into the request path
# and the cache key -- validated against an allow-list rather than
# trusted, the same reasoning as rdaas/client.py's _resource_id.
_VALID_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_path_segment(value: str, label: str) -> str:
    if not _VALID_PATH_SEGMENT.match(value):
        raise InvalidInput(
            say(
                f"{label} {value!r} must contain only letters, digits, '_', or '-'.",
                f"{label} {value!r} ne doit contenir que des lettres, des chiffres, « _ » ou « - ».",
            )
        )
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
    use_lang(lang)
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
            coverage=say(
                "years 2019-2025 confirmed live; nothing older is served here",
                "années 2019 à 2025 confirmées en direct ; rien de plus ancien n'est servi ici",
            ),
            lang=current_lang(),
        ),
    )


async def _raise_if_unknown(year: str, service: str, layer_id: int) -> None:
    """Turn an HTTP 500 for a bad service or layer into NotFound.

    Confirmed live 2026-09-27: the server now answers an unknown service or
    layer with an HTML "Application Error" page and HTTP 500, not the
    embedded {"error": {"code": 404}} it used to send. A 500 also means a
    real outage, so check the service and layer listings before blaming the
    caller. If the listings fail too, the caller keeps the original error.
    """
    services = await list_services(year)
    if service not in {s.name.rsplit("/", 1)[-1] for s in services.services}:
        raise NotFound(
            say(
                f"No service {service!r} for {year}; statcan_geo_list_services lists the valid names.",
                f"Aucun service {service!r} pour {year} ; statcan_geo_list_services liste les noms valides.",
            )
        )
    body = await get_json(CONFIG, "list_layers", f"{constants.BASE_URL}/{year}/{service}/MapServer")
    if layer_id not in {layer.get("id") for layer in list_or_empty(body, "layers")}:
        raise NotFound(
            say(
                f"Service {service!r} ({year}) has no layer {layer_id}.",
                f"Le service {service!r} ({year}) n'a pas de couche {layer_id}.",
            )
        )


async def get_layer_detail(year: str, service: str, layer_id: int) -> GeoLayerDetail:
    year = _validate_path_segment(year, "year")
    service = _validate_path_segment(service, "service")
    if layer_id < 0:
        raise InvalidInput(
            say(
                f"layer_id must be >= 0, got {layer_id}.",
                f"layer_id doit être >= 0, reçu {layer_id}.",
            )
        )
    cache_key = f"statcan-geo:layer:{year}:{service}:{layer_id}"
    url = f"{constants.BASE_URL}/{year}/{service}/MapServer/{layer_id}"

    async def fetch():
        return await get_json(CONFIG, "get_layer_detail", url)

    try:
        body, was_cached = await cached_fetch(
            cache_key, constants.CACHE_TTL_LAYER_DETAIL_SECONDS, fetch
        )
    except UpstreamError:
        with contextlib.suppress(UpstreamError, UpstreamUnavailable):
            await _raise_if_unknown(year, service, layer_id)
        raise
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
            lang=current_lang(),
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
    lat: float | None = None,
    lon: float | None = None,
    bbox: str | None = None,
    distance_m: float | None = None,
) -> GeoQueryResult:
    """Query one geography layer's features by attribute and/or location (and,
    if `return_geometry`, by returning polygon boundaries reprojected to
    `out_sr`, WGS84 lat/lon by default -- the service's native spatial
    reference is EPSG:3347, Statistics Canada Lambert).

    `lat`/`lon` select the features that contain (intersect) that WGS84
    point -- "which census tract holds this address" -- and `bbox`
    ("min_lon,min_lat,max_lon,max_lat") the features intersecting a
    rectangle. See `spatial_query_params` for the validation.

    Results are capped at `result_record_count` (each layer's own
    upstream `maxRecordCount`, confirmed 6000 for 2021's Cartographic
    boundary layers, is the true ceiling per request regardless of
    what is asked for); `exceeded_transfer_limit` on the result tells
    the caller whether to page further with `result_offset`.
    """
    year = _validate_path_segment(year, "year")
    service = _validate_path_segment(service, "service")
    if layer_id < 0:
        raise InvalidInput(
            say(
                f"layer_id must be >= 0, got {layer_id}.",
                f"layer_id doit être >= 0, reçu {layer_id}.",
            )
        )
    if result_offset < 0:
        raise InvalidInput(
            say(
                f"result_offset must be >= 0, got {result_offset}.",
                f"result_offset doit être >= 0, reçu {result_offset}.",
            )
        )
    if result_record_count < 1 or result_record_count > constants.QUERY_RECORD_COUNT_MAX:
        raise InvalidInput(
            say(
                f"result_record_count must be between 1 and {constants.QUERY_RECORD_COUNT_MAX}, "
                f"got {result_record_count}.",
                f"result_record_count doit être entre 1 et {constants.QUERY_RECORD_COUNT_MAX}, reçu {result_record_count}.",
            )
        )

    spatial_params, spatial_filter = spatial_query_params(lat, lon, bbox, distance_m)
    service_url = f"{constants.BASE_URL}/{year}/{service}/MapServer"
    try:
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
            extra_params=spatial_params,
        )
    except UpstreamError:
        with contextlib.suppress(UpstreamError, UpstreamUnavailable):
            await _raise_if_unknown(year, service, layer_id)
        raise

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
        spatial_filter=spatial_filter,
        features=features,
        returned_count=len(features),
        exceeded_transfer_limit=exceeded,
        result_offset=result_offset,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{service_url}/{layer_id}/query",
            cached=False,
            schema_name="statcan_geo.GeoQueryResult",
            coverage=say(
                f"{len(features)} features returned"
                + (" (more available; page with result_offset)" if exceeded else ""),
                f"{len(features)} entités renvoyées"
                + (" (il y en a d'autres ; paginez avec result_offset)" if exceeded else ""),
            ),
            lang=current_lang(),
        ),
    )


def spatial_query_params(
    lat: float | None,
    lon: float | None,
    bbox: str | None,
    distance_m: float | None,
) -> tuple[dict[str, object] | None, SpatialFilter | None]:
    """Turn a point or bbox into ArcGIS spatial-filter parameters.

    Confirmed live 2026-10-02 on the geoanalytics DA layer: a point
    `geometry=lon,lat` with `inSR=4326` returns the one containing
    polygon, an envelope returns every intersecting feature, and
    `distance` + `units=esriSRUnit_Meter` on a point returns features
    within that radius (transit stops 300 m around Bay and Queen).
    `inSR=4326` makes the coordinates plain WGS84 whatever the layer's own
    spatial reference is. `lat`/`lon` are validated here because the
    service silently accepts an out-of-range or swapped pair and returns
    nothing.
    """
    if (lat is None) != (lon is None):
        raise InvalidInput(
            say(
                "Give both lat and lon for a point filter, or neither.",
                "Donnez à la fois lat et lon pour un filtre par point, ou ni l'un ni l'autre.",
            )
        )
    if lat is not None and bbox is not None:
        raise InvalidInput(
            say(
                "Use either lat/lon or bbox as the spatial filter, not both.",
                "Utilisez soit lat/lon, soit bbox comme filtre spatial, pas les deux.",
            )
        )
    if distance_m is not None and lat is None:
        raise InvalidInput(
            say(
                "distance_m needs lat and lon (it is a radius around that point).",
                "distance_m exige lat et lon (c'est un rayon autour de ce point).",
            )
        )
    if lat is not None and lon is not None:
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise InvalidInput(
                say(
                    f"lat must be within -90..90 and lon within -180..180, got lat={lat}, lon={lon}.",
                    f"lat doit être entre -90 et 90 et lon entre -180 et 180, reçu lat={lat}, lon={lon}.",
                )
            )
        params: dict[str, object] = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
        if distance_m is not None:
            if not 0 < distance_m <= constants.DISTANCE_MAX_METRES:
                raise InvalidInput(
                    say(
                        f"distance_m must be between 0 and {constants.DISTANCE_MAX_METRES}, "
                        f"got {distance_m}.",
                        f"distance_m doit être entre 0 et {constants.DISTANCE_MAX_METRES}, reçu {distance_m}.",
                    )
                )
            params["distance"] = distance_m
            params["units"] = "esriSRUnit_Meter"
        return params, SpatialFilter(kind="point", lon=lon, lat=lat, distance_m=distance_m)
    if bbox is not None:
        try:
            xmin, ymin, xmax, ymax = (float(part) for part in bbox.split(","))
        except ValueError:
            raise InvalidInput(
                say(
                    f"bbox must be 'min_lon,min_lat,max_lon,max_lat' (four numbers), got {bbox!r}.",
                    f"bbox doit être « min_lon,min_lat,max_lon,max_lat » (quatre nombres), reçu {bbox!r}.",
                )
            ) from None
        if not (-180 <= xmin < xmax <= 180 and -90 <= ymin < ymax <= 90):
            raise InvalidInput(
                say(
                    "bbox must satisfy min_lon < max_lon within -180..180 and "
                    f"min_lat < max_lat within -90..90, got {bbox!r}.",
                    f"bbox doit respecter min_lon < max_lon entre -180 et 180 et min_lat < max_lat entre -90 et 90, reçu {bbox!r}.",
                )
            )
        params = {
            "geometry": f"{xmin},{ymin},{xmax},{ymax}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
        return params, SpatialFilter(kind="bbox", bbox=[xmin, ymin, xmax, ymax])
    return None, None


# --- geoanalytics MapServers (infc / hna / qol) and the National Road Network ---

ANALYTICS_CONFIG = ArcGISHubConfig(
    source=constants.ANALYTICS_RATE_LIMIT_SOURCE,
    domain="geoanalytics.cloud.statcan.ca",
    rate_limit_per_second=constants.ANALYTICS_RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.ANALYTICS_RATE_LIMIT_CAPACITY,
)

_NRN_LAYER_NAME = re.compile(r"^([A-Z]{2}) - (.+?)(?: / .*)?$")


def _dataset_target(dataset: str) -> tuple[ArcGISHubConfig, str | None, str]:
    """Return (client config, fixed service URL or None, limits text)."""
    if dataset == "nrn":
        return (
            CONFIG,
            constants.NRN_SERVICE_URL,
            say(constants.NRN_LIMITS, constants.NRN_LIMITS_FR),
        )
    if dataset in constants.ANALYTICS_DATASETS:
        return (
            ANALYTICS_CONFIG,
            None,
            say(constants.ANALYTICS_LIMITS, constants.ANALYTICS_LIMITS_FR),
        )
    valid = ", ".join([*constants.ANALYTICS_DATASETS, "nrn"])
    raise InvalidInput(
        say(
            f"dataset {dataset!r} is not one of: {valid}.",
            f"dataset {dataset!r} ne fait pas partie de : {valid}.",
        )
    )


async def analytics_service_url(dataset: str) -> str:
    """Read the dataset's current MapServer URL from the apps' config file.

    Confirmed live 2026-10-02: the file lists `mapserver` entries with ids
    `hna_ms`, `infc_ms` and `qol_ms`, each a portal-proxied
    `.../portal/sharing/servers/<32-hex id>/rest/services/Geomatics_Services/
    <name>/MapServer` URL. The proxy ids are not stable by contract, so they
    are looked up on every (cached) call, and a changed file fails loudly.
    """
    entry_id = constants.ANALYTICS_DATASETS[dataset]

    async def fetch():
        return await get_json(ANALYTICS_CONFIG, "read_config", constants.ANALYTICS_CONFIG_URL)

    body, _ = await cached_fetch(
        "statcan-geo:analytics-config", constants.CACHE_TTL_ANALYTICS_CONFIG_SECONDS, fetch
    )
    entries = list_or_empty(body, "mapserver") if isinstance(body, dict) else []
    url = next(
        (e.get("url") for e in entries if isinstance(e, dict) and e.get("id") == entry_id), None
    )
    if (
        not isinstance(url, str)
        or not url.startswith(constants.ANALYTICS_HOST_PREFIX)
        or "/rest/services/" not in url
        or not url.rstrip("/").endswith("/MapServer")
    ):
        raise UpstreamError(
            say(
                f"StatCan's map-app config ({constants.ANALYTICS_CONFIG_URL}) no longer lists a "
                f"usable MapServer under id {entry_id!r} for dataset {dataset!r} (found {url!r}). "
                "These endpoints are undocumented and the config has changed; the tool needs an update.",
                f"La configuration de l'application cartographique de Statistique Canada ({constants.ANALYTICS_CONFIG_URL}) ne liste plus de MapServer utilisable sous l'identifiant {entry_id!r} pour le jeu de données {dataset!r} (trouvé {url!r}). Ces points d'accès ne sont pas documentés et la configuration a changé ; l'outil doit être mis à jour.",
            )
        )
    return url.rstrip("/")


async def _service_info(dataset: str) -> tuple[ArcGISHubConfig, str, dict, bool, str]:
    config, fixed_url, limits = _dataset_target(dataset)
    service_url = fixed_url or await analytics_service_url(dataset)

    async def fetch():
        return await get_json(config, f"service_info:{dataset}", service_url)

    info, was_cached = await cached_fetch(
        f"statcan-geo:layers:{service_url}", constants.CACHE_TTL_ANALYTICS_LAYERS_SECONDS, fetch
    )
    if not isinstance(info, dict) or not list_or_empty(info, "layers"):
        raise UpstreamError(
            say(
                f"{service_url} answered without a layer list; the {dataset!r} service has changed.",
                f"{service_url} a répondu sans liste de couches ; le service {dataset!r} a changé.",
            )
        )
    return config, service_url, info, was_cached, limits


def _parse_layer(raw: dict) -> GeoSpatialLayer:
    name = str(raw.get("name", ""))
    province = road_class = None
    matched = _NRN_LAYER_NAME.match(name)
    if matched:
        province, road_class = matched.group(1), matched.group(2)
    parent = raw.get("parentLayerId")
    return GeoSpatialLayer(
        layer_id=raw["id"],
        name=name,
        parent_layer_id=parent if isinstance(parent, int) and parent >= 0 else None,
        is_group=bool(raw.get("subLayerIds")),
        geometry_type=raw.get("geometryType"),
        province=province,
        road_class=road_class,
    )


async def list_spatial_layers(
    dataset: str, province: str | None = None, road_class: str | None = None
) -> GeoSpatialLayerList:
    _, service_url, info, was_cached, limits = await _service_info(dataset)
    layers = [_parse_layer(raw) for raw in list_or_empty(info, "layers")]
    if province or road_class:
        if dataset != "nrn":
            raise InvalidInput(
                say(
                    "province and road_class filters apply only to dataset 'nrn'.",
                    "Les filtres province et road_class ne s'appliquent qu'au jeu de données « nrn ».",
                )
            )
        layers = [
            layer
            for layer in layers
            if not layer.is_group
            and (not province or layer.province == province.upper())
            and (not road_class or road_class.lower() in (layer.road_class or "").lower())
        ]
    return GeoSpatialLayerList(
        dataset=dataset,
        service_url=service_url,
        max_record_count=info.get("maxRecordCount"),
        capabilities=info.get("capabilities"),
        layers=layers,
        provenance=make_provenance(
            source=_dataset_source(dataset),
            url=service_url,
            cached=was_cached,
            schema_name="statcan_geo.GeoSpatialLayerList",
            coverage=say(f"{len(layers)} layers listed", f"{len(layers)} couches listées"),
            limits=limits,
            lang=current_lang(),
        ),
    )


def _dataset_source(dataset: str) -> str:
    return (
        constants.RATE_LIMIT_SOURCE if dataset == "nrn" else constants.ANALYTICS_RATE_LIMIT_SOURCE
    )


async def _checked_layer(
    dataset: str, layer_id: int
) -> tuple[ArcGISHubConfig, str, GeoSpatialLayer]:
    if layer_id < 0:
        raise InvalidInput(
            say(
                f"layer_id must be >= 0, got {layer_id}.",
                f"layer_id doit être >= 0, reçu {layer_id}.",
            )
        )
    config, service_url, info, _, _ = await _service_info(dataset)
    layer = next(
        (_parse_layer(raw) for raw in list_or_empty(info, "layers") if raw.get("id") == layer_id),
        None,
    )
    if layer is None:
        raise NotFound(
            say(
                f"Dataset {dataset!r} has no layer {layer_id}; statcan_geo_list_spatial_layers "
                "lists the valid ids.",
                f"Le jeu de données {dataset!r} n'a pas de couche {layer_id} ; statcan_geo_list_spatial_layers liste les identifiants valides.",
            )
        )
    if layer.is_group:
        raise InvalidInput(
            say(
                f"Layer {layer_id} ({layer.name!r}) of {dataset!r} is a group of sub-layers with no "
                "rows of its own; pick one of its sub-layers (statcan_geo_list_spatial_layers).",
                f"La couche {layer_id} ({layer.name!r}) de {dataset!r} est un groupe de sous-couches sans lignes propres ; choisissez l'une de ses sous-couches (statcan_geo_list_spatial_layers).",
            )
        )
    return config, service_url, layer


async def get_spatial_layer_detail(dataset: str, layer_id: int) -> GeoSpatialLayerDetail:
    config, service_url, layer = await _checked_layer(dataset, layer_id)
    url = f"{service_url}/{layer_id}"
    body = await get_json(config, f"layer_detail:{dataset}:{layer_id}", url)
    fields = [
        GeoLayerField(name=f["name"], field_type=f["type"], alias=f.get("alias"))
        for f in list_or_empty(body, "fields")
    ]
    spatial_ref = body.get("spatialReference") or body.get("extent", {}).get("spatialReference", {})
    return GeoSpatialLayerDetail(
        dataset=dataset,
        layer_id=layer_id,
        name=body.get("name", layer.name),
        geometry_type=body.get("geometryType"),
        fields=fields,
        max_record_count=body.get("maxRecordCount"),
        spatial_reference_wkid=spatial_ref.get("wkid") or spatial_ref.get("latestWkid"),
        provenance=make_provenance(
            source=_dataset_source(dataset),
            url=url,
            cached=False,
            schema_name="statcan_geo.GeoSpatialLayerDetail",
            limits=_dataset_target(dataset)[2],
            lang=current_lang(),
        ),
    )


async def resolve_nrn_layer(province: str, road_class: str) -> int:
    """Find the one NRN layer for a province code and a road-class phrase."""
    listing = await list_spatial_layers("nrn", province=province, road_class=road_class)
    matches = listing.layers
    exact = [m for m in matches if (m.road_class or "").lower() == road_class.lower()]
    if len(exact) == 1:
        return exact[0].layer_id
    if len(matches) == 1:
        return matches[0].layer_id
    if not matches:
        raise NotFound(
            say(
                f"No NRN layer for province {province!r} and road class {road_class!r}; not every "
                "province has every class (e.g. Quebec has no toll points). "
                "statcan_geo_list_spatial_layers(dataset='nrn') lists them.",
                f"Aucune couche du RRN pour la province {province!r} et la catégorie de route {road_class!r} ; chaque province n'a pas toutes les catégories (p. ex. le Québec n'a pas de postes de péage). statcan_geo_list_spatial_layers(dataset='nrn') les liste.",
            )
        )
    names = ", ".join(sorted({m.road_class or m.name for m in matches}))
    raise InvalidInput(
        say(
            f"road_class {road_class!r} matches several NRN layers ({names}); be exact.",
            f"road_class {road_class!r} correspond à plusieurs couches du RRN ({names}) ; soyez exact.",
        )
    )


async def query_spatial_layer(
    dataset: str,
    layer_id: int,
    *,
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
) -> GeoSpatialQueryResult:
    if result_offset < 0:
        raise InvalidInput(
            say(
                f"result_offset must be >= 0, got {result_offset}.",
                f"result_offset doit être >= 0, reçu {result_offset}.",
            )
        )
    if result_record_count < 1 or result_record_count > constants.QUERY_RECORD_COUNT_MAX:
        raise InvalidInput(
            say(
                f"result_record_count must be between 1 and {constants.QUERY_RECORD_COUNT_MAX}, "
                f"got {result_record_count}.",
                f"result_record_count doit être entre 1 et {constants.QUERY_RECORD_COUNT_MAX}, reçu {result_record_count}.",
            )
        )
    spatial_params, spatial_filter = spatial_query_params(lat, lon, bbox, distance_m)
    config, service_url, layer = await _checked_layer(dataset, layer_id)
    body = await query_layer(
        config,
        service_url,
        layer_id,
        where=where,
        out_fields=out_fields,
        return_geometry=return_geometry,
        limit=result_record_count,
        offset=result_offset,
        output_format="geojson",
        out_sr=out_sr if return_geometry else None,
        extra_params=spatial_params,
    )
    features = [
        GeoFeature(attributes=f.get("properties", {}), geometry=f.get("geometry"))
        for f in list_or_empty(body, "features")
    ]
    exceeded = bool(body.get("exceededTransferLimit"))
    return GeoSpatialQueryResult(
        dataset=dataset,
        layer_id=layer_id,
        layer_name=layer.name,
        where=where,
        spatial_filter=spatial_filter,
        features=features,
        returned_count=len(features),
        exceeded_transfer_limit=exceeded,
        result_offset=result_offset,
        provenance=make_provenance(
            source=_dataset_source(dataset),
            url=f"{service_url}/{layer_id}/query",
            cached=False,
            schema_name="statcan_geo.GeoSpatialQueryResult",
            coverage=say(
                f"{len(features)} features returned"
                + (" (more available; page with result_offset)" if exceeded else ""),
                f"{len(features)} entités renvoyées"
                + (" (il y en a d'autres ; paginez avec result_offset)" if exceeded else ""),
            ),
            lang=current_lang(),
            limits=_dataset_target(dataset)[2],
        ),
    )
