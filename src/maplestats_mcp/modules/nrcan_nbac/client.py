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

from datetime import date
from typing import Any

from maplestats_mcp.modules.nrcan_nbac import constants
from maplestats_mcp.modules.nrcan_nbac.schemas import FireQueryResult, FireRecord
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.wfs import WfsConfig, get_features

CONFIG = WfsConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


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


async def query_fires(
    *,
    cql_filter: str | None = None,
    include_geometry: bool = False,
    sort_by: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FireQueryResult:
    """Query fire polygons/records from NBAC; ``lang`` is accepted for consistency.

    ``cql_filter`` is a standard OGC CQL expression against NBAC's own
    field names, e.g. ``"admin_area = 'BC' AND year >= 2017 AND year
    <= 2024"``. Leave ``include_geometry`` false (the default) for a
    lightweight attribute-only query -- NBAC's polygons can be large,
    and most analyses only need the dates/area/admin_area columns.
    """
    del lang
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

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
    total_matched = body.get("numberMatched") or body.get("totalFeatures") or len(fires)
    return FireQueryResult(
        fires=fires,
        returned_count=len(fires),
        total_matched=total_matched,
        limit=limit,
        offset=offset,
        cql_filter=cql_filter,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?typeName={constants.TYPE_NAME}",
            cached=was_cached,
            schema_name="nrcan_nbac.FireQueryResult",
            coverage=f"{len(fires)} of {total_matched} total matching fires returned",
            limits=f"rows capped at {constants.ROWS_LIMIT_MAX} per request",
            freshness="NBAC is compiled annually, not updated in real time",
        ),
    )
