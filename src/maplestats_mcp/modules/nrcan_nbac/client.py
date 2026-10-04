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
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.wfs import WfsConfig, get_features

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

    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            constants.TYPE_NAME,
            cql_filter=cql_filter,
            property_names=property_names,
            srs_name=constants.DEFAULT_SRS,
            sort_by=sort_by,
            count=limit,
            start_index=offset,
        )

    cache_key = f"nrcan-nbac:query:{cql_filter}:{include_geometry}:{sort_by}:{limit}:{offset}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_QUERY_SECONDS, fetch)
    features = body.get("features") or []
    fires = [_fire_record(feature) for feature in features]
    omitted = 0
    if include_geometry:
        used = 0
        for fire in fires:
            if fire.geometry is None:
                continue
            size = len(json.dumps(fire.geometry, separators=(",", ":")))
            if used + size > constants.GEOMETRY_BYTES_MAX:
                fire.geometry = None
                omitted += 1
            else:
                used += size
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
