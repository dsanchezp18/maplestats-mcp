"""Client for DataBC's public BCGW WFS 2.0 endpoint.

See shared/wfs.py for the OGC WFS 2.0 platform quirks this relies on
(GeoJSON on success, XML ExceptionReport on error, propertyName both
narrows fields and suppresses geometry). One quirk specific to BCGW,
confirmed live against both curated layers below: date fields (e.g.
`ISSUE_DATE`, `TRACK_DATE`) are plain calendar dates with a trailing
literal "Z" (e.g. "2026-07-16Z"), the same GML date-encoding quirk
already documented for NRCan's NBAC in modules/nrcan_nbac/client.py --
`date.fromisoformat` rejects the "Z" suffix directly, so `_parse_bc_date`
strips it first.

A second BCGW-specific quirk, confirmed live: `propertyName` narrows
returned fields but not exactly to the requested list -- this GeoServer
instance always adds back whatever it considers each layer's own
identifying field(s) (e.g. `FIRE_NUMBER`/`FIRE_YEAR` on the wildfire
layer) plus the `sortBy` field, on top of what was asked for. This is
harmless for the code here (every parser reads named fields out of the
response and ignores the rest) but means `ATTRIBUTE_FIELDS`'s job is
"ask for a lightweight response," not "guarantee exactly these fields
come back."
"""

from __future__ import annotations

from datetime import date
from typing import Any

from maplestats_mcp.modules.bcgw import constants
from maplestats_mcp.modules.bcgw.schemas import (
    LayerQueryResult,
    MiningTenureQueryResult,
    MiningTenureRecord,
    WildfireQueryResult,
    WildfireRecord,
)
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


def _parse_bc_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def _escape_cql_literal(value: str) -> str:
    """Double a literal single quote per standard CQL/SQL string escaping."""
    return value.replace("'", "''")


def _check_limit_offset(limit: int, offset: int) -> None:
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")


def _wildfire_record(feature: dict[str, Any]) -> WildfireRecord:
    props = feature.get("properties") or {}
    return WildfireRecord(
        fire_number=props["FIRE_NUMBER"],
        fire_year=props["FIRE_YEAR"],
        size_hectares=props.get("FIRE_SIZE_HECTARES"),
        status=props.get("FIRE_STATUS") or None,
        source=props.get("SOURCE") or None,
        track_date=_parse_bc_date(props.get("TRACK_DATE")),
        load_date=_parse_bc_date(props.get("LOAD_DATE")),
        url=props.get("FIRE_URL") or None,
        geometry=feature.get("geometry"),
    )


async def get_active_wildfires(
    *,
    status: str | None = None,
    fire_year: int | None = None,
    min_size_hectares: float | None = None,
    include_geometry: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> WildfireQueryResult:
    """Query current BC wildfire perimeters/status.

    Confirmed live 2026-09-22: `status` values observed include "Out of
    Control", "Being Held", "Under Control", and "Out" -- there is no
    fixed enum published, so this passes the value through rather than
    validating against a hardcoded list. There is no fire-centre/region
    field on this layer to filter by.
    """
    del lang
    _check_limit_offset(limit, offset)

    clauses: list[str] = []
    if status:
        clauses.append(f"FIRE_STATUS='{_escape_cql_literal(status)}'")
    if fire_year is not None:
        clauses.append(f"FIRE_YEAR={fire_year}")
    if min_size_hectares is not None:
        clauses.append(f"FIRE_SIZE_HECTARES>={min_size_hectares}")
    cql_filter = " AND ".join(clauses) if clauses else None

    property_names = None if include_geometry else constants.WILDFIRE_ATTRIBUTE_FIELDS

    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            constants.WILDFIRE_TYPE_NAME,
            cql_filter=cql_filter,
            property_names=property_names,
            srs_name=constants.DEFAULT_SRS,
            sort_by=constants.DEFAULT_SORT_FIELD,
            count=limit,
            start_index=offset,
        )

    cache_key = f"bcgw:wildfires:{cql_filter}:{include_geometry}:{limit}:{offset}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_WILDFIRE_SECONDS, fetch)
    features = body.get("features") or []
    wildfires = [_wildfire_record(feature) for feature in features]
    total_matched = body.get("numberMatched") or body.get("totalFeatures") or len(wildfires)

    return WildfireQueryResult(
        wildfires=wildfires,
        returned_count=len(wildfires),
        total_matched=total_matched,
        limit=limit,
        offset=offset,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?typeName={constants.WILDFIRE_TYPE_NAME}",
            cached=was_cached,
            schema_name="bcgw.WildfireQueryResult",
            coverage=f"{len(wildfires)} of {total_matched} total matching fires returned",
            freshness="updated as fire perimeters are re-mapped during fire season",
        ),
    )


def _mining_tenure_record(feature: dict[str, Any]) -> MiningTenureRecord:
    props = feature.get("properties") or {}
    return MiningTenureRecord(
        tenure_number_id=props["TENURE_NUMBER_ID"],
        claim_name=props.get("CLAIM_NAME") or None,
        tenure_type_code=props.get("TENURE_TYPE_CODE") or None,
        tenure_type_description=props.get("TENURE_TYPE_DESCRIPTION") or None,
        tenure_sub_type_description=props.get("TENURE_SUB_TYPE_DESCRIPTION") or None,
        title_type_description=props.get("TITLE_TYPE_DESCRIPTION") or None,
        issue_date=_parse_bc_date(props.get("ISSUE_DATE")),
        good_to_date=_parse_bc_date(props.get("GOOD_TO_DATE")),
        area_hectares=props.get("AREA_IN_HECTARES"),
        owner_name=props.get("OWNER_NAME") or None,
        percent_ownership=props.get("PERCENT_OWNERSHIP"),
        number_of_owners=props.get("NUMBER_OF_OWNERS"),
        statement_of_work_event_count=props.get("STATEMENT_OF_WORK_EVENT_COUNT"),
        termination_date=_parse_bc_date(props.get("TERMINATION_DATE")),
        geometry=feature.get("geometry"),
    )


