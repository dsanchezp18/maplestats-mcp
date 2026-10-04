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
- `lang=fr` on `/collections` and `/collections/{id}` returns French
  titles and descriptions ("Alertes météo" for weather-alerts, confirmed
  live 2026-10-03); item properties are the same in both languages, with
  bilingual content in `_en`/`_fr` suffixed properties.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from maplestats_mcp.modules.eccc import constants
from maplestats_mcp.modules.eccc.schemas import (
    CollectionDetail,
    CollectionList,
    CollectionSummary,
    Feature,
    ItemsResult,
    Queryable,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.limits import fit_to_budget, join_limits, truncation_note
from maplestats_mcp.shared.rate_limiter import get_limiter

_MAX_KEYS_IN_ERROR = 25
_MAX_FRENCH_FIELDS = 12


def _raise(
    exc_cls: type[ValueError],
    en: str,
    fr: str,
    lang: str,
    cause: BaseException | None = None,
) -> NoReturn:
    """Raise the English message as before, or the French one in its typed template."""
    try:
        if lang == "fr":
            raise_typed(exc_cls, fr, "fr")
        raise exc_cls(en)
    except exc_cls as err:
        if cause is None:
            raise
        raise err from cause


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
    exc: httpx.HTTPStatusError, context: str, *, datetime_supplied: bool, lang: str = "en"
) -> NoReturn:
    status = exc.response.status_code
    description = _error_description(exc)
    # GeoMet's own error descriptions ("Collection not found") are English only.
    upstream_fr = f" (message de la source, en anglais : {description})" if description else ""
    if status == 404:
        _raise(
            NotFound,
            description or f"{context}: not found.",
            f"{context} : introuvable{upstream_fr}.",
            lang,
            exc,
        )
    if status == 400:
        _raise(
            InvalidInput,
            description or f"{context}: rejected the request (HTTP 400).",
            f"{context} : requête refusée (HTTP 400){upstream_fr}.",
            lang,
            exc,
        )
    if status == 500 and datetime_supplied:
        # Confirmed live: weather-alerts (and presumably other
        # collections) return a generic HTTP 500 for any `datetime`
        # value rather than a clean 400 - see module docstring.
        _raise(
            InvalidInput,
            f"{context}: this collection does not appear to support datetime filtering "
            f"(upstream returned HTTP 500: {description or 'query error'}). Retry without "
            "datetime_filter, or filter by bbox/property instead.",
            f"{context} : cette collection ne semble pas accepter le filtre de date "
            f"(la source a renvoyé HTTP 500{upstream_fr}). Réessayez sans datetime_filter, "
            "ou filtrez plutôt par bbox ou par propriété.",
            lang,
            exc,
        )
    _raise(
        UpstreamError,
        f"{context}: upstream returned HTTP {status}: {description}",
        f"{context} : HTTP {status}{upstream_fr}.",
        lang,
        exc,
    )


async def _get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    datetime_supplied: bool = False,
    lang: str = "en",
) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, path, datetime_supplied=datetime_supplied, lang=lang)
    except httpx.HTTPError as exc:
        _raise(
            UpstreamUnavailable,
            f"{path} did not respond in time (already retried by shared/http.py).",
            f"{path} n'a pas répondu à temps (après plusieurs essais).",
            lang,
            exc,
        )


def _require_id(value: str, kind: str, lang: str = "en") -> str:
    value = value.strip()
    if not value:
        _raise(InvalidInput, f"{kind} must not be empty.", f"{kind} ne doit pas être vide.", lang)
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


def _url(path: str, params: dict[str, Any]) -> str:
    """The request URL with its query string, so provenance reproduces the call."""
    return str(httpx.URL(f"{constants.BASE_URL}{path}", params=params))


async def _all_collections(lang: str = "en") -> tuple[list[CollectionSummary], bool]:
    # GeoMet answers `lang` with titles and descriptions in that language
    # (confirmed live 2026-10-03: climate-stations is "Climat - Stations" with
    # lang=fr); item properties carry both languages either way.
    async def fetch() -> list[CollectionSummary]:
        obj = await _get("/collections", params={"f": "json", "lang": lang}, lang=lang)
        return [_collection_summary(c) for c in list_or_empty(obj, "collections")]

    return await cached_fetch(
        f"eccc:collections:{lang}", constants.CACHE_TTL_COLLECTIONS_SECONDS, fetch
    )


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


