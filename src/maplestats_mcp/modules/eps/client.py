"""Client for EPS Community Safety Data Portal occurrences. See the
module docstring for the coverage and label quirks confirmed live.
Reuses `shared/arcgis.py` for the ArcGIS REST query and its embedded
`{"error": ...}` handling rather than re-implementing either.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from maplestats_mcp.modules.eps import constants
from maplestats_mcp.modules.eps.schemas import (
    Dataset,
    GroupBy,
    LoadDate,
    Occurrence,
    OccurrenceCount,
    OccurrenceList,
    OccurrenceSummary,
)
from maplestats_mcp.shared import arcgis
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput

_CONFIG = arcgis.ArcGISHubConfig(
    source=constants.SOURCE,
    domain="services9.arcgis.com",
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)
_COUNT_FIELD = "occurrence_count"
_FRESHNESS = "refreshed daily by EPS with a 24-48 hour publication delay"


def _layer_url(dataset: str) -> str:
    if dataset not in constants.DATASETS:
        raise InvalidInput(f"dataset must be one of {sorted(constants.DATASETS)}, got {dataset!r}.")
    return constants.DATASETS[dataset]


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parse_iso_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


def build_where(
    *,
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
) -> str:
    """Build a SQL-92 `where` clause. Label filters match exactly because
    upstream labels include near-duplicates (see module docstring);
    `end_date` is inclusive, matching how a person reads a date range."""
    clauses: list[str] = []
    for field, value in (
        ("Occurrence_Category", category),
        ("Occurrence_Group", group),
        ("Occurrence_Type_Group", type_group),
    ):
        if value:
            clauses.append(f"{field} = {_quote(value)}")
    start = _parse_iso_date(start_date, "start_date") if start_date else None
    end = _parse_iso_date(end_date, "end_date") if end_date else None
    if start and end and start > end:
        raise InvalidInput(f"start_date {start} is after end_date {end}.")
    if start:
        clauses.append(f"Reported_Date >= DATE '{start.isoformat()}'")
    if end:
        clauses.append(f"Reported_Date < DATE '{(end + timedelta(days=1)).isoformat()}'")
    if intersection_contains and intersection_contains.strip():
        pattern = intersection_contains.strip().upper().replace("'", "''")
        clauses.append(f"UPPER(Intersection) LIKE '%{pattern}%'")
    return " AND ".join(clauses) or "1=1"


def _epoch_to_date(value: object) -> date | None:
    parsed = arcgis.parse_epoch_millis(value)
    # Stored as 12:00 UTC (local midnight in Edmonton), so the UTC date
    # is the calendar date EPS reports.
    return parsed.date() if parsed else None


def _to_occurrence(feature: dict[str, Any]) -> Occurrence:
    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    return Occurrence(
        reported_date=_epoch_to_date(attrs.get("Reported_Date")),
        category=attrs.get("Occurrence_Category"),
        group=attrs.get("Occurrence_Group"),
        type_group=attrs.get("Occurrence_Type_Group"),
        intersection=attrs.get("Intersection"),
        longitude=geometry.get("x"),
        latitude=geometry.get("y"),
    )


async def _count(layer_url: str, where: str) -> int:
    body = await arcgis.get_json(
        _CONFIG,
        "count",
        f"{layer_url}/query",
        params={"where": where, "returnCountOnly": "true"},
    )
    return int(body.get("count") or 0)


async def list_occurrences(
    dataset: Dataset = "current",
    *,
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> OccurrenceList:
    """List individual occurrences, newest first, with WGS84 coordinates."""
    del lang
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    layer_url = _layer_url(dataset)
    where = build_where(
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
    )

    async def fetch() -> tuple[int, list[dict[str, Any]]]:
        total = await _count(layer_url, where)
        body = await arcgis.query_layer(
            _CONFIG,
            layer_url,
            0,
            where=where,
            out_fields=(
                "Reported_Date,Occurrence_Category,Occurrence_Group,"
                "Occurrence_Type_Group,Intersection"
            ),
            order_by="Reported_Date DESC, OBJECTID DESC",
            return_geometry=True,
            limit=limit,
            offset=offset,
            out_sr=4326,
        )
        return total, body.get("features") or []

    cache_key = f"eps:list:{dataset}:{where}:{limit}:{offset}"
    (total, features), was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_QUERY_SECONDS, fetch
    )
    return OccurrenceList(
        dataset=dataset,
        where=where,
        total_matches=total,
        offset=offset,
        occurrences=[_to_occurrence(feature) for feature in features],
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{layer_url}/query",
            cached=was_cached,
            schema_name="eps.OccurrenceList",
            freshness=_FRESHNESS,
            coverage=constants.DATASET_COVERAGE[dataset],
            limits="location is the nearest intersection only; no time of day",
        ),
    )


async def summarize_occurrences(
    dataset: Dataset = "current",
    group_by: GroupBy = "category",
    *,
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
    top: int = 100,
    lang: str = "en",
) -> OccurrenceSummary:
    """Count occurrences grouped by category, group, type, month, or
    intersection, computed server-side with ArcGIS outStatistics."""
    del lang
    if group_by not in constants.GROUP_BY_FIELDS:
        raise InvalidInput(
            f"group_by must be one of {sorted(constants.GROUP_BY_FIELDS)}, got {group_by!r}."
        )
    if not 1 <= top <= constants.LIMIT_MAX:
        raise InvalidInput(f"top must be between 1 and {constants.LIMIT_MAX}, got {top}.")
    layer_url = _layer_url(dataset)
    where = build_where(
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
    )
    fields = constants.GROUP_BY_FIELDS[group_by]
    # Months read chronologically; everything else reads largest first.
    order_by = "Reported_Year, Reported_Month" if group_by == "month" else f"{_COUNT_FIELD} DESC"
    statistics = [
        {
            "statisticType": "count",
            "onStatisticField": "OBJECTID",
            "outStatisticFieldName": _COUNT_FIELD,
        }
    ]

    async def fetch() -> tuple[int, list[dict[str, Any]]]:
        total = await _count(layer_url, where)
        body = await arcgis.get_json(
            _CONFIG,
            "summarize",
            f"{layer_url}/query",
            params={
                "where": where,
                "groupByFieldsForStatistics": ",".join(fields),
                "outStatistics": json.dumps(statistics),
                "orderByFields": order_by,
                "resultRecordCount": top,
            },
        )
        return total, body.get("features") or []

    cache_key = f"eps:summary:{dataset}:{group_by}:{where}:{top}"
    (total, features), was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_QUERY_SECONDS, fetch
    )
    groups = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        groups.append(
            OccurrenceCount(
                keys={field: attrs.get(field) for field in fields},
                count=int(attrs.get(_COUNT_FIELD) or 0),
            )
        )
    return OccurrenceSummary(
        dataset=dataset,
        group_by=group_by,
        where=where,
        total_matches=total,
        groups=groups,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{layer_url}/query",
            cached=was_cached,
            schema_name="eps.OccurrenceSummary",
            freshness=_FRESHNESS,
            coverage=constants.DATASET_COVERAGE[dataset],
            limits=f"at most {top} groups returned",
        ),
    )


async def get_last_load_date(*, lang: str = "en") -> LoadDate:
    """Return EPS's own record of when the occurrence data was last loaded."""
    del lang

    async def fetch() -> dict[str, Any]:
        return await arcgis.query_layer(_CONFIG, constants.LOAD_DATE_URL, 0, limit=1)

    body, was_cached = await cached_fetch(
        "eps:load-date", constants.CACHE_TTL_LOAD_DATE_SECONDS, fetch
    )
    features = body.get("features") or []
    raw = (features[0].get("attributes") or {}).get("Last_Load_Date") if features else None
    parsed: date | None = None
    if isinstance(raw, str):
        # Confirmed live as DD/MM/YYYY (e.g. "20/09/2026"), not ISO.
        try:
            parsed = datetime.strptime(raw.strip(), "%d/%m/%Y").replace(tzinfo=UTC).date()
        except ValueError:
            parsed = None
    return LoadDate(
        last_load_date=parsed,
        raw_value=raw,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.LOAD_DATE_URL}/query",
            cached=was_cached,
            schema_name="eps.LoadDate",
        ),
    )