_TENURE_TYPE_CODES = {"mineral": "M", "placer": "P"}


async def get_mining_tenure(
    *,
    tenure_type: str | None = None,
    owner_name: str | None = None,
    min_area_hectares: float | None = None,
    include_geometry: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> MiningTenureQueryResult:
    """Query acquired BC mineral/placer mining tenure (claims).

    `tenure_type` is "mineral" or "placer" (maps to BCGW's own 'M'/'P'
    TENURE_TYPE_CODE) if given. `owner_name` does a case-sensitive
    substring match against BCGW's own data, which is stored in upper
    case -- confirmed live -- so the input is upper-cased before matching
    rather than requiring the caller to know that.
    """
    del lang
    _check_limit_offset(limit, offset)
    if tenure_type is not None and tenure_type not in _TENURE_TYPE_CODES:
        raise InvalidInput(
            f"tenure_type must be one of {sorted(_TENURE_TYPE_CODES)}, got {tenure_type!r}."
        )

    clauses: list[str] = []
    if tenure_type is not None:
        clauses.append(f"TENURE_TYPE_CODE='{_TENURE_TYPE_CODES[tenure_type]}'")
    if owner_name:
        pattern = _escape_cql_literal(owner_name.upper())
        clauses.append(f"OWNER_NAME LIKE '%{pattern}%'")
    if min_area_hectares is not None:
        clauses.append(f"AREA_IN_HECTARES>={min_area_hectares}")
    cql_filter = " AND ".join(clauses) if clauses else None

    property_names = None if include_geometry else constants.MINING_TENURE_ATTRIBUTE_FIELDS

    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            constants.MINING_TENURE_TYPE_NAME,
            cql_filter=cql_filter,
            property_names=property_names,
            srs_name=constants.DEFAULT_SRS,
            sort_by=constants.DEFAULT_SORT_FIELD,
            count=limit,
            start_index=offset,
        )

    cache_key = f"bcgw:mining-tenure:{cql_filter}:{include_geometry}:{limit}:{offset}"
    body, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_MINING_TENURE_SECONDS, fetch
    )
    features = body.get("features") or []
    tenures = [_mining_tenure_record(feature) for feature in features]
    total_matched = body.get("numberMatched") or body.get("totalFeatures") or len(tenures)

    return MiningTenureQueryResult(
        tenures=tenures,
        returned_count=len(tenures),
        total_matched=total_matched,
        limit=limit,
        offset=offset,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?typeName={constants.MINING_TENURE_TYPE_NAME}",
            cached=was_cached,
            schema_name="bcgw.MiningTenureQueryResult",
            coverage=f"{len(tenures)} of {total_matched} total matching tenures returned",
        ),
    )


async def query_layer(
    type_name: str,
    *,
    cql_filter: str | None = None,
    property_names: str | None = None,
    include_geometry: bool = False,
    sort_by: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> LayerQueryResult:
    """Query any BCGW layer by its type_name (e.g.
    "WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW").

    Discover a layer's type_name via ckan_* (portal="bc") -- a WFS/WMS-queryable
    dataset's package carries a resource whose URL embeds it right after
    "openmaps.gov.bc.ca/geo/pub/". `property_names` is a comma-separated
    field list; when omitted (and `include_geometry` is false), no
    property filter is sent and BCGW returns every field including
    geometry, so pass `property_names` explicitly for a lightweight
    attribute-only query on an unfamiliar layer.

    Confirmed live 2026-09-22: this GeoServer instance answers HTTP 400
    ("Cannot do natural order without a primary key") whenever a request
    would genuinely page (more rows match than `limit`) with no `sort_by`
    given -- reproduced against the mining tenure layer, not a one-off.
    `sort_by` therefore defaults to "OBJECTID" here when the caller
    doesn't supply one, since that is BCGW's standard ArcSDE row
    identifier and present on the layers checked; pass a different
    `sort_by` explicitly if a specific layer genuinely lacks it.
    """
    del lang
    _check_limit_offset(limit, offset)
    type_name = type_name.strip()
    if not type_name:
        raise InvalidInput("type_name must not be empty.")
    effective_sort_by = sort_by if sort_by is not None else constants.DEFAULT_SORT_FIELD

    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            type_name,
            cql_filter=cql_filter,
            property_names=property_names,
            srs_name=constants.DEFAULT_SRS if include_geometry else None,
            sort_by=effective_sort_by,
            count=limit,
            start_index=offset,
        )

    cache_key = f"bcgw:layer:{type_name}:{cql_filter}:{property_names}:{include_geometry}:{sort_by}:{limit}:{offset}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_GENERIC_SECONDS, fetch)
    features = body.get("features") or []
    records = [
        {**(feature.get("properties") or {}), "geometry": feature.get("geometry")}
        if include_geometry
        else dict(feature.get("properties") or {})
        for feature in features
    ]
    total_matched = body.get("numberMatched") or body.get("totalFeatures") or len(records)

    return LayerQueryResult(
        type_name=type_name,
        records=records,
        returned_count=len(records),
        total_matched=total_matched,
        limit=limit,
        offset=offset,
        cql_filter=cql_filter,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?typeName={type_name}",
            cached=was_cached,
            schema_name="bcgw.LayerQueryResult",
            coverage=f"{len(records)} of {total_matched} total matching records returned",
        ),
    )