async def list_collections(lang: str = "en") -> CollectionList:
    collections, was_cached = await _all_collections(lang)
    return CollectionList(
        collections=collections,
        total_count=len(collections),
        provenance=make_provenance(
            source="eccc",
            url=_url("/collections", {"f": "json", "lang": lang}),
            cached=was_cached,
            schema_name="eccc.CollectionList",
            lang=lang,
        ),
    )


async def search_collections(
    query: str, *, limit: int = constants.COLLECTIONS_SEARCH_LIMIT_DEFAULT, lang: str = "en"
) -> CollectionList:
    """Client-side substring search over the cached collection inventory.

    Matches the English and the French titles, descriptions and keywords
    (an "alerte" search found nothing when only English text was read),
    and returns the collections in `lang`.
    """
    all_collections = await list_collections(lang)
    other, _ = await _all_collections("fr" if lang == "en" else "en")
    hit_ids = {c.id for c in _filter_collections(other, query, len(other))}
    hit_ids |= {c.id for c in _filter_collections(all_collections.collections, query, 10**6)}
    matches = [c for c in all_collections.collections if c.id in hit_ids][:limit]
    searched = len(all_collections.collections)
    coverage = (
        french_spacing(
            f"au plus {limit} correspondances parmi les {searched} collections examinées "
            "(titres, descriptions et mots-clés en français et en anglais)"
        )
        if lang == "fr"
        else f"top {limit} matches of {searched} collections searched"
    )
    return CollectionList(
        collections=matches,
        total_count=len(matches),
        provenance=make_provenance(
            source="eccc",
            url=_url("/collections", {"f": "json", "lang": lang}),
            cached=all_collections.provenance.cached,
            schema_name="eccc.CollectionList",
            coverage=coverage,
            lang=lang,
        ),
    )


async def _queryables(collection_id: str, lang: str = "en") -> tuple[list[Queryable], bool]:
    segment = _path_segment(collection_id)

    async def fetch() -> list[Queryable]:
        obj = await _get(f"/collections/{segment}/queryables", params={"f": "json"}, lang=lang)
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


async def get_collection(collection_id: str, lang: str = "en") -> CollectionDetail:
    collection_id = _require_id(collection_id, "collection_id", lang)
    segment = _path_segment(collection_id)
    params = {"f": "json", "lang": lang}

    async def fetch() -> dict[str, Any]:
        return await _get(f"/collections/{segment}", params=params, lang=lang)

    detail, was_cached = await cached_fetch(
        f"eccc:collection:{collection_id}:{lang}",
        constants.CACHE_TTL_COLLECTION_DETAIL_SECONDS,
        fetch,
    )
    queryables, _ = await _queryables(collection_id, lang)
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
            url=_url(f"/collections/{segment}", params),
            cached=was_cached,
            schema_name="eccc.CollectionDetail",
            # Property names (queryables) are the source's identifiers, the
            # same in both languages; only the title and description change.
            limits=french_spacing(
                "Les noms des propriétés interrogeables sont les identifiants de la source, "
                "identiques en français et en anglais."
            )
            if lang == "fr"
            else None,
            lang=lang,
        ),
    )


def _validate_known_properties(
    collection_id: str,
    queryables: list[Queryable],
    names: list[str],
    context: str,
    lang: str = "en",
) -> None:
    known = {q.name for q in queryables}
    unknown = [n for n in names if n not in known]
    if not unknown:
        return
    valid_preview = ", ".join(sorted(known)[:_MAX_KEYS_IN_ERROR])
    more = ", ..." if len(known) > _MAX_KEYS_IN_ERROR else ""
    _raise(
        InvalidInput,
        f"{context} for collection {collection_id!r} used unknown propert"
        f"{'y' if len(unknown) == 1 else 'ies'} {unknown!r} - an unrecognized property name is "
        "silently ignored by the upstream API and returns zero rows rather than an error "
        f"(confirmed live), so this is checked first. Known properties include: {valid_preview}"
        f"{more}.",
        f"{context} pour la collection {collection_id!r} : propriété"
        f"{'' if len(unknown) == 1 else 's'} inconnue{'' if len(unknown) == 1 else 's'} "
        f"{unknown!r}. La source ignore sans erreur un nom de propriété inconnu et renvoie "
        "zéro ligne ; il est donc vérifié avant l'appel. Propriétés connues, entre autres : "
        f"{valid_preview}{more}.",
        lang,
    )


