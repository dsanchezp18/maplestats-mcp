"""Shared plumbing for any Esri ArcGIS Hub deployment ("Data Hub" sites).

Confirmed live 2026-09-18 against geoportal.gov.mb.ca (Manitoba) and
data.princeedwardisland.ca (Prince Edward Island): every ArcGIS Hub
site — even one running on a fully custom government domain rather
than a *.hub.arcgis.com subdomain — proxies the same two APIs under its
own domain, so one client works for every portal. What differs per
portal (domain, collection, whether downloads work) stays in
modules/arcgis_hub/constants.py.

Two live-verified platform quirks this module encodes:

1. The Hub Search API v3 (an OGC API - Features-shaped catalogue) at
   `/api/search/v1/collections/dataset/items` is scoped to the site's
   own content by construction — no orgId/siteId parameter needed. The
   collection's own root document (`/api/search/v1/collections/dataset`)
   declares its `type` filter enum as CSV/Feature Service/Shapefile/
   KML/Table/Image Service and similar — never a web app or StoryMap.
   That does not make every item exportable: checked live 2026-10-03,
   the download API (`/api/download/v1`) answers HTTP 500 for File
   Geodatabase, Shapefile and CSV Collection items and 400 for Image
   Service items, and a Feature Service exports only the formats its
   own settings allow (Surrey's plan layers: geojson and kml, not csv
   or shapefile). `download_links` below therefore picks links by item
   kind. Errors here use real HTTP status codes
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
   (Ottawa's Planning/MapServer/277), and the layer/table id worth querying by default is
   not always 0 — a Prince Edward Island item's service had an empty
   `layers` list and its one queryable table at id 2. `_service_root`
   and `default_layer_index` below exist because of these two, found
   only by calling every function here against the portals live
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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, NoReturn

import httpx

from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.upstream_text import clean_detail, is_backend_outage, network_error

DOWNLOAD_FORMATS = ("csv", "shapefile", "geojson", "kml", "filegdb")
# A Hub item id is 32 hex digits; a layer-level item adds "_<layer id>".
# Checked live 2026-10-03: an unchecked id went straight into the URL path, so
# "../../../collections" read another resource and "x?f=html" added a query.
ITEM_ID_PATTERN = re.compile(r"^[0-9a-f]{32}(_\d+)?$")
# The Hub Search API pages through Elasticsearch, which refuses from + size
# above 10,000 with HTTP 500 (live 2026-10-03, Orangeville, startindex=10002).
SEARCH_WINDOW_MAX = 10_000
# Files stored on the item itself (not a service) are served by the item's
# /data resource: checked live 2026-10-03, a 302 to storage for a File
# Geodatabase or Shapefile and 206 for a ranged CSV read.
ITEM_DATA_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}/data"
_FILE_FORMATS = {
    "CSV": "csv",
    "CSV Collection": "zip",
    "Shapefile": "shapefile",
    "File Geodatabase": "filegdb",
    "GeoJson": "geojson",
    "KML": "kml",
    "KML Collection": "zip",
    "Microsoft Excel": "xlsx",
    "PDF": "pdf",
    "GeoPackage": "geopackage",
    "Microsoft Word": "docx",
    "Image": "image",
}
_SUPPORTED = re.compile(r"Supported file formats are ([a-zA-Z0-9_, ]+)")


class LayerNotQueryable(UpstreamError):
    """A catalogue item whose layer cannot be read by an anonymous query.

    Hub catalogues list such items as ordinary datasets anyway. Confirmed
    live 2026-09-26 on Red Deer's portal: "WAT_BulkWaterStation_PUBLIC"
    answers its service root with code 499 "Token Required" (secured), and a
    Survey123 form layer with capabilities "Create,Editing" answers a query
    with code 400 "This operation is not supported." (submit-only). Subclasses
    UpstreamError so existing handling is unchanged, but lets callers tell
    "cannot be read" apart from "broken" or "bad request".
    """


@dataclass(frozen=True)
class ArcGISHubConfig:
    """Per-portal configuration for the shared ArcGIS Hub client."""

    source: str
    domain: str
    rate_limit_per_second: float
    rate_limit_capacity: float
    # Open a new connection for every request. For a server behind a load
    # balancer that pins each connection to one backend: when one backend
    # fails, every retry on the reused connection fails with it (see the
    # statcan/geo config for the live case).
    fresh_connection_per_request: bool = False
    # The Hub Search API collection holding the site's datasets. Almost every
    # site has "dataset"; Okotoks's current site (maps-okotoks.hub.arcgis.com,
    # checked 2026-09-27) has only "all", which also lists Hub pages.
    collection: str = "dataset"


def _limiter(config: ArcGISHubConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return clean_detail(exc.response.text)
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, list) and message:
            return clean_detail("; ".join(str(item) for item in message))
        if isinstance(message, str) and message:
            return clean_detail(message)
        error = body.get("error")
        if isinstance(error, str) and error:
            return clean_detail(error)
    return clean_detail(exc.response.text)


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if status == 429 or (400 <= status < 500 and is_backend_outage(detail)):
        # A rate limit that outlasted shared/http.py's retries, or a 4xx naming the
        # server's own database or pool, is the service being unavailable, not a
        # mistake in the request (same rule as shared/wfs.py).
        raise UpstreamUnavailable(
            f"{context}: the service is temporarily unavailable (HTTP {status}: {detail}). "
            "Try again shortly."
        ) from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(config: ArcGISHubConfig, context: str, url: str, params: dict[str, Any]) -> Any:
    await _limiter(config).acquire()
    try:
        headers = {"Connection": "close"} if config.fresh_connection_per_request else None
        return await api_get(url, params=params, headers=headers)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise network_error(context, exc) from exc


def collection_url(config: ArcGISHubConfig) -> str:
    return f"https://{config.domain}/api/search/v1/collections/{config.collection}"


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
        config, f"{config.source}:search_items", f"{collection_url(config)}/items", params
    )


async def get_item(config: ArcGISHubConfig, item_id: str) -> dict[str, Any]:
    """Fetch one dataset item's full Hub Search API metadata."""
    url = f"{collection_url(config)}/items/{item_id}"
    return await _get(config, f"{config.source}:get_item:{item_id}", url, {})


