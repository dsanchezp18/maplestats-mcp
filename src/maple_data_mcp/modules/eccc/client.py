"""HTTP client for the MSC GeoMet-OGC-API (api.weather.gc.ca).

Every function wraps `shared.http.api_get` through the eccc rate
limiter and either returns a typed model or raises a `shared/errors.py`
exception. The following was confirmed live against
https://api.weather.gc.ca this session (not assumed from
https://eccc-msc.github.io/open-data/msc-geomet/readme_en/ prose
alone):

- `/collections?f=json` -> {"collections": [{id, title, description,
  keywords, links, extent: {spatial: {bbox, crs}}, itemType, crs,
  storageCRS}, ...]}. 100+ entries measured live spanning weather
  alerts, current conditions/surface observations (SWOB), city
  forecasts, AQHI, climate stations/daily/hourly/monthly/normals,
  hydrometric stations/real-time/historical, marine, hurricanes, and
  several downscaled-climate-projection families. Cached whole.
- `/collections/{id}?f=json` -> the same per-collection shape as one
  entry above, plus (not present on the list endpoint) a `links` entry
  with `rel: "http://www.opengis.net/def/rel/ogc/1.0/queryables"`.
  `/collections/{id}/queryables?f=json` -> JSON Schema
  {"properties": {name: {"title", "type", ...}, ...}} - the actual
  filterable/orderable property names for that collection, genuinely
  different per collection (confirmed against weather-alerts:
  alert_code/province/... vs. hydrometric-realtime:
  STATION_NUMBER/LEVEL/DISCHARGE/...).
- `/collections/{id}/items?f=json` -> GeoJSON
  {"type": "FeatureCollection", "features": [{id, type, geometry,
  properties}, ...], "numberMatched", "numberReturned", "links",
  "timeStamp"}. Confirmed identical envelope shape across every
  collection checked (weather-alerts, hydrometric-realtime,
  climate-stations, aqhi-observations-realtime, aqhi-forecasts-realtime,
  swob-realtime). `offset`/`limit` are the pagination params (a `next`
  link on a truncated response carries `offset=<n>`, confirmed live) -
  0-based, matching this project's convention elsewhere.
- **Bare property-name query params filter by equality** (e.g.
  `?province=ON`, `?STATION_NUMBER=05BL023`), confirmed live against
  weather-alerts and hydrometric-realtime, and combine as AND when
  several are given together. **An unknown/misspelled property name is
  not rejected** - it is silently ignored and the filter matches
  nothing (`?not_a_real_property=xyz` returns HTTP 200 with
  `numberMatched: 0`, confirmed live), which looks identical to "no
  rows match" from the caller's perspective. `_validate_filter_keys`
  below checks caller-supplied filter/sortby/field names against this
  collection's own `/queryables` before sending the request, so a typo
  raises `InvalidInput` naming the bad key instead of silently
  returning zero rows.
- **`bbox` filtering works as documented** (OGC API - Features core):
  `west,south,east,north` in CRS84 (WGS84 lon/lat), confirmed live.
- **`datetime` filtering support is genuinely inconsistent per
  collection and is not predictable from a collection's own metadata.**
  Confirmed live: `hydrometric-realtime` (435,353 rows measured this
  session) accepts `datetime=2026-09-19T00:00:00Z/..` and filters
  correctly; `weather-alerts` returns HTTP 500
  `{"code": "NoApplicableCode", "description": "query error (check
  logs)"}` for *any* `datetime` value, including a bare date. Neither
  collection's own extent document distinguishes "has a queryable
  datetime" from "does not" - both report only a `spatial` extent, no
  `temporal` block. `query_items` below cannot know in advance which
  collections support it, so a `datetime_filter`-triggered HTTP 500 is
  caught and re-raised as `InvalidInput` (a caller-actionable "this
  collection doesn't support that", not a generic upstream failure)
  rather than `UpstreamError`.
- **The server enforces no upper bound on `limit`** - `limit=100000`
  against an 88-row collection was honoured in full with no error or
  truncation (confirmed live). Several collections here have hundreds
  of thousands of rows (see `hydrometric-realtime` above), so this
  client enforces its own cap (`constants.ITEMS_LIMIT_MAX`) rather than
  trusting a caller-supplied limit.
- **`climate-stations`' `LATITUDE`/`LONGITUDE` properties are integers
  scaled by 1e7, not decimal degrees** (confirmed live:
  `LATITUDE: 485500000` / `LONGITUDE: -1234200000` for a station at
  48.55 N, -123.42 W). The feature's own GeoJSON `geometry` carries
  correct decimal coordinates - `properties` is returned verbatim here
  (see schemas.py's module docstring), so this is left for a caller to
  handle, but is called out in docs://eccc/gotchas since it is easy to
  misread as plain degrees.
- Unknown collection id -> HTTP 404
  `{"code": "NotFound", "description": "Collection not found"}`.
- No numeric rate limit is published, and no X-RateLimit-*/Retry-After
  style header was present on any live response checked this session -
  see constants.py for the conservative default used in its place.
"""