_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$")


def _bad_datetime(value: str, lang: str, cause: BaseException | None = None) -> NoReturn:
    _raise(
        InvalidInput,
        _DATETIME_HELP.format(value=value),
        _DATETIME_HELP_FR.format(value=value),
        lang,
        cause,
    )


def _check_datetime(value: str, lang: str = "en") -> str:
    """Check an OGC datetime (an instant, or "start/end" with ".." open).

    A malformed value used to reach the server, whose HTTP 500 was then
    read as "this collection does not support datetime filtering" even on
    collections that do (hydrometric-realtime, live 2026-10-03).
    """
    value = value.strip()
    parts = value.split("/")
    if not value or len(parts) > 2:
        _bad_datetime(value, lang)
    for part in parts:
        if len(parts) == 2 and part in ("", ".."):
            continue
        if not _INSTANT.match(part):
            _bad_datetime(value, lang)
        try:
            if "T" in part:
                datetime.fromisoformat(part)
            else:
                date.fromisoformat(part)
        except ValueError as exc:
            _bad_datetime(value, lang, exc)
    return value


_DATETIME_HELP = (
    "datetime_filter must be an RFC 3339 date or date-time such as 2026-09-19 or "
    "2026-09-19T00:00:00Z, or an interval start/end with .. for an open end "
    "(2026-09-19T00:00:00Z/..), got {value!r}."
)
_DATETIME_HELP_FR = (
    "datetime_filter doit être une date ou une date-heure RFC 3339, comme 2026-09-19 ou "
    "2026-09-19T00:00:00Z, ou un intervalle début/fin avec .. pour une borne ouverte "
    "(2026-09-19T00:00:00Z/..) ; valeur reçue : {value!r}."
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
    lang: str = "en",
) -> ItemsResult:
    collection_id = _require_id(collection_id, "collection_id", lang)
    if limit < 1 or limit > constants.ITEMS_LIMIT_MAX:
        _raise(
            InvalidInput,
            f"limit must be between 1 and {constants.ITEMS_LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.ITEMS_LIMIT_MAX} ; valeur reçue : "
            f"{limit}.",
            lang,
        )
    if offset < 0:
        _raise(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être positif ou nul ; valeur reçue : {offset}.",
            lang,
        )
    if bbox is not None and len(bbox) != 4:
        _raise(
            InvalidInput,
            f"bbox must have exactly 4 values [west, south, east, north], got {len(bbox)}.",
            f"bbox doit contenir exactement 4 valeurs [ouest, sud, est, nord] ; reçu : "
            f"{len(bbox)}.",
            lang,
        )
    if datetime_filter is not None:
        datetime_filter = _check_datetime(datetime_filter, lang)

    filters = filters or {}
    names_to_check = list(filters.keys()) + list(fields or [])
    if sortby:
        names_to_check.append(sortby.lstrip("+-"))
    if names_to_check:
        queryables, _ = await _queryables(collection_id, lang)
        _validate_known_properties(
            collection_id, queryables, names_to_check, "filters/fields/sortby", lang
        )

    params: dict[str, Any] = {
        "f": "json",
        "lang": lang,
        "limit": limit,
        "offset": offset,
        **filters,
    }
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
            lang=lang,
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ITEMS_SECONDS, fetch)
    received = [_feature_from_json(f) for f in list_or_empty(obj, "features")]
    # Some collections carry hundreds of properties per row (SWOB
    # observations are about 8.3 KB an item, so 50 rows were 415 KB live,
    # 2026-10-03); the byte budget keeps a page usable.
    features = fit_to_budget(received, constants.ITEMS_BYTES_MAX)
    number_matched = obj.get("numberMatched", len(received))
    budget_mb = constants.ITEMS_BYTES_MAX // 1_000_000
    if lang == "fr":
        return _items_result_fr(
            collection_id,
            features,
            received_count=len(received),
            number_matched=number_matched,
            limit=limit,
            offset=offset,
            url=_url(f"/collections/{segment}/items", params),
            cached=was_cached,
        )
    note = None
    if len(features) < len(received):
        note = (
            f"Stopped at {len(features)} of the {len(received)} rows fetched: they reach the "
            f"{budget_mb} MB response budget. Continue with "
            f"offset={offset + len(features)}, or pass fields to return fewer properties."
        )
    return ItemsResult(
        collection_id=collection_id,
        items=features,
        number_matched=number_matched,
        number_returned=len(features),
        limit=limit,
        offset=offset,
        note=note,
        provenance=make_provenance(
            source="eccc",
            url=_url(f"/collections/{segment}/items", params),
            cached=was_cached,
            schema_name="eccc.ItemsResult",
            coverage=f"{len(features)} of {number_matched} matching items returned",
            limits=join_limits(
                f"limit capped at {constants.ITEMS_LIMIT_MAX} per request",
                truncation_note(
                    returned=len(features),
                    total=len(received),
                    unit=f"items received (cut to about {constants.ITEMS_BYTES_MAX // 1_000_000} MB)",
                    how_to_get_more="select fewer `fields`, lower limit and page with offset",
                ),
            ),
        ),
    )