def download_url(config: ArcGISHubConfig, item_id: str, fmt: str, *, layer_index: int = 0) -> str:
    """Build a direct export-download link for one item.

    `layer_index` must be the layer's own id in its service, not 0 by
    default: checked live 2026-09-27, Cochrane's "Parks" (layer 18) and
    Okotoks's "Floodway" (layer 35) answer `layers=0` with HTTP 404 and
    their real id with the 302 below.

    `https://<domain>/api/download/v1/items/<id>/<fmt>?layers=<n>`
    302-redirects to a hub.arcgis.com-hosted file (or answers 202 while
    it builds one) for a Feature Service in a format the service allows.
    It does not work for every item (see module docstring): build it
    only through `download_links`, which checks the item kind and the
    formats the download API itself lists.
    """
    return f"https://{config.domain}/api/download/v1/items/{item_id}/{fmt}?layers={layer_index}"


ItemKind = Literal["service", "file", "none"]


def item_kind(item_type: str, service_url: str | None) -> ItemKind:
    """How an item can be downloaded: export of a service, its stored file, or not at all.

    Checked live 2026-10-03 across Manitoba, Ottawa, Surrey and Burnaby: a
    Feature/Map Service exports through the download API; an item with no
    service url (CSV, CSV Collection, Shapefile, File Geodatabase) is a file
    stored on the item; an Image Service (raster) answers the download API
    with 400 and has no stored file either.
    """
    if item_type == "Image Service" or (service_url and "/ImageServer" in service_url):
        return "none"
    if service_url:
        return "service" if "/rest/services/" in service_url else "none"
    return "file"


def file_format(item_type: str) -> str:
    """A short format label for a file item's /data link."""
    return _FILE_FORMATS.get(item_type, "file")


def item_data_url(item_id: str) -> str:
    return ITEM_DATA_URL.format(item_id=item_id)


async def supported_download_formats(
    config: ArcGISHubConfig, item_id: str, layer_index: int
) -> tuple[str, ...]:
    """The export formats the download API accepts for one service item, in DOWNLOAD_FORMATS order.

    The API lists them itself when asked for a format it does not know:
    checked live 2026-10-03, `/api/download/v1/items/<id>/_?layers=<n>`
    answers 400 "Unsupported file format. Supported file formats are csv,
    shapefile, geojson, kml" on most portals, and "filegdb, geojson, kml"
    for Surrey's plan layers, whose csv and shapefile links answer 400.
    Any other answer (the API broken for the site, as Red Deer's 500, or a
    network failure) gives no formats, so no dead links are handed out.
    """

    async def fetch() -> tuple[str, ...]:
        await _limiter(config).acquire()
        url = f"https://{config.domain}/api/download/v1/items/{item_id}/_"
        try:
            await api_get(url, params={"layers": layer_index})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                return ()
            found = _SUPPORTED.search(_error_detail(exc))
            if not found:
                return ()
            listed = {part.strip().lower() for part in found.group(1).split(",")}
            return tuple(fmt for fmt in DOWNLOAD_FORMATS if fmt in listed)
        return ()

    # A network failure is not cached (it raises out of fetch), so the next
    # call asks again; it still yields no links for this answer.
    try:
        formats, _ = await cached_fetch(
            f"{config.source}:download_formats:{item_id}:{layer_index}", 60 * 60, fetch
        )
    except httpx.HTTPError:
        return ()
    return formats