from __future__ import annotations

from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from maple_data_mcp.modules.eccc import constants
from maple_data_mcp.modules.eccc.schemas import (
    CollectionDetail,
    CollectionList,
    CollectionSummary,
    Feature,
    ItemsResult,
    Queryable,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.json_utils import list_or_empty
from maple_data_mcp.shared.rate_limiter import get_limiter

_MAX_KEYS_IN_ERROR = 25


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _error_description(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return ""
    return body.get("description", "") if isinstance(body, dict) else ""


def _raise_for_status(
    exc: httpx.HTTPStatusError, context: str, *, datetime_supplied: bool
) -> NoReturn:
    status = exc.response.status_code
    description = _error_description(exc)
    if status == 404:
        raise NotFound(description or f"{context}: not found.") from exc
    if status == 400:
        raise InvalidInput(description or f"{context}: rejected the request (HTTP 400).") from exc
    if status == 500 and datetime_supplied:
        # Confirmed live: weather-alerts (and presumably other
        # collections) return a generic HTTP 500 for any `datetime`
        # value rather than a clean 400 - see module docstring.
        raise InvalidInput(
            f"{context}: this collection does not appear to support datetime filtering "
            f"(upstream returned HTTP 500: {description or 'query error'}). Retry without "
            "datetime_filter, or filter by bbox/property instead."
        ) from exc
    raise UpstreamError(f"{context}: upstream returned HTTP {status}: {description}") from exc


async def _get(
    path: str, params: dict[str, Any] | None = None, *, datetime_supplied: bool = False
) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, path, datetime_supplied=datetime_supplied)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{path} did not respond in time (already retried by shared/http.py)."
        ) from exc


def _require_id(value: str, kind: str) -> str:
    value = value.strip()
    if not value:
        raise InvalidInput(f"{kind} must not be empty.")
    return value


def _path_segment(value: str) -> str:
    """Percent-encode a collection id before splicing it into a URL path."""
    return quote(value, safe="")


def _collection_summary(obj: dict[str, Any]) -> CollectionSummary:
    return CollectionSummary(
        id=obj["id"],
        title=obj.get("title", ""),
        description=obj.get("description", ""),
        keywords=list_or_empty(obj, "keywords"),
        item_type=obj.get("itemType", "unknown"),
    )


async def _all_collections() -> tuple[list[CollectionSummary], bool]:
    async def fetch() -> list[CollectionSummary]:
        obj = await _get("/collections", params={"f": "json"})
        return [_collection_summary(c) for c in list_or_empty(obj, "collections")]

    return await cached_fetch("eccc:collections", constants.CACHE_TTL_COLLECTIONS_SECONDS, fetch)


def _filter_collections(
    items: list[CollectionSummary], query: str, limit: int
) -> list[CollectionSummary]:
    if not query:
        return items[:limit]
    needle = query.lower()
    return [
        item
        for item in items
        if needle in item.id.lower()
        or needle in item.title.lower()
        or needle in item.description.lower()
        or any(needle in kw.lower() for kw in item.keywords)
    ][:limit]


async def list_collections() -> CollectionList:
    collections, was_cached = await _all_collections()
    return CollectionList(
        collections=collections,
        total_count=len(collections),
        provenance=make_provenance(
            source="eccc",
            url=f"{constants.BASE_URL}/collections?f=json",
            cached=was_cached,
            schema_name="eccc.CollectionList",
        ),
    )


async def search_collections(
    query: str, *, limit: int = constants.COLLECTIONS_SEARCH_LIMIT_DEFAULT
) -> CollectionList:
    """Client-side substring search over the cached collection inventory."""
    all_collections = await list_collections()
    matches = _filter_collections(all_collections.collections, query, limit)
    return CollectionList(
        collections=matches,
        total_count=len(matches),
        provenance=make_provenance(
            source="eccc",
            url=f"{constants.BASE_URL}/collections?f=json",
            cached=all_collections.provenance.cached,
            schema_name="eccc.CollectionList",
            coverage=f"top {limit} matches of {len(all_collections.collections)} collections searched",
        ),
    )


async def _queryables(collection_id: str) -> tuple[list[Queryable], bool]:
    segment = _path_segment(collection_id)

    async def fetch() -> list[Queryable]:
        obj = await _get(f"/collections/{segment}/queryables", params={"f": "json"})
        properties = obj.get("properties") or {}
        return [
            Queryable(name=name, type=schema.get("type")) for name, schema in properties.items()
        ]

    return await cached_fetch(
        f"eccc:queryables:{collection_id}", constants.CACHE_TTL_COLLECTION_DETAIL_SECONDS, fetch
    )