def _french_fields(features: list[Feature]) -> list[str]:
    """Names of the French-language properties (`_fr`/`_FR` suffix) in these rows."""
    names = {
        key for feature in features for key in feature.properties if key.lower().endswith("_fr")
    }
    return sorted(names)


def _items_result_fr(
    collection_id: str,
    features: list[Feature],
    *,
    received_count: int,
    number_matched: int,
    limit: int,
    offset: int,
    url: str,
    cached: bool,
) -> ItemsResult:
    """The French result: same rows, with French note and provenance text.

    GeoMet's `lang` does not translate item properties (confirmed live
    2026-10-04 on hydrometric-stations: STATUS_EN "Discontinued" and
    STATUS_FR "Fermée" come back either way), so the note points to the
    `_fr` properties instead of rewriting rows.
    """
    budget_mb = constants.ITEMS_BYTES_MAX // 1_000_000
    notes = []
    if len(features) < received_count:
        notes.append(
            f"Arrêt à {len(features)} des {received_count} lignes reçues : elles atteignent "
            f"le plafond de {budget_mb} Mo par réponse. Continuez avec "
            f"offset={offset + len(features)}, ou passez fields pour renvoyer moins de "
            "propriétés."
        )
    french = _french_fields(features)
    if french:
        shown = ", ".join(french[:_MAX_FRENCH_FIELDS])
        more = ", ..." if len(french) > _MAX_FRENCH_FIELDS else ""
        notes.append(
            "Les propriétés sont reproduites telles que publiées. Les textes bilingues de la "
            f"source sont en double (suffixes _en et _fr) ; en français : {shown}{more}. Les "
            "autres noms de propriétés et valeurs n'existent qu'en anglais."
        )
    elif features:
        notes.append(
            "Les propriétés sont reproduites telles que publiées ; cette collection ne fournit "
            "ses noms et ses valeurs qu'en anglais."
        )
    truncated = (
        f"{len(features)} des {received_count} lignes reçues renvoyées (coupées à environ "
        f"{budget_mb} Mo) ; choisissez moins de propriétés avec fields, baissez limit et "
        "paginez avec offset"
        if len(features) < received_count
        else None
    )
    limits = join_limits(f"limit plafonné à {constants.ITEMS_LIMIT_MAX} par requête", truncated)
    return ItemsResult(
        collection_id=collection_id,
        items=features,
        number_matched=number_matched,
        number_returned=len(features),
        limit=limit,
        offset=offset,
        note=french_spacing(" ".join(notes)) if notes else None,
        provenance=make_provenance(
            source="eccc",
            url=url,
            cached=cached,
            schema_name="eccc.ItemsResult",
            coverage=french_spacing(
                f"{len(features)} entités renvoyées sur {number_matched} correspondantes"
            ),
            limits=french_spacing(limits) if limits else None,
            lang="fr",
        ),
    )