def _service_root(service_url: str) -> str:
    trimmed = service_url.rstrip("/")
    head, _, tail = trimmed.rpartition("/")
    return head if tail.isdigit() else trimmed


def layer_query_url(service_url: str, layer_index: int) -> str:
    """The layer's query endpoint, also when service_url already names a layer
    (.../MapServer/28 gives .../MapServer/28/query, not .../28/28/query)."""
    return f"{_service_root(service_url)}/{layer_index}/query"


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
    # ArcGIS's fixed text for a layer without the Query capability; the
    # request itself was fine, so this is not the caller's InvalidInput.
    if code == 400 and "operation is not supported" in detail.lower():
        raise LayerNotQueryable(
            f"{source}:{context}: this layer does not allow queries (it is likely a "
            "submit-only form); use the item's download_urls if it has any, or another item."
        )
    if code == 400:
        raise InvalidInput(f"{source}:{context}: rejected the request ({detail}).")
    # Confirmed live against a plain ArcGIS Server deployment (StatCan's
    # geo.statcan.gc.ca): an unknown folder/service/layer answers this
    # same embedded shape with code 404 ("Folder not found"/"Service
    # not found"/"Layer not found") -- map it the same way a real HTTP
    # 404 status is mapped elsewhere in this codebase.
    if code == 404:
        raise NotFound(f"{source}:{context}: {detail or 'not found'}.")
    # 499 "Token Required" / 498 "Invalid Token": the service is secured.
    if code in (498, 499):
        raise LayerNotQueryable(
            f"{source}:{context}: this layer is secured and needs an ArcGIS login "
            f"({detail or 'Token Required'}), so it cannot be queried here; use the "
            "item's download_urls if it has any, or another item."
        )
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

    async def fetch() -> dict[str, Any]:
        return await get_service_info(config, service_url)

    # Cached: an item's detail (for its download links) and a query of the
    # same item both need it.
    info, _ = await cached_fetch(
        f"{config.source}:service_info:{_service_root(service_url)}", 60 * 60, fetch
    )
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
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query one FeatureServer/MapServer layer's rows via the ArcGIS REST API.

    `service_url` must be a `properties.url` value taken from this
    same portal's own search results (see module docstring point 2 for
    why this endpoint's errors need special handling); checking for
    `/rest/services/` (present on every ArcGIS REST endpoint, Esri-
    hosted or self-hosted — confirmed live: Burnaby's items point at
    `gis.burnaby.ca/arcgis/rest/services/...`, not an `*.arcgis.com`
    domain) is a cheap guard against a caller
    passing an arbitrary URL, not a documented upstream requirement.

    Confirmed live: an item's `url` is sometimes the bare service root
    (Manitoba: `.../FeatureServer`) and sometimes already a specific
    layer endpoint (Burnaby: `.../MapServer/10`) — the two
    portals differ in which layer of a possibly-multi-layer service
    their catalogue item happens to reference. `_service_root` strips
    a trailing numeric layer segment first so `layer_index` always
    selects the layer, instead of silently doubling it into
    `.../MapServer/10/10/query` on a portal like Burnaby's. Pass
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

    `extra_params` adds raw ArcGIS query parameters (e.g. the spatial
    filter `geometry`/`geometryType`/`inSR`/`spatialRel`) for callers
    that need them; it is merged last and absent for every other caller.
    """
    _require_arcgis_rest_url(config, "query_layer", service_url)
    url, params = _query_request(
        service_url,
        layer_index,
        where=where,
        out_fields=out_fields,
        order_by=order_by,
        return_geometry=return_geometry,
        limit=limit,
        offset=offset,
        output_format=output_format,
        out_sr=out_sr,
        extra_params=extra_params,
    )
    body = await _get(config, f"{config.source}:query_layer:{layer_index}", url, params)
    _raise_if_embedded_error(config.source, "query_layer", body)
    return body


def _query_request(
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
    extra_params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
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
    if extra_params:
        params.update(extra_params)
    return layer_query_url(service_url, layer_index), params


def query_url(service_url: str, layer_index: int, **kwargs: Any) -> str:
    """The full URL `query_layer` requests with the same arguments, for provenance."""
    url, params = _query_request(service_url, layer_index, **kwargs)
    return str(httpx.URL(url, params=params))


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