def _find_link_href(links: list[dict[str, Any]], rel: str) -> str | None:
    for link in links:
        if link.get("rel") == rel:
            href = link.get("href")
            # Confirmed live that this API's root document uses a
            # bilingual {"en": ..., "fr": ...} href dict on its "about"
            # link rather than a plain string (every "canonical"/
            # "download" link checked on a collection detail page was a
            # plain string) - guarded here too so an unexpected dict
            # shape is skipped instead of failing CollectionDetail's
            # str | None validation.
            if isinstance(href, str):
                return href
    return None


async def get_collection(collection_id: str) -> CollectionDetail:
    collection_id = _require_id(collection_id, "collection_id")
    segment = _path_segment(collection_id)

    async def fetch() -> dict[str, Any]:
        return await _get(f"/collections/{segment}", params={"f": "json"})

    detail, was_cached = await cached_fetch(
        f"eccc:collection:{collection_id}", constants.CACHE_TTL_COLLECTION_DETAIL_SECONDS, fetch
    )
    queryables, _ = await _queryables(collection_id)
    bbox_list = (detail.get("extent") or {}).get("spatial", {}).get("bbox") or []
    links = list_or_empty(detail, "links")
    return CollectionDetail(
        id=detail.get("id", collection_id),
        title=detail.get("title", ""),
        description=detail.get("description", ""),
        keywords=list_or_empty(detail, "keywords"),
        item_type=detail.get("itemType", "unknown"),
        bbox=list(bbox_list[0]) if bbox_list else None,
        queryables=queryables,
        canonical_url=_find_link_href(links, "canonical"),
        download_url=_find_link_href(links, "download"),
        provenance=make_provenance(
            source="eccc",
            url=f"{constants.BASE_URL}/collections/{collection_id}?f=json",
            cached=was_cached,
            schema_name="eccc.CollectionDetail",
        ),
    )


def _validate_known_properties(
    collection_id: str, queryables: list[Queryable], names: list[str], context: str
) -> None:
    known = {q.name for q in queryables}
    unknown = [n for n in names if n not in known]
    if not unknown:
        return
    valid_preview = ", ".join(sorted(known)[:_MAX_KEYS_IN_ERROR])
    raise InvalidInput(
        f"{context} for collection {collection_id!r} used unknown propert"
        f"{'y' if len(unknown) == 1 else 'ies'} {unknown!r} - an unrecognized property name is "
        "silently ignored by the upstream API and returns zero rows rather than an error "
        f"(confirmed live), so this is checked first. Known properties include: {valid_preview}"
        f"{', ...' if len(known) > _MAX_KEYS_IN_ERROR else ''}."
    )


def _feature_from_json(obj: dict[str, Any]) -> Feature:
    return Feature(
        id=obj.get("id"),
        geometry=obj.get("geometry"),
        properties=obj.get("properties") or {},
    )


async def query_items(
    collection_id: str,
    *,
    bbox: list[float] | None = None,
    datetime_filter: str | None = None,
    filters: dict[str, str] | None = None,
    fields: list[str] | None = None,
    sortby: str | None = None,
    limit: int = constants.ITEMS_LIMIT_DEFAULT,
    offset: int = 0,
) -> ItemsResult:
    collection_id = _require_id(collection_id, "collection_id")
    if limit < 1 or limit > constants.ITEMS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ITEMS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    if bbox is not None and len(bbox) != 4:
        raise InvalidInput(
            f"bbox must have exactly 4 values [west, south, east, north], got {len(bbox)}."
        )

    filters = filters or {}
    names_to_check = list(filters.keys()) + list(fields or [])
    if sortby:
        names_to_check.append(sortby.lstrip("+-"))
    if names_to_check:
        queryables, _ = await _queryables(collection_id)
        _validate_known_properties(
            collection_id, queryables, names_to_check, "filters/fields/sortby"
        )

    params: dict[str, Any] = {"f": "json", "limit": limit, "offset": offset, **filters}
    if bbox is not None:
        params["bbox"] = ",".join(str(v) for v in bbox)
    if datetime_filter is not None:
        params["datetime"] = datetime_filter
    if fields:
        params["properties"] = ",".join(fields)
    if sortby:
        params["sortby"] = sortby
    segment = _path_segment(collection_id)
    cache_key = f"eccc:items:{collection_id}:{sorted(params.items())}"

    async def fetch() -> dict[str, Any]:
        return await _get(
            f"/collections/{segment}/items",
            params=params,
            datetime_supplied=datetime_filter is not None,
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ITEMS_SECONDS, fetch)
    features = [_feature_from_json(f) for f in list_or_empty(obj, "features")]
    number_matched = obj.get("numberMatched", len(features))
    return ItemsResult(
        collection_id=collection_id,
        items=features,
        number_matched=number_matched,
        number_returned=obj.get("numberReturned", len(features)),
        limit=limit,
        offset=offset,
        provenance=make_provenance(
            source="eccc",
            url=f"{constants.BASE_URL}/collections/{collection_id}/items",
            cached=was_cached,
            schema_name="eccc.ItemsResult",
            coverage=f"{len(features)} of {number_matched} matching items returned",
            limits=f"limit capped at {constants.ITEMS_LIMIT_MAX} per request",
        ),
    )
