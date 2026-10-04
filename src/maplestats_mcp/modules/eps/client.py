"""Client for EPS Community Safety Data Portal occurrences. See the
module docstring for the coverage and label quirks confirmed live.
Reuses `shared/arcgis.py` for the ArcGIS REST query and its embedded
`{"error": ...}` handling rather than re-implementing either.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

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
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.limits import join_limits

_CONFIG = arcgis.ArcGISHubConfig(
    source=constants.SOURCE,
    domain="services9.arcgis.com",
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)
_COUNT_FIELD = "occurrence_count"


def _coverage(dataset: str, lang: str) -> str:
    return pick(lang, constants.DATASET_COVERAGE[dataset], constants.DATASET_COVERAGE_FR[dataset])


def _layer_url(dataset: str, lang: str = "en") -> str:
    if dataset not in constants.DATASETS:
        raise_localized(
            InvalidInput,
            f"dataset must be one of {sorted(constants.DATASETS)}, got {dataset!r}.",
            f"dataset doit être l'une des valeurs {sorted(constants.DATASETS)} ; reçu {dataset!r}.",
            lang,
        )
    return constants.DATASETS[dataset]


async def _load_date(lang: str = "en") -> tuple[date | None, str | None, bool]:
    """(parsed load date, raw value, cached) from EPS's one-row load-date table."""

    async def fetch() -> dict[str, Any]:
        body = await arcgis.query_layer(_CONFIG, constants.LOAD_DATE_URL, 0, limit=1)
        # Seen 2026-09-28: EPS rebuilds this one-row table when it reloads
        # the data, and it is empty meanwhile. Raising here also keeps the
        # empty answer out of the cache.
        if not body.get("features"):
            raise_localized(
                UpstreamUnavailable,
                "eps: the load-date table is empty, which happens while EPS reloads "
                "its data. Try again later.",
                "eps : la table de la date de chargement est vide, ce qui arrive pendant que "
                "le Service de police d'Edmonton recharge ses données. Réessayez plus tard.",
                lang,
            )
        return body

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
    return parsed, raw if isinstance(raw, str) else None, was_cached


def _as_datetime(day: date | None) -> datetime | None:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) if day else None


async def _as_of(dataset: str) -> datetime | None:
    """The load date for the daily dataset; None for the closed 2023 year.

    A missing load date (the table is empty while EPS reloads) leaves as_of
    unset rather than failing a query that otherwise worked.
    """
    if dataset != "current":
        return None
    try:
        parsed, _, _ = await _load_date()
    except UpstreamUnavailable:
        return None
    return _as_datetime(parsed)


async def _window(layer_url: str) -> tuple[date | None, date | None]:
    """First and last Reported_Date in the whole layer (server-side min/max).

    Confirmed live 2026-10-03: "current" ran 2025-09-29 to 2026-09-27, so its
    first and last months are part-months (2025-09 had 422 occurrences
    against about 6,500 in a full month); "2023" ran 2023-01-01 to 2023-12-31.
    """
    statistics = [
        {
            "statisticType": "min",
            "onStatisticField": "Reported_Date",
            "outStatisticFieldName": "first_date",
        },
        {
            "statisticType": "max",
            "onStatisticField": "Reported_Date",
            "outStatisticFieldName": "last_date",
        },
    ]

    async def fetch() -> dict[str, Any]:
        return await arcgis.get_json(
            _CONFIG,
            "window",
            f"{layer_url}/query",
            params={"where": "1=1", "outStatistics": json.dumps(statistics)},
        )

    body, _ = await cached_fetch(
        f"eps:window:{layer_url}", constants.CACHE_TTL_WINDOW_SECONDS, fetch
    )
    features = body.get("features") or []
    attrs = (features[0].get("attributes") or {}) if features else {}
    return _epoch_to_date(attrs.get("first_date")), _epoch_to_date(attrs.get("last_date"))


