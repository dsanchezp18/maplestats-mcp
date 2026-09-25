"""Shared plumbing for any Esri ArcGIS Hub deployment ("Data Hub" sites).

Confirmed live 2026-09-18 against geoportal.gov.mb.ca (Manitoba),
geohub.saskatchewan.ca (Saskatchewan), and data.princeedwardisland.ca
(Prince Edward Island): every ArcGIS Hub site — even one running on a
fully custom government domain rather than a *.hub.arcgis.com
subdomain — proxies the same two APIs under its own domain, so one
client works for all three portals. What differs per portal (domain,
rate limit, cache TTLs) stays in each modules/arcgis_<province>/
package, per AGENTS.md.

Two live-verified platform quirks this module encodes:

1. The Hub Search API v3 (an OGC API - Features-shaped catalogue) at
   `/api/search/v1/collections/dataset/items` is scoped to the site's
   own content by construction — no orgId/siteId parameter needed. The
   collection's own root document (`/api/search/v1/collections/dataset`)
   declares its `type` filter enum as CSV/Feature Service/Shapefile/
   KML/Table/Image Service and similar — never a web app or StoryMap —
   so every item this API returns is a genuine downloadable dataset,
   and `download_url` below never needs to check an item's type before
   building an export link. Errors here use real HTTP status codes
   with a `{"message": ..., "error": ..., "statusCode": ...}` body,
   but `message` is a plain string on a 404 and a `list[str]` on some
   400s (confirmed: an over-limit request returns
   `{"message": ["searchOptions.limit must not be greater than
   20000"], ...}`) — `_error_detail` below checks both shapes.
2. The classic ArcGIS REST FeatureServer/MapServer query API, reached
   at each item's own `properties.url`, always answers HTTP 200 —
   even for a malformed `where` clause or an out-of-range layer index
   — and puts the real error in the JSON body as
   `{"error": {"code": ..., "message": ..., "details": [...]}}`.
   `query_layer` below inspects the decoded body for that key itself,
   since `api_get`'s `raise_for_status()` never fires for this
   endpoint. Relatedly, `properties.url` is sometimes the bare service
   root (Manitoba) and sometimes already a specific layer endpoint
   (Saskatchewan), and the layer/table id worth querying by default is
   not always 0 — a Prince Edward Island item's service had an empty
   `layers` list and its one queryable table at id 2. `_service_root`
   and `default_layer_index` below exist because of these two, found
   only by calling every function here against all three portals live
   (see AGENTS.md's rule on why mocked tests alone cannot catch this).
3. A later audit (2026-09-19, adding Durham Region) found a third
   quirk `default_layer_index` did not yet handle: an item's
   `properties.url` can point at a specific layer of one large shared
   service (Durham's `Durham_OpenData/MapServer/129`, out of 200+
   layers on that one MapServer) rather than at a single-purpose
   service whose own first layer is the right default. Re-listing the
   stripped root and picking `layers[0]` would have silently returned
   a different, unrelated dataset (layer 0) instead of raising —
   `default_layer_index` now returns a URL's own trailing numeric
   layer id directly when present, before ever calling
   `get_service_info`.

`get_json` (2026-09-21, added for StatCan's `modules/statcan/geo`) is
a thin, generic escape hatch for a plain ArcGIS *Server* deployment
(no Hub Search API in front of it -- a raw folder/service/layer tree
browsed directly, confirmed live for geo.statcan.gc.ca) that still
needs this module's shared error handling: the same embedded
`{"error": ...}` shape from quirk 2 above is confirmed live on every
resource this kind of deployment serves, not only `query_layer`'s
endpoint. `query_layer`'s own `output_format`/`out_sr` parameters
(also added then) are backward compatible -- every existing caller
keeps getting plain esri JSON with no reprojection, since both
default to the prior behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

DOWNLOAD_FORMATS = ("csv", "shapefile", "geojson", "kml")


@dataclass(frozen=True)
class ArcGISHubConfig:
    """Per-portal configuration for the shared ArcGIS Hub client."""

    source: str
    domain: str
    rate_limit_per_second: float
    rate_limit_capacity: float


def _limiter(config: ArcGISHubConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return exc.response.text[:200]
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, list) and message:
            return "; ".join(str(item) for item in message)
        if isinstance(message, str) and message:
            return message
        error = body.get("error")
        if isinstance(error, str) and error:
            return error
    return exc.response.text[:200]


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(config: ArcGISHubConfig, context: str, url: str, params: dict[str, Any]) -> Any:
    await _limiter(config).acquire()
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc


def _collection_url(config: ArcGISHubConfig) -> str:
    return f"https://{config.domain}/api/search/v1/collections/dataset"


async def search_items(
    config: ArcGISHubConfig,
    *,
    query: str = "",
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search one Hub site's dataset catalogue.

    `offset` is 0-based for consistency with every other module in this
    codebase; the upstream API's own `startindex` parameter is 1-based
    (confirmed live: a one-item page's "next" link carries
    `startindex=2`), so this converts once here rather than leaking a
    1-based parameter into every caller.
    """
    params: dict[str, Any] = {"limit": limit, "startindex": offset + 1}
    if query:
        params["q"] = query
    if tag:
        params["tags"] = tag
    if item_type:
        params["type"] = item_type
    return await _get(
        config, f"{config.source}:search_items", f"{_collection_url(config)}/items", params
    )


