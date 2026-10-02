"""Client for Alberta Wildfire status. See the package docstring for what
was confirmed live. Reuses `shared/arcgis.py` for the ArcGIS REST query and
its embedded `{"error": ...}` handling.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from maplestats_mcp.modules.ab_wildfire import constants as c
from maplestats_mcp.modules.ab_wildfire.schemas import (
    DangerAtPoint,
    DangerCount,
    DangerSummary,
    Dataset,
    DateBasis,
    Fire,
    FireControlOrder,
    FireControlOrderList,
    FireGroup,
    FireGroupBy,
    FireList,
    FireSort,
    FireSummary,
    Headline,
    Perimeter,
    PerimeterList,
    PerimeterState,
    SameDayComparison,
    SeasonStatistics,
)
from maplestats_mcp.shared import arcgis
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.models import Provenance

_CONFIG = arcgis.ArcGISHubConfig(
    source=c.SOURCE,
    domain=c.DOMAIN,
    rate_limit_per_second=c.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=c.RATE_LIMIT_CAPACITY,
)
_LICENCE = f"Licence: Open Government Licence - Alberta ({c.LICENCE_URL}). {c.ATTRIBUTION}"
_FIRE_FIELDS_CURRENT = (
    "LABEL,FIRE_YEAR,FIRE_TYPE,FIRE_STATUS,FIRE_STATUS_DATE,ASSESSMENT_ASSISTANCE_DATE,"
    "AREA_ESTIMATE,SIZE_CLASS,GENERAL_CAUSE,RESP_AREA,CO_FLAG,FIRE_COMPLEX_NUMBER,"
    "FIRE_COMPLEX_NAME,INCIDENT_TYPE,RESPONSE_TYPE,LATITUDE,LONGITUDE"
)
# The previous-five-years layer has no carry-over flag, complex or incident fields.
_FIRE_FIELDS_HISTORY = (
    "LABEL,FIRE_YEAR,FIRE_TYPE,FIRE_STATUS,FIRE_STATUS_DATE,ASSESSMENT_ASSISTANCE_DATE,"
    "AREA_ESTIMATE,SIZE_CLASS,GENERAL_CAUSE,RESP_AREA,LATITUDE,LONGITUDE"
)
_PERIMETER_FIELDS = (
    "FireNumber,FIRE_TYPE,FIRE_STATUS,FIRE_STATUS_DATE,AREA_ESTIMATE,SIZE_CLASS,GENERAL_CAUSE,"
    "RESP_AREA,CaptreDate,DataSource,SourceKeys,CreatMethd,SumAreaHa,GISFeatureLastUpdated"
)
_ALERT_FIELDS = "name,order_number,alert_type,contact_number,jurisdictions,start_date"
_OHV_FIELDS = "Order_Number,Effective,Expiry,Website_Name,Website_URL"
_ASSISTANCE_VARIANTS = {fixed: broken for broken, fixed in c.STATUS_SPELLING_FIX.items()}


# ------------------------------------------------------------------ helpers


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parse_iso_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


def _utc(value: object) -> datetime | None:
    return arcgis.parse_epoch_millis(value)


def _utc_date(value: object) -> date | None:
    parsed = _utc(value)
    # Order start dates are stored at local midnight (06:00 or 07:00 UTC), so
    # the UTC date is the calendar date Alberta reports.
    return parsed.date() if parsed else None


def _local_datetime(value: object) -> datetime | None:
    """Parse the string status date 'YYYY/MM/DD HH:MM:SS' (no zone stated)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y/%m/%d %H:%M:%S")  # noqa: DTZ007 - no zone stated
    except ValueError:
        return None


def _whole(value: object) -> int | None:
    """Counts arrive as doubles (753.0); return them as integers."""
    return int(value) if isinstance(value, (int, float)) else None


def _fix_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return c.STATUS_SPELLING_FIX.get(value, value)