def _month_partial(year: int, month: int, first: date | None, last: date | None) -> bool | None:
    """True when [first, last] does not cover the whole calendar month."""
    if first is None or last is None:
        return None
    month_start = date(year, month, 1)
    next_month = date(year + month // 12, month % 12 + 1, 1)
    return first > month_start or last < next_month - timedelta(days=1)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parse_iso_date(value: str, name: str, lang: str = "en") -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_localized(
            InvalidInput,
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.",
            f"{name} doit être une date ISO (AAAA-MM-JJ) ; reçu {value!r}.",
            lang,
        )


def build_where(
    *,
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
    lang: str = "en",
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
    start = _parse_iso_date(start_date, "start_date", lang) if start_date else None
    end = _parse_iso_date(end_date, "end_date", lang) if end_date else None
    if start and end and start > end:
        raise_localized(
            InvalidInput,
            f"start_date {start} is after end_date {end}.",
            f"start_date {start} est postérieure à end_date {end}.",
            lang,
        )
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
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}; reçu {limit}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être supérieur ou égal à 0 ; reçu {offset}.",
            lang,
        )
    layer_url = _layer_url(dataset, lang)
    where = build_where(
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
        lang=lang,
    )

    request: dict[str, Any] = {
        "where": where,
        "out_fields": (
            "Reported_Date,Occurrence_Category,Occurrence_Group,Occurrence_Type_Group,Intersection"
        ),
        "order_by": "Reported_Date DESC, OBJECTID DESC",
        "return_geometry": True,
        "limit": limit,
        "offset": offset,
        "out_sr": 4326,
    }

    async def fetch() -> tuple[int, list[dict[str, Any]]]:
        total = await _count(layer_url, where)
        body = await arcgis.query_layer(_CONFIG, layer_url, 0, **request)
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
            url=arcgis.query_url(layer_url, 0, **request),
            cached=was_cached,
            schema_name="eps.OccurrenceList",
            as_of=await _as_of(dataset),
            freshness=pick(
                lang,
                constants.DATASET_FRESHNESS[dataset],
                constants.DATASET_FRESHNESS_FR[dataset],
            ),
            coverage=_coverage(dataset, lang),
            limits=join_limits(
                (
                    pick(
                        lang,
                        f"Returned occurrences {offset + 1} to {offset + len(features)} of "
                        f"{total:,}, newest first; page with offset, narrow the filters, or use "
                        "eps_summarize_occurrences for counts",
                        f"Incidents {offset + 1} à {offset + len(features)} sur {total:,}".replace(
                            ",", "\u00a0"
                        )
                        + ", du plus récent au plus ancien ; paginez avec offset, resserrez "
                        "les filtres ou utilisez eps_summarize_occurrences pour les "
                        "dénombrements",
                    )
                    if features and offset + len(features) < total
                    else None
                ),
                pick(
                    lang,
                    "location is the nearest intersection only; no time of day",
                    "le lieu se limite à l'intersection la plus proche ; aucune heure n'est "
                    "indiquée",
                ),
            ),
            lang=lang,
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
    if group_by not in constants.GROUP_BY_FIELDS:
        raise_localized(
            InvalidInput,
            f"group_by must be one of {sorted(constants.GROUP_BY_FIELDS)}, got {group_by!r}.",
            f"group_by doit être l'une des valeurs {sorted(constants.GROUP_BY_FIELDS)}; "
            f"reçu {group_by!r}.",
            lang,
        )
    if not 1 <= top <= constants.LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"top must be between 1 and {constants.LIMIT_MAX}, got {top}.",
            f"top doit être compris entre 1 et {constants.LIMIT_MAX}; reçu {top}.",
            lang,
        )
    layer_url = _layer_url(dataset, lang)
    where = build_where(
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
        lang=lang,
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

    params = {
        "where": where,
        "groupByFieldsForStatistics": ",".join(fields),
        "outStatistics": json.dumps(statistics),
        "orderByFields": order_by,
        "resultRecordCount": top,
    }

    async def fetch() -> tuple[int, list[dict[str, Any]]]:
        total = await _count(layer_url, where)
        body = await arcgis.get_json(_CONFIG, "summarize", f"{layer_url}/query", params=params)
        return total, body.get("features") or []

    cache_key = f"eps:summary:{dataset}:{group_by}:{where}:{top}"
    (total, features), was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_QUERY_SECONDS, fetch
    )
    data_from: date | None = None
    data_to: date | None = None
    if group_by == "month":
        # The counts can only span the layer's dates, narrowed by the filters.
        first, last = await _window(layer_url)
        start = _parse_iso_date(start_date, "start_date") if start_date else None
        end = _parse_iso_date(end_date, "end_date") if end_date else None
        data_from = max(d for d in (first, start) if d) if first or start else None
        data_to = min(d for d in (last, end) if d) if last or end else None
    groups = []
    partial_months: list[str] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        partial: bool | None = None
        if group_by == "month":
            year, month = attrs.get("Reported_Year"), attrs.get("Reported_Month")
            if year is not None and month is not None:
                partial = _month_partial(int(year), int(month), data_from, data_to)
                if partial:
                    partial_months.append(f"{int(year)}-{int(month):02d}")
        groups.append(
            OccurrenceCount(
                keys={field: attrs.get(field) for field in fields},
                count=int(attrs.get(_COUNT_FIELD) or 0),
                partial=partial,
            )
        )
    limits = pick(lang, f"at most {top} groups returned", f"au plus {top} groupes renvoyés")
    if partial_months:
        limits += pick(
            lang,
            f"; {', '.join(partial_months)} cover only part of the month (data from "
            f"{data_from} to {data_to}), so their counts are not comparable to full months",
            f" ; {', '.join(partial_months)} ne couvrent qu'une partie du mois (données du "
            f"{data_from} au {data_to}) : leurs nombres ne se comparent pas à ceux d'un mois "
            "complet",
        )
    return OccurrenceSummary(
        dataset=dataset,
        group_by=group_by,
        where=where,
        total_matches=total,
        groups=groups,
        data_from=data_from,
        data_to=data_to,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(f"{layer_url}/query", params=params)),
            cached=was_cached,
            schema_name="eps.OccurrenceSummary",
            as_of=await _as_of(dataset),
            freshness=pick(
                lang,
                constants.DATASET_FRESHNESS[dataset],
                constants.DATASET_FRESHNESS_FR[dataset],
            ),
            coverage=_coverage(dataset, lang),
            limits=limits,
            lang=lang,
        ),
    )


async def get_last_load_date(*, lang: str = "en") -> LoadDate:
    """Return EPS's own record of when the occurrence data was last loaded."""
    parsed, raw, was_cached = await _load_date(lang)
    return LoadDate(
        last_load_date=parsed,
        raw_value=raw,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=arcgis.query_url(constants.LOAD_DATE_URL, 0, limit=1),
            cached=was_cached,
            schema_name="eps.LoadDate",
            as_of=_as_datetime(parsed),
            freshness=pick(
                lang,
                constants.DATASET_FRESHNESS["current"],
                constants.DATASET_FRESHNESS_FR["current"],
            ),
            lang=lang,
        ),
    )
