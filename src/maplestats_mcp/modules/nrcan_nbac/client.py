"""HTTP client for NRCan's National Burned Area Composite (NBAC) WFS layer.

Field names and shapes confirmed live against real `public:nbac`
features -- see shared/wfs.py for the OGC WFS 2.0 platform quirks this
client relies on. One additional quirk specific to this layer: date
fields (`hs_sdate`, `ag_sdate`, `capdate`, etc.) are plain calendar
dates with a trailing literal "Z" (e.g. "2024-08-12Z"), not a full
ISO-8601 timestamp -- `date.fromisoformat` rejects the "Z" suffix
directly, so `_parse_nbac_date` strips it first.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, NoReturn

from maplestats_mcp.modules.nrcan_nbac import constants
from maplestats_mcp.modules.nrcan_nbac.schemas import FireQueryResult, FireRecord
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.wfs import WfsConfig, feature_url, get_features

CONFIG = WfsConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _pick(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def _parse_nbac_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def _fire_record(feature: dict[str, Any]) -> FireRecord:
    props = feature.get("properties") or {}
    return FireRecord(
        year=props["year"],
        fire_id=props["nfireid"],
        admin_area=props.get("admin_area") or None,
        burn_source=props.get("basrc") or None,
        fire_cause=props.get("firecaus") or None,
        hotspot_start_date=_parse_nbac_date(props.get("hs_sdate")),
        hotspot_end_date=_parse_nbac_date(props.get("hs_edate")),
        agency_start_date=_parse_nbac_date(props.get("ag_sdate")),
        agency_end_date=_parse_nbac_date(props.get("ag_edate")),
        capture_date=_parse_nbac_date(props.get("capdate")),
        polygon_area_ha=props.get("poly_ha"),
        adjusted_area_ha=props.get("adj_ha"),
        adjustment_flag=props.get("adj_flag") or None,
        national_park=props.get("natpark") or None,
        prescribed=props.get("prescribed") or None,
        version=props.get("version") or None,
        geometry=feature.get("geometry"),
    )


async def _geometry_features(request: dict[str, Any], lang: str) -> dict[str, Any]:
    """GetFeature with geometry, read under GEOMETRY_RESPONSE_BYTES_MAX.

    `get_features` buffers and parses the whole response, which for polygons
    can be tens of MB, so this goes through the streaming reader: a declared
    Content-Length above the cap is refused unread, and an undeclared one
    (GeoServer's usual chunked answer) stops at the cap.
    """
    url = feature_url(CONFIG, constants.TYPE_NAME, **request)
    limiter = get_limiter(
        CONFIG.source, rate=CONFIG.rate_limit_per_second, capacity=CONFIG.rate_limit_capacity
    )
    try:
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host == constants.DOMAIN,
            limiter_for=lambda _host: limiter,
            max_bytes=constants.GEOMETRY_RESPONSE_BYTES_MAX,
            context="nrcan_nbac",
            timeout=120.0,
        )
    except UpstreamError as exc:
        # The streaming reader calls every refused request "HTTP 400", and the
        # service's own reason (a malformed CQL filter) is what the caller
        # needs. Ask for one attribute-only row: it raises InvalidInput with
        # that reason when the request itself is bad, and succeeds when the
        # failure was the size or the service.
        await get_features(
            CONFIG,
            constants.TYPE_NAME,
            cql_filter=request["cql_filter"],
            property_names="year",
            sort_by=request["sort_by"],
            count=1,
        )
        megabytes = constants.GEOMETRY_RESPONSE_BYTES_MAX // (1024 * 1024)
        _raise(
            UpstreamError,
            f"nrcan_nbac: the request with geometry failed or is over the {megabytes} MB "
            f"response limit. Ask for fewer fires (limit=1) or set include_geometry=false. "
            f"Cause: {exc}",
            f"nrcan_nbac : la requête avec géométrie a échoué ou dépasse la limite de "
            f"{megabytes} Mo. Demandez moins de feux (limit=1) ou passez "
            f"include_geometry=false. Cause : {exc}",
            lang,
        )
    try:
        body = json.loads(downloaded.body)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        _raise(
            UpstreamError,
            "nrcan_nbac: the geometry response was not a GeoJSON object.",
            "nrcan_nbac : la réponse avec géométrie n'est pas un objet GeoJSON.",
            lang,
        )
    return body


def _trim_geometry(body: dict[str, Any]) -> dict[str, Any]:
    """The body with polygons past GEOMETRY_BYTES_MAX dropped, and how many.

    Trimmed before the result is cached, so the cache holds the budgeted
    result and not the full GeoJSON (five 2023 BC fires were 33 MB).
    """
    omitted = 0
    used = 0
    for feature in body.get("features") or []:
        geometry = feature.get("geometry")
        if geometry is None:
            continue
        size = len(json.dumps(geometry, separators=(",", ":")))
        if used + size > constants.GEOMETRY_BYTES_MAX:
            feature["geometry"] = None
            omitted += 1
        else:
            used += size
    body["geometry_omitted"] = omitted
    return body


async def latest_year() -> int | None:
    """The most recent fire year in the layer (2024 on 2026-10-03; year=2025
    returned nothing, with no hint that the data stop there)."""

    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            constants.TYPE_NAME,
            property_names="year",
            srs_name=constants.DEFAULT_SRS,
            sort_by="year D",
            count=1,
        )

    body, _ = await cached_fetch("nrcan-nbac:latest-year", constants.CACHE_TTL_QUERY_SECONDS, fetch)
    features = body.get("features") or []
    year = (features[0].get("properties") or {}).get("year") if features else None
    return int(year) if isinstance(year, int | float) else None


async def query_fires(
    *,
    cql_filter: str | None = None,
    include_geometry: bool = False,
    sort_by: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FireQueryResult:
    """Query fire polygons/records from NBAC; ``lang`` picks the language of notes and errors.

    ``cql_filter`` is a standard OGC CQL expression against NBAC's own
    field names, e.g. ``"admin_area = 'BC' AND year >= 2017 AND year
    <= 2024"``. Leave ``include_geometry`` false (the default) for a
    lightweight attribute-only query -- NBAC's polygons can be large,
    and most analyses only need the dates/area/admin_area columns.
    """
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        _raise(
            InvalidInput,
            f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.ROWS_LIMIT_MAX}, reçu {limit}.",
            lang,
        )
    if offset < 0:
        _raise(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être >= 0, reçu {offset}.",
            lang,
        )
    requested = limit
    if include_geometry:
        limit = min(limit, constants.GEOMETRY_ROWS_MAX)

    property_names = None if include_geometry else constants.ATTRIBUTE_FIELDS

    request: dict[str, Any] = {
        "cql_filter": cql_filter,
        "property_names": property_names,
        "srs_name": constants.DEFAULT_SRS,
        "sort_by": sort_by,
        "count": limit,
        "start_index": offset,
    }

    async def fetch() -> dict[str, Any]:
        if not include_geometry:
            return await get_features(CONFIG, constants.TYPE_NAME, **request)
        return _trim_geometry(await _geometry_features(request, lang))

    cache_key = f"nrcan-nbac:query:{cql_filter}:{include_geometry}:{sort_by}:{limit}:{offset}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_QUERY_SECONDS, fetch)
    features = body.get("features") or []
    fires = [_fire_record(feature) for feature in features]
    omitted = int(body.get("geometry_omitted") or 0)
    total_matched = body.get("numberMatched") or body.get("totalFeatures") or len(fires)
    last_year = await latest_year()
    notes: list[str] = []
    budget_mb = constants.GEOMETRY_BYTES_MAX // 1_000_000
    if limit < requested:
        notes.append(
            _pick(
                f"With geometry, at most {limit} fires are returned per call (a single NBAC "
                f"polygon can be several MB); continue with offset={offset + len(fires)}.",
                f"Avec la géométrie, au plus {limit} feux sont renvoyés par appel (un seul "
                f"polygone du CNZB peut peser plusieurs Mo) ; continuez avec "
                f"offset={offset + len(fires)}.",
                lang,
            )
        )
    if omitted:
        notes.append(
            _pick(
                f"{omitted} polygon(s) left out: together they exceed the "
                f"{budget_mb} MB geometry budget. Ask for those "
                "fires one at a time, or use the NBAC shapefile download.",
                f"{omitted} polygone(s) omis : ensemble, ils dépassent le budget de "
                f"géométrie de {budget_mb} Mo. Demandez ces feux un à la fois, ou utilisez "
                "le téléchargement du fichier de formes du CNZB.",
                lang,
            )
        )
    if not fires and last_year is not None:
        notes.append(
            _pick(
                f"No fires matched; NBAC currently runs to fire year {last_year}.",
                f"Aucun feu ne correspond ; le CNZB va actuellement jusqu'à la saison des "
                f"feux {last_year}.",
                lang,
            )
        )
    if lang == "fr":
        notes.append(
            french_spacing(
                "Les codes de la source (admin_area, basrc, firecaus, etc.) sont reproduits "
                "tels quels."
            )
        )
    return FireQueryResult(
        fires=fires,
        returned_count=len(fires),
        total_matched=total_matched,
        limit=limit,
        offset=offset,
        cql_filter=cql_filter,
        latest_year=last_year,
        geometry_omitted=omitted,
        note=" ".join(notes) or None,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?typeName={constants.TYPE_NAME}",
            cached=was_cached,
            schema_name="nrcan_nbac.FireQueryResult",
            coverage=_pick(
                f"{len(fires)} of {total_matched} total matching fires returned",
                f"{len(fires)} feux renvoyés sur {total_matched} correspondants",
                lang,
            ),
            limits=_pick(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request",
                f"lignes plafonnées à {constants.ROWS_LIMIT_MAX} par requête",
                lang,
            ),
            freshness=_pick(
                "NBAC is compiled annually, not updated in real time"
                + (f"; latest fire year {last_year}" if last_year else ""),
                "Le CNZB est compilé chaque année, pas mis à jour en temps réel"
                + (f" ; dernière saison des feux : {last_year}" if last_year else ""),
                lang,
            ),
            lang=lang,
        ),
    )