def _check_page(limit: int, offset: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise InvalidInput(f"limit must be between 1 and {maximum}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")


def _check_point(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidInput(
            f"latitude must be within -90..90 and longitude within -180..180, "
            f"got {latitude}, {longitude}."
        )


def _check_bbox(bbox: list[float]) -> None:
    if len(bbox) != 4:
        raise InvalidInput("bbox must be [min_lon, min_lat, max_lon, max_lat].")
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (min_lon < max_lon and min_lat < max_lat):
        raise InvalidInput(f"bbox must have min < max on both axes, got {bbox}.")
    _check_point(min_lat, min_lon)
    _check_point(max_lat, max_lon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def _radius_bbox(latitude: float, longitude: float, radius_km: float) -> list[float]:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.32 * max(math.cos(math.radians(latitude)), 0.05))
    return [longitude - dlon, latitude - dlat, longitude + dlon, latitude + dlat]


async def _get(context: str, url: str, params: dict[str, Any]) -> Any:
    return await arcgis.get_json(_CONFIG, context, url, params=params)


async def _query(layer_url: str, context: str, **params: Any) -> dict[str, Any]:
    return await _get(context, f"{layer_url}/query", {"where": "1=1", **params})


async def _count(layer_url: str, where: str, **params: Any) -> int:
    body = await _query(layer_url, "count", where=where, returnCountOnly="true", **params)
    return int(body.get("count") or 0)


async def _layer_as_of(layer_url: str) -> datetime | None:
    """The layer's own data-edit time (`editingInfo.dataLastEditDate`)."""

    async def fetch() -> datetime | None:
        try:
            body = await _get("layer_info", layer_url, {})
        except (UpstreamError, UpstreamUnavailable):
            # Only a freshness hint; the data query itself will report real failures.
            return None
        info = body.get("editingInfo") or {}
        return _utc(info.get("dataLastEditDate") or info.get("lastEditDate"))

    value, _ = await cached_fetch(f"ab_wildfire:as_of:{layer_url}", c.CACHE_TTL_LAYER_INFO, fetch)
    return value


def _prov(
    schema: str,
    url: str,
    cached: bool,
    *,
    as_of: datetime | None,
    freshness: str,
    coverage: str | None = None,
    limits: str | None = None,
) -> Provenance:
    return make_provenance(
        source=c.SOURCE,
        url=url,
        cached=cached,
        schema_name=f"ab_wildfire.{schema}",
        as_of=as_of,
        freshness=freshness,
        coverage=coverage,
        limits=f"{limits.rstrip('.')}. {_LICENCE}" if limits else _LICENCE,
    )


_FIRES_FRESHNESS = "updated by Alberta Wildfire through the day in fire season; cached 10 minutes"
_SLOW_FRESHNESS = "refreshed daily or when orders change; cached 30 minutes"


# ------------------------------------------------------------------- fires


@dataclass(frozen=True)
class FireFilters:
    """Filters shared by `list_fires` and `summarize_fires`."""

    status: str | None = None
    active_only: bool = False
    fire_type: str | None = None
    cause: str | None = None
    size_class: str | None = None
    forest_area: str | None = None
    fire_year: int | None = None
    carryover: bool | None = None
    start_date: str | None = None
    end_date: str | None = None
    date_basis: DateBasis = "assessed"
    min_area_ha: float | None = None
    bbox: list[float] | None = None


def build_fire_where(
    filters: FireFilters, *, dataset: Dataset = "current", extra_bbox: list[float] | None = None
) -> str:
    """Build the SQL-92 `where` clause. Text filters are case-insensitive;
    `end_date` is inclusive, as a person reads a date range."""
    clauses: list[str] = []
    if filters.status:
        requested = filters.status.strip()
        variants = {requested}
        # The previous-five-years layer misspells "Assistance Ended".
        misspelt = _ASSISTANCE_VARIANTS.get(requested.title())
        if misspelt:
            variants.add(misspelt)
        values = ", ".join(_quote(v.upper()) for v in sorted(variants))
        clauses.append(f"UPPER(FIRE_STATUS) IN ({values})")
    if filters.active_only:
        inactive = ", ".join(_quote(s) for s in c.INACTIVE_STATUSES)
        clauses.append(f"(FIRE_STATUS IS NULL OR FIRE_STATUS NOT IN ({inactive}))")
    if filters.fire_type:
        match = [t for t in c.FIRE_TYPES if t.lower() == filters.fire_type.strip().lower()]
        if not match:
            raise InvalidInput(f"fire_type must be one of {list(c.FIRE_TYPES)}.")
        clauses.append(f"FIRE_TYPE = {_quote(match[0])}")
    if filters.cause:
        clauses.append(f"UPPER(GENERAL_CAUSE) = {_quote(filters.cause.strip().upper())}")
    if filters.size_class:
        letters = [p.strip().upper() for p in filters.size_class.split(",") if p.strip()]
        if not letters or any(letter not in c.SIZE_CLASSES for letter in letters):
            raise InvalidInput(
                f"size_class must be letters from {list(c.SIZE_CLASSES)}, comma separated "
                f"(e.g. 'D,E'); got {filters.size_class!r}."
            )
        clauses.append("SIZE_CLASS IN (" + ", ".join(_quote(x) for x in letters) + ")")
    if filters.forest_area and filters.forest_area.strip():
        pattern = filters.forest_area.strip().upper().replace("'", "''")
        clauses.append(f"UPPER(RESP_AREA) LIKE '%{pattern}%'")
    if filters.fire_year is not None:
        clauses.append(f"FIRE_YEAR = {int(filters.fire_year)}")
    if filters.carryover is not None:
        if dataset != "current":
            raise InvalidInput("carryover is only recorded in the 'current' dataset.")
        clauses.append(f"CO_FLAG = '{'Y' if filters.carryover else 'N'}'")
    if filters.min_area_ha is not None:
        clauses.append(f"AREA_ESTIMATE >= {float(filters.min_area_ha)}")
    start = _parse_iso_date(filters.start_date, "start_date") if filters.start_date else None
    end = _parse_iso_date(filters.end_date, "end_date") if filters.end_date else None
    if start and end and start > end:
        raise InvalidInput(f"start_date {start} is after end_date {end}.")
    if filters.date_basis == "assessed":
        if start:
            clauses.append(f"ASSESSMENT_ASSISTANCE_DATE >= DATE '{start.isoformat()}'")
        if end:
            after = (end + timedelta(days=1)).isoformat()
            clauses.append(f"ASSESSMENT_ASSISTANCE_DATE < DATE '{after}'")
    else:
        # FIRE_STATUS_DATE is text 'YYYY/MM/DD HH:MM:SS', so it compares as a string.
        if start:
            clauses.append(f"FIRE_STATUS_DATE >= '{start.strftime('%Y/%m/%d')}'")
        if end:
            after = (end + timedelta(days=1)).strftime("%Y/%m/%d")
            clauses.append(f"FIRE_STATUS_DATE < '{after}'")
    for box in (filters.bbox, extra_bbox):
        if box:
            _check_bbox(box)
            clauses.append(
                f"LONGITUDE >= {box[0]} AND LATITUDE >= {box[1]} "
                f"AND LONGITUDE <= {box[2]} AND LATITUDE <= {box[3]}"
            )
    return " AND ".join(clauses) or "1=1"


def _dataset_layer(dataset: Dataset) -> str:
    if dataset == "current":
        return c.FIRES_CURRENT
    if dataset == "previous_5_years":
        return c.FIRES_HISTORY
    raise InvalidInput(f"dataset must be 'current' or 'previous_5_years', got {dataset!r}.")


def _to_fire(attrs: dict[str, Any], distance: float | None = None) -> Fire:
    carryover = attrs.get("CO_FLAG")
    return Fire(
        fire_number=attrs.get("LABEL"),
        fire_year=attrs.get("FIRE_YEAR"),
        fire_type=attrs.get("FIRE_TYPE"),
        status=_fix_status(attrs.get("FIRE_STATUS")),
        status_changed=_local_datetime(attrs.get("FIRE_STATUS_DATE")),
        assessed_at=_utc(attrs.get("ASSESSMENT_ASSISTANCE_DATE")),
        area_ha=attrs.get("AREA_ESTIMATE"),
        size_class=attrs.get("SIZE_CLASS"),
        cause=attrs.get("GENERAL_CAUSE"),
        forest_area=attrs.get("RESP_AREA"),
        carryover=None if carryover is None else carryover == "Y",
        complex_number=attrs.get("FIRE_COMPLEX_NUMBER"),
        complex_name=attrs.get("FIRE_COMPLEX_NAME"),
        incident_type=attrs.get("INCIDENT_TYPE"),
        response_type=attrs.get("RESPONSE_TYPE"),
        latitude=attrs.get("LATITUDE"),
        longitude=attrs.get("LONGITUDE"),
        distance_km=None if distance is None else round(distance, 1),
    )


def _dataset_coverage(dataset: Dataset) -> str:
    if dataset == "current":
        return (
            "fires of the current year plus carry-over fires, including mutual-aid fires; "
            "the active set is empty off-season"
        )
    return (
        "fires of the last six fire years, each cut at today's calendar date "
        "(a same-date comparison set, not a full history)"
    )


async def list_fires(
    dataset: Dataset = "current",
    filters: FireFilters | None = None,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    sort_by: FireSort = "latest",
    limit: int = c.LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FireList:
    """List fire points, newest status change first or largest first; with a
    point and radius, the fires within it, nearest first."""
    del lang
    filters = filters or FireFilters()
    _check_page(limit, offset, c.LIMIT_MAX)
    if sort_by not in ("latest", "largest"):
        raise InvalidInput("sort_by must be 'latest' or 'largest'.")
    circle: tuple[float, float, float] | None = None
    if latitude is not None or longitude is not None or radius_km is not None:
        if latitude is None or longitude is None or radius_km is None:
            raise InvalidInput("latitude, longitude and radius_km must be given together.")
        _check_point(latitude, longitude)
        if not 0 < radius_km <= c.MAX_RADIUS_KM:
            raise InvalidInput(f"radius_km must be above 0 and at most {c.MAX_RADIUS_KM:g}.")
        circle = (latitude, longitude, radius_km)
    layer = _dataset_layer(dataset)
    extra = _radius_bbox(*circle) if circle else None
    where = build_fire_where(filters, dataset=dataset, extra_bbox=extra)
    order = (
        "FIRE_STATUS_DATE DESC, OBJECTID DESC"
        if sort_by == "latest"
        else "AREA_ESTIMATE DESC, OBJECTID DESC"
    )
    fields = _FIRE_FIELDS_CURRENT if dataset == "current" else _FIRE_FIELDS_HISTORY
    # With a radius the bounding box over-selects, so take every row in it
    # (one page) and cut to the circle here.
    fetch_limit, fetch_offset = (c.LIMIT_MAX, 0) if circle else (limit, offset)

    async def fetch() -> tuple[int, list[dict[str, Any]], bool]:
        total = await _count(layer, where)
        body = await _query(
            layer,
            "list_fires",
            where=where,
            outFields=fields,
            orderByFields=order,
            returnGeometry="false",
            resultRecordCount=fetch_limit,
            resultOffset=fetch_offset,
        )
        return total, body.get("features") or [], bool(body.get("exceededTransferLimit"))

    key = f"ab_wildfire:fires:{dataset}:{where}:{order}:{fetch_limit}:{fetch_offset}"
    (total, features, truncated), was_cached = await cached_fetch(key, c.CACHE_TTL_FIRES, fetch)
    rows = [f.get("attributes") or {} for f in features]
    if circle:
        centre_lat, centre_lon, radius = circle
        if truncated or total > c.LIMIT_MAX:
            raise InvalidInput(
                f"{total} fires fall inside the search box; narrow the radius or add filters "
                f"(at most {c.LIMIT_MAX} can be searched around a point)."
            )
        scored = [
            (haversine_km(centre_lat, centre_lon, a["LATITUDE"], a["LONGITUDE"]), a)
            for a in rows
            if a.get("LATITUDE") is not None and a.get("LONGITUDE") is not None
        ]
        scored = sorted((s for s in scored if s[0] <= radius), key=lambda s: s[0])
        total = len(scored)
        fires = [_to_fire(a, d) for d, a in scored[offset : offset + limit]]
    else:
        fires = [_to_fire(a) for a in rows]
    layer_url = f"{layer}/query"
    return FireList(
        dataset=dataset,
        where=where,
        total_matches=total,
        returned_count=len(fires),
        offset=offset,
        fires=fires,
        provenance=_prov(
            "FireList",
            layer_url,
            was_cached,
            as_of=await _layer_as_of(layer),
            freshness=_FIRES_FRESHNESS,
            coverage=_dataset_coverage(dataset),
            limits=(
                f"{len(fires)} of {total} matching fires returned; "
                "area is the agency's estimate in hectares"
            ),
        ),
    )


async def summarize_fires(
    dataset: Dataset = "current",
    group_by: FireGroupBy = "status",
    filters: FireFilters | None = None,
    *,
    lang: str = "en",
) -> FireSummary:
    """Count fires and sum their estimated area by status, cause, size class,
    forest area, fire type or fire year, computed server-side over every
    matching row."""
    del lang
    filters = filters or FireFilters()
    if group_by not in c.FIRE_GROUP_FIELDS:
        raise InvalidInput(
            f"group_by must be one of {sorted(c.FIRE_GROUP_FIELDS)}, got {group_by!r}."
        )
    layer = _dataset_layer(dataset)
    where = build_fire_where(filters, dataset=dataset)
    field = c.FIRE_GROUP_FIELDS[group_by]
    statistics = [
        {"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"},
        {
            "statisticType": "sum",
            "onStatisticField": "AREA_ESTIMATE",
            "outStatisticFieldName": "ha",
        },
        {
            "statisticType": "max",
            "onStatisticField": "AREA_ESTIMATE",
            "outStatisticFieldName": "mx",
        },
    ]

    async def fetch() -> list[dict[str, Any]]:
        body = await _query(
            layer,
            "summarize_fires",
            where=where,
            groupByFieldsForStatistics=field,
            outStatistics=json.dumps(statistics),
        )
        return body.get("features") or []

    key = f"ab_wildfire:summary:{dataset}:{group_by}:{where}"
    features, was_cached = await cached_fetch(key, c.CACHE_TTL_FIRES, fetch)
    merged: dict[str | int | None, dict[str, float]] = {}
    for feature in features:
        attrs = feature.get("attributes") or {}
        value = attrs.get(field)
        if group_by == "status":
            # Fold the previous-five-years layer's "Assisstance Ended" typo in.
            value = _fix_status(value)
        slot = merged.setdefault(value, {"n": 0.0, "ha": 0.0, "mx": 0.0, "has_area": 0.0})
        slot["n"] += int(attrs.get("n") or 0)
        if attrs.get("ha") is not None:
            slot["ha"] += float(attrs["ha"])
            slot["has_area"] = 1.0
        slot["mx"] = max(slot["mx"], float(attrs.get("mx") or 0.0))
    groups = [
        FireGroup(
            key=key_value,
            fires=int(slot["n"]),
            total_area_ha=round(slot["ha"], 2) if slot["has_area"] else None,
            largest_fire_ha=slot["mx"] if slot["has_area"] else None,
        )
        for key_value, slot in merged.items()
    ]
    if group_by == "fire_year":
        groups.sort(key=lambda g: (g.key is None, g.key))
    else:
        groups.sort(key=lambda g: g.fires, reverse=True)
    return FireSummary(
        dataset=dataset,
        group_by=group_by,
        where=where,
        total_fires=sum(g.fires for g in groups),
        total_area_ha=round(sum(g.total_area_ha or 0.0 for g in groups), 2),
        groups=groups,
        provenance=_prov(
            "FireSummary",
            f"{layer}/query",
            was_cached,
            as_of=await _layer_as_of(layer),
            freshness=_FIRES_FRESHNESS,
            coverage=_dataset_coverage(dataset),
            limits=(
                "counts and areas cover every matching row, mutual-aid fires and "
                "carry-over fires included unless filtered; the dashboard headline "
                "counts current-year wildfires only"
            ),
        ),
    )


# -------------------------------------------------------------- statistics


async def get_season_statistics(*, lang: str = "en") -> SeasonStatistics:
    """The dashboard's five headline numbers plus season totals at today's
    date for the last six years against 5, 10 and 25-year averages."""
    del lang

    async def fetch() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        headline = await _query(c.STATISTICS, "statistics", outFields="*", orderByFields="OBJECTID")
        history = await _query(
            c.THIS_DAY, "this_day", outFields="*", orderByFields="FireStatusYear"
        )
        return headline.get("features") or [], history.get("features") or []

    (head_rows, day_rows), was_cached = await cached_fetch(
        "ab_wildfire:season", c.CACHE_TTL_SLOW, fetch
    )
    values = {
        (r.get("attributes") or {}).get("statistic_name"): (r.get("attributes") or {}).get(
            "statistic_value"
        )
        for r in head_rows
    }
    if not values:
        raise UpstreamError("ab_wildfire: the statistics view returned no rows.")
    headline = Headline(
        active_wildfires=_whole(values.get("Wildfire_Active_Count")),
        active_area_ha=values.get("Wildfire_Active_Area"),
        year_to_date_wildfires=_whole(values.get("YTD_Wildfire_Total_Count")),
        year_to_date_area_ha=values.get("YTD_Wildfire_Total_Area"),
        new_wildfires_24h=_whole(values.get("New_Wildfire_24h")),
    )
    comparison = []
    for row in day_rows:
        a = row.get("attributes") or {}
        day = None
        if isinstance(a.get("FireStatusDate"), str):
            try:
                day = date.fromisoformat(a["FireStatusDate"])
            except ValueError:
                day = None
        if not isinstance(a.get("FireStatusYear"), int):
            continue
        comparison.append(
            SameDayComparison(
                year=a["FireStatusYear"],
                day=day,
                wildfires_that_day=a.get("TotalNumberOfWildfiresPerDay"),
                wildfires_to_date=a.get("TotalNumberOfWildfiresToDate"),
                area_burned_to_date_ha=a.get("TotalHaBurned"),
                area_burned_that_day_ha=a.get("TotalDailyHaBurned"),
                five_year_avg_wildfires=a.get("FiveYearAvgCnt"),
                ten_year_avg_wildfires=a.get("TenYearAvgCnt"),
                twentyfive_year_avg_wildfires=a.get("TwentyfiveYearAvgCnt"),
                five_year_avg_area_ha=a.get("FiveYearAvgHa"),
                ten_year_avg_area_ha=a.get("TenYearAvgHa"),
                twentyfive_year_avg_area_ha=a.get("TwentyfiveYearAvgHa"),
            )
        )
    dates = [r.day for r in comparison if r.day]
    return SeasonStatistics(
        headline=headline,
        same_day_comparison=comparison,
        comparison_date=max(dates) if dates else None,
        provenance=_prov(
            "SeasonStatistics",
            f"{c.STATISTICS}/query",
            was_cached,
            as_of=await _layer_as_of(c.STATISTICS),
            freshness="daily; cached 30 minutes",
            coverage=(
                "headline figures count current-year wildfires only (not mutual-aid or "
                "carry-over fires); the comparison table holds the same calendar date in "
                "each of the last six years"
            ),
            limits=(
                "the 25-year averages and the current year's own averages are null; daily "
                "area can be slightly negative when estimates are revised; the active "
                "count can be above zero while the active-fire layer is empty"
            ),
        ),
    )


# -------------------------------------------------------------- perimeters


def build_perimeter_where(
    *,
    fire_number: str | None,
    cause: str | None,
    size_class: str | None,
    forest_area: str | None,
    min_area_ha: float | None,
) -> str:
    clauses: list[str] = []
    if fire_number and fire_number.strip():
        pattern = fire_number.strip().upper().replace("'", "''")
        clauses.append(f"UPPER(FireNumber) LIKE '%{pattern}%'")
    if cause:
        clauses.append(f"UPPER(GENERAL_CAUSE) = {_quote(cause.strip().upper())}")
    if size_class:
        letters = [p.strip().upper() for p in size_class.split(",") if p.strip()]
        if not letters or any(letter not in c.SIZE_CLASSES for letter in letters):
            raise InvalidInput(f"size_class must be letters from {list(c.SIZE_CLASSES)}.")
        clauses.append("SIZE_CLASS IN (" + ", ".join(_quote(x) for x in letters) + ")")
    if forest_area and forest_area.strip():
        pattern = forest_area.strip().upper().replace("'", "''")
        clauses.append(f"UPPER(RESP_AREA) LIKE '%{pattern}%'")
    if min_area_ha is not None:
        clauses.append(f"AREA_ESTIMATE >= {float(min_area_ha)}")
    return " AND ".join(clauses) or "1=1"


def _to_perimeter(feature: dict[str, Any], include_geometry: bool) -> Perimeter:
    # f=geojson puts the attributes under "properties".
    p = feature.get("properties") or {}
    return Perimeter(
        fire_number=p.get("FireNumber"),
        fire_type=p.get("FIRE_TYPE"),
        status=_fix_status(p.get("FIRE_STATUS")),
        status_changed=_local_datetime(p.get("FIRE_STATUS_DATE")),
        area_ha=p.get("AREA_ESTIMATE"),
        mapped_area_ha=p.get("SumAreaHa"),
        size_class=p.get("SIZE_CLASS"),
        cause=p.get("GENERAL_CAUSE"),
        forest_area=p.get("RESP_AREA"),
        captured_at=_utc(p.get("CaptreDate")),
        data_source=p.get("DataSource"),
        source_keys=p.get("SourceKeys"),
        creation_method=p.get("CreatMethd"),
        last_updated=_utc(p.get("GISFeatureLastUpdated")),
        geometry=feature.get("geometry") if include_geometry else None,
    )


async def get_perimeters(
    state: PerimeterState = "active",
    *,
    fire_number: str | None = None,
    cause: str | None = None,
    size_class: str | None = None,
    forest_area: str | None = None,
    min_area_ha: float | None = None,
    include_geometry: bool = False,
    limit: int = c.LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> PerimeterList:
    """List mapped fire perimeters of active or extinguished fires, largest first."""
    del lang
    if state not in c.PERIMETERS:
        raise InvalidInput(f"state must be 'active' or 'extinguished', got {state!r}.")
    _check_page(limit, offset, c.LIMIT_GEOMETRY_MAX if include_geometry else c.LIMIT_MAX)
    layer = c.PERIMETERS[state]
    where = build_perimeter_where(
        fire_number=fire_number,
        cause=cause,
        size_class=size_class,
        forest_area=forest_area,
        min_area_ha=min_area_ha,
    )

    async def fetch() -> tuple[int, list[dict[str, Any]]]:
        total = await _count(layer, where)
        params: dict[str, Any] = {
            "where": where,
            "outFields": _PERIMETER_FIELDS,
            "orderByFields": "AREA_ESTIMATE DESC, OBJECTID DESC",
            "resultRecordCount": limit,
            "resultOffset": offset,
            "f": "geojson",
            "returnGeometry": str(include_geometry).lower(),
        }
        if include_geometry:
            # About 50 m of simplification and 5 decimals (about 1 m): perimeters
            # carry thousands of vertices otherwise.
            params.update(outSR=4326, maxAllowableOffset=0.0005, geometryPrecision=5)
        body = await _query(layer, "perimeters", **params)
        return total, body.get("features") or []

    key = f"ab_wildfire:perimeters:{state}:{where}:{include_geometry}:{limit}:{offset}"
    (total, features), was_cached = await cached_fetch(key, c.CACHE_TTL_FIRES, fetch)
    perimeters = [_to_perimeter(f, include_geometry) for f in features]
    note = None
    if total == 0 and where == "1=1":
        note = "No perimeters are published right now" + (
            " (normal outside the fire season)." if state == "active" else "."
        )
    return PerimeterList(
        state=state,
        where=where,
        total_matches=total,
        returned_count=len(perimeters),
        offset=offset,
        perimeters=perimeters,
        note=note,
        provenance=_prov(
            "PerimeterList",
            f"{layer}/query",
            was_cached,
            as_of=await _layer_as_of(layer)
            or max((p.last_updated for p in perimeters if p.last_updated), default=None),
            freshness=_FIRES_FRESHNESS,
            coverage=(
                "only some fires have a mapped perimeter (none for 'Turned Over' fires); "
                "current-season fires"
            ),
            limits=(
                f"{len(perimeters)} of {total} matching perimeters returned"
                + ("; geometry simplified to about 50 m" if include_geometry else "")
            ),
        ),
    )


# ------------------------------------------------------------ fire danger


def _severity(danger_class: str | None) -> int:
    return c.DANGER_CLASSES.index(danger_class) if danger_class in c.DANGER_CLASSES else -1


async def get_fire_danger(latitude: float, longitude: float, *, lang: str = "en") -> DangerAtPoint:
    """The fire danger class of the rating polygon containing a point."""
    del lang
    _check_point(latitude, longitude)

    async def fetch() -> list[dict[str, Any]]:
        body = await _query(
            c.DANGER,
            "danger_point",
            geometry=f"{longitude},{latitude}",
            geometryType="esriGeometryPoint",
            inSR=4326,
            spatialRel="esriSpatialRelIntersects",
            outFields="Fire_Danger,Last_Updated",
            returnGeometry="false",
        )
        return body.get("features") or []

    key = f"ab_wildfire:danger_point:{round(latitude, 4)}:{round(longitude, 4)}"
    features, was_cached = await cached_fetch(key, c.CACHE_TTL_SLOW, fetch)
    rows = [f.get("attributes") or {} for f in features]
    # A point on a shared edge can touch two polygons; report the more severe.
    best = max(rows, key=lambda a: _severity(a.get("Fire_Danger")), default=None)
    danger_class = best.get("Fire_Danger") if best else None
    return DangerAtPoint(
        latitude=latitude,
        longitude=longitude,
        danger_class=danger_class,
        meaning=c.DANGER_MEANING.get(danger_class) if danger_class else None,
        rating_timestamp=_utc(best.get("Last_Updated")) if best else None,
        note=(
            None if best else "The point is outside the rating polygons, which cover Alberta only."
        ),
        provenance=_prov(
            "DangerAtPoint",
            f"{c.DANGER}/query",
            was_cached,
            as_of=await _layer_as_of(c.DANGER),
            freshness="the rating is refreshed daily from the Fire Weather Index system",
            coverage="Alberta only; the polygons also cover the white area outside the forest zone",
            limits=(
                "general public information; regulated forest operations must use weather data "
                "representative of the site"
            ),
        ),
    )


async def summarize_fire_danger(
    bbox: list[float] | None = None, *, lang: str = "en"
) -> DangerSummary:
    """Count the rating polygons of each danger class, province-wide or in a box."""
    del lang
    params: dict[str, Any] = {}
    if bbox:
        _check_bbox(bbox)
        params = {
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
    statistics = [
        {"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"},
        {
            "statisticType": "max",
            "onStatisticField": "Last_Updated",
            "outStatisticFieldName": "updated",
        },
    ]

    async def fetch() -> list[dict[str, Any]]:
        body = await _query(
            c.DANGER,
            "danger_summary",
            groupByFieldsForStatistics="Fire_Danger",
            outStatistics=json.dumps(statistics),
            **params,
        )
        return body.get("features") or []

    key = f"ab_wildfire:danger_summary:{bbox}"
    features, was_cached = await cached_fetch(key, c.CACHE_TTL_SLOW, fetch)
    counts = [
        DangerCount(danger_class=a["Fire_Danger"], polygons=int(a.get("n") or 0))
        for a in (f.get("attributes") or {} for f in features)
        if a.get("Fire_Danger")
    ]
    counts.sort(key=lambda d: _severity(d.danger_class), reverse=True)
    updated = max(
        (
            u
            for u in (_utc((f.get("attributes") or {}).get("updated")) for f in features)
            if u is not None
        ),
        default=None,
    )
    return DangerSummary(
        bbox=bbox,
        most_severe_class=counts[0].danger_class if counts else None,
        classes=counts,
        total_polygons=sum(d.polygons for d in counts),
        rating_timestamp=updated,
        note=(
            "Counts are rating polygons, not area: the polygons differ in size, so a class's "
            "share of polygons is not its share of the land."
        ),
        provenance=_prov(
            "DangerSummary",
            f"{c.DANGER}/query",
            was_cached,
            as_of=await _layer_as_of(c.DANGER),
            freshness="the rating is refreshed daily from the Fire Weather Index system",
            coverage="Alberta only (807 polygons province-wide)",
            limits="a box counts every polygon it touches, including partly",
        ),
    )


# ----------------------------------------------------- fire control orders


async def _fetch_orders(
    alert_type: str,
    layer: str,
    where: str,
    point: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "where": where,
        "outFields": _OHV_FIELDS if alert_type == c.OHV_LABEL else _ALERT_FIELDS,
        "returnGeometry": "false",
        "resultRecordCount": c.LIMIT_MAX,
    }
    if point:
        params.update(
            geometry=f"{point[1]},{point[0]}",
            geometryType="esriGeometryPoint",
            inSR=4326,
            spatialRel="esriSpatialRelIntersects",
        )
    body = await _query(layer, f"orders:{alert_type}", **params)
    return [
        {"_type": alert_type, **(f.get("attributes") or {})} for f in body.get("features") or []
    ]


async def get_fire_control_orders(
    latitude: float | None = None,
    longitude: float | None = None,
    *,
    alert_type: str | None = None,
    name_contains: str | None = None,
    limit: int = 100,
    lang: str = "en",
) -> FireControlOrderList:
    """List fire bans, restrictions, advisories and forest closures (and OHV
    restrictions), province-wide or those covering a point."""
    del lang
    if (latitude is None) != (longitude is None):
        raise InvalidInput("latitude and longitude must be given together.")
    point = None
    if latitude is not None and longitude is not None:
        _check_point(latitude, longitude)
        point = (latitude, longitude)
    if not 1 <= limit <= c.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {c.LIMIT_MAX}, got {limit}.")
    layers = {**c.FIRE_CONTROL_ORDERS, c.OHV_LABEL: c.OHV_RESTRICTION}
    if alert_type:
        match = [k for k in layers if k.lower() == alert_type.strip().lower()]
        if not match:
            raise InvalidInput(f"alert_type must be one of {list(layers)}, got {alert_type!r}.")
        layers = {match[0]: layers[match[0]]}
    pattern = (name_contains or "").strip().upper().replace("'", "''")

    def where_for(kind: str) -> str:
        if not pattern:
            return "1=1"
        if kind == c.OHV_LABEL:
            return f"UPPER(Website_Name) LIKE '%{pattern}%'"
        return f"(UPPER(name) LIKE '%{pattern}%' OR UPPER(jurisdictions) LIKE '%{pattern}%')"

    async def fetch() -> list[dict[str, Any]]:
        results = await asyncio.gather(
            *(_fetch_orders(kind, url, where_for(kind), point) for kind, url in layers.items())
        )
        return [row for rows in results for row in rows]

    key = f"ab_wildfire:orders:{sorted(layers)}:{pattern}:{point}"
    rows, was_cached = await cached_fetch(key, c.CACHE_TTL_SLOW, fetch)
    grouped: dict[tuple[Any, ...], FireControlOrder] = {}
    for row in rows:
        kind = row["_type"]
        if kind == c.OHV_LABEL:
            order = FireControlOrder(
                alert_type=kind,
                name=row.get("Website_Name"),
                jurisdictions=None,
                start_date=_utc_date(row.get("Effective")),
                expiry_date=_utc_date(row.get("Expiry")),
                order_number=row.get("Order_Number"),
                website=row.get("Website_URL"),
                polygons=1,
            )
        else:
            order = FireControlOrder(
                alert_type=row.get("alert_type") or kind,
                name=row.get("name"),
                jurisdictions=(row.get("jurisdictions") or "").strip() or None,
                start_date=_utc_date(row.get("start_date")),
                contact_number=row.get("contact_number"),
                order_number=row.get("order_number"),
                polygons=1,
            )
        identity = (
            order.alert_type,
            order.name,
            order.jurisdictions,
            order.start_date,
            order.order_number,
            order.contact_number,
        )
        if identity in grouped:
            grouped[identity].polygons += 1
        else:
            grouped[identity] = order
    orders = sorted(
        grouped.values(),
        key=lambda o: (c.ALERT_SEVERITY.get(o.alert_type, 9), (o.name or "").lower()),
    )
    counts: dict[str, int] = {}
    for order in orders:
        counts[order.alert_type] = counts.get(order.alert_type, 0) + 1
    stale = [
        o
        for o in orders
        if o.start_date and o.start_date < datetime.now(UTC).date() - timedelta(days=365)
    ]
    note = None
    if stale:
        note = (
            f"{len(stale)} entries started more than a year ago. The layer has no end date, so "
            "an old entry may be stale; confirm with the issuing municipality or park."
        )
    shown = orders[:limit]
    where_text = "point " + f"{latitude},{longitude}" if point else "province-wide"
    if pattern:
        where_text += f"; name contains {pattern}"
    return FireControlOrderList(
        where=where_text,
        returned_count=len(shown),
        counts_by_type=counts,
        orders=shown,
        note=note,
        provenance=_prov(
            "FireControlOrderList",
            f"{c.SERVICES_ROOT}/alberta_fire_ban_system/FeatureServer",
            was_cached,
            as_of=await _layer_as_of(next(iter(layers.values()))),
            freshness=_SLOW_FRESHNESS,
            coverage=(
                "orders mapped in the Alberta Fire Ban System; the issuing municipality "
                "is the authority for what is allowed"
            ),
            limits=(
                f"{len(shown)} of {len(orders)} distinct entries returned; one entry can be "
                "several map polygons (see `polygons`)"
            ),
        ),
    )