async def get_item(config: ArcGISHubConfig, item_id: str) -> dict[str, Any]:
    """Fetch one dataset item's full Hub Search API metadata."""
    url = f"{_collection_url(config)}/items/{item_id}"
    return await _get(config, f"{config.source}:get_item:{item_id}", url, {})


def download_url(config: ArcGISHubConfig, item_id: str, fmt: str, *, layer_index: int = 0) -> str:
    """Build a direct export-download link for one item.

    Confirmed live: `https://<domain>/api/download/v1/items/<id>/<fmt>
    ?layers=<n>` 302-redirects to a hub.arcgis.com-hosted download —
    the same link `data.json`'s `distribution` array publishes for
    every dataset, so it is safe to build for any item this Hub site's
    dataset collection returns (see module docstring).
    """
    return f"https://{config.domain}/api/download/v1/items/{item_id}/{fmt}?layers={layer_index}"


def _service_root(service_url: str) -> str:
    trimmed = service_url.rstrip("/")
    head, _, tail = trimmed.rpartition("/")
    return head if tail.isdigit() else trimmed


def _feature_service_error_detail(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message") or ""
        details = error.get("details")
        if isinstance(details, list) and details:
            return f"{message} ({'; '.join(str(d) for d in details)})".strip()
        return message or str(error)
    return str(error)


def _raise_if_embedded_error(source: str, context: str, body: Any) -> None:
    if not (isinstance(body, dict) and "error" in body):
        return
    detail = _feature_service_error_detail(body)
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code == 400:
        raise InvalidInput(f"{source}:{context}: rejected the request ({detail}).")
    # Confirmed live against a plain ArcGIS Server deployment (StatCan's
    # geo.statcan.gc.ca): an unknown folder/service/layer answers this
    # same embedded shape with code 404 ("Folder not found"/"Service
    # not found"/"Layer not found") -- map it the same way a real HTTP
    # 404 status is mapped elsewhere in this codebase.
    if code == 404:
        raise NotFound(f"{source}:{context}: {detail or 'not found'}.")
    raise UpstreamError(f"{source}:{context} returned an error: {detail}")


def _require_arcgis_rest_url(config: ArcGISHubConfig, context: str, service_url: str) -> None:
    if not service_url.startswith("https://") or "/rest/services/" not in service_url:
        raise InvalidInput(
            f"{config.source}:{context}: service_url must be an https ArcGIS REST "
            f"service endpoint (containing /rest/services/), got {service_url!r}."
        )


async def get_json(
    config: ArcGISHubConfig, context: str, url: str, *, params: dict[str, Any] | None = None
) -> Any:
    """GET one arbitrary ArcGIS REST resource -- a folder listing, a
    specific layer's own field/schema document, or anything else this
    module doesn't already have a dedicated function for -- raising for
    both a non-2xx status and the platform's embedded `{"error": ...}`
    shape (see module docstring, quirk 2). Unlike `get_service_info`,
    this does not strip a trailing numeric path segment first; pass the
    exact resource URL wanted.
    """
    body = await _get(config, f"{config.source}:{context}", url, {"f": "json", **(params or {})})
    _raise_if_embedded_error(config.source, context, body)
    return body


async def get_service_info(config: ArcGISHubConfig, service_url: str) -> dict[str, Any]:
    """Fetch a FeatureServer/MapServer's own root document (its `layers`/`tables` listing)."""
    _require_arcgis_rest_url(config, "get_service_info", service_url)
    root = _service_root(service_url)
    body = await _get(config, f"{config.source}:get_service_info", root, {"f": "json"})
    _raise_if_embedded_error(config.source, "get_service_info", body)
    return body


async def default_layer_index(config: ArcGISHubConfig, service_url: str) -> int:
    """Resolve which layer/table id to query when the caller doesn't pick one.

    Most hosted Feature/Map Services expose their one layer at index 0,
    but a hosted *table* (no geometry) can sit at any id — confirmed
    live against a Prince Edward Island item whose service reports an
    empty `layers` list and its only queryable table at id 2, not 0
    (`.../FeatureServer/0/query` on that service returns HTTP 200 with
    `{"error": {"code": 400, "message": "Invalid URL", ...}}`). Prefer
    the first entry in `layers`, fall back to the first entry in
    `tables`, and only default to 0 when a service reports neither —
    that should not happen for an item this Hub's dataset collection
    returned, but keeps this from raising on an unexpected shape.

    When `service_url` already names a specific layer (its final path
    segment is numeric), that digit is returned directly without
    re-listing the service root. Confirmed live against Durham Region's
    Durham_OpenData/MapServer, a single shared service exposing 200+
    layers: an item's `properties.url` there is
    `.../MapServer/129` (the one layer that item actually represents),
    and stripping to the bare root then picking `layers[0]` would
    silently return layer 0 ("ADDR_Durham") instead — a different,
    unrelated dataset, not a missing-data error, so nothing downstream
    would have caught it.
    """
    trimmed = service_url.rstrip("/")
    _, _, tail = trimmed.rpartition("/")
    if tail.isdigit():
        return int(tail)
    info = await get_service_info(config, service_url)
    layers = info.get("layers")
    if layers:
        return layers[0].get("id") or 0
    tables = info.get("tables")
    if tables:
        return tables[0].get("id") or 0
    return 0


async def query_layer(
    config: ArcGISHubConfig,
    service_url: str,
    layer_index: int,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    order_by: str | None = None,
    return_geometry: bool = False,
    limit: int = 10,
    offset: int = 0,
    output_format: str = "json",
    out_sr: int | None = None,
) -> dict[str, Any]:
    """Query one FeatureServer/MapServer layer's rows via the ArcGIS REST API.

    `service_url` must be a `properties.url` value taken from this
    same portal's own search results (see module docstring point 2 for
    why this endpoint's errors need special handling); checking for
    `/rest/services/` (present on every ArcGIS REST endpoint, Esri-
    hosted or self-hosted — confirmed live: Saskatchewan's GeoHub
    items point at `gis.saskatchewan.ca/egis/rest/services/...`, not
    an `*.arcgis.com` domain) is a cheap guard against a caller
    passing an arbitrary URL, not a documented upstream requirement.

    Confirmed live: an item's `url` is sometimes the bare service root
    (Manitoba: `.../FeatureServer`) and sometimes already a specific
    layer endpoint (Saskatchewan: `.../FeatureServer/0`) — the two
    portals differ in which layer of a possibly-multi-layer service
    their catalogue item happens to reference. `_service_root` strips
    a trailing numeric layer segment first so `layer_index` always
    selects the layer, instead of silently doubling it into
    `.../FeatureServer/0/0/query` on a portal like Saskatchewan's. Pass
    a `layer_index` resolved by `default_layer_index` rather than a
    bare `0` unless the caller already knows the right id.

    `output_format` (confirmed live equally supported by every ArcGIS
    REST deployment in this codebase so far) defaults to plain esri
    JSON, matching every caller before this parameter existed; pass
    `"geojson"` for a standard `FeatureCollection` shape instead.
    `out_sr` reprojects returned geometry (e.g. `4326` for WGS84 lat/
    lon) — only meaningful together with `return_geometry=True`, and
    omitted from the request entirely when left `None` so a service's
    own native spatial reference is returned unchanged, the same
    default every existing caller already relies on.
    """
    _require_arcgis_rest_url(config, "query_layer", service_url)
    params: dict[str, Any] = {
        "where": where,
        "outFields": out_fields,
        "f": output_format,
        "resultRecordCount": limit,
        "resultOffset": offset,
        "returnGeometry": str(return_geometry).lower(),
    }
    if order_by:
        params["orderByFields"] = order_by
    if out_sr is not None:
        params["outSR"] = out_sr
    url = f"{_service_root(service_url)}/{layer_index}/query"
    body = await _get(config, f"{config.source}:query_layer:{layer_index}", url, params)
    _raise_if_embedded_error(config.source, "query_layer", body)
    return body


def parse_epoch_millis(value: object) -> datetime | None:
    """Convert a Hub Search API Unix-milliseconds timestamp to a datetime.

    Confirmed live: `created`/`modified` on a search result are integer
    Unix milliseconds, not ISO-8601 strings.
    """
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def excerpt(text: str, max_length: int) -> str:
    text = text.strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"
