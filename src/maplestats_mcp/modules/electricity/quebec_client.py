"""Client for Hydro-Quebec's open data (donnees.hydroquebec.com, Opendatasoft).

Confirmed live 2026-09-29 against the Explore API v2.1, no key:

- `demande-electricite-quebec`: 15-minute total demand (`valeurs_demandetotal`,
  MW) for a rolling two local days starting at local midnight (192 rows,
  2026-09-28T04:00Z onward); slots not yet reached are null rows, so "latest"
  needs a not-null filter.
- `historique-demande-electricite-quebec`: hourly average MW (`moyenne_mw`),
  2019-01-01 to 2025-01-01 only (metadata modified 2026-06-05), not kept current.
- `production-electricite-quebec`: hourly at :30 (`valeurs_total`, `_hydraulique`,
  `_eolien`, `_autres`, `_solaire`, `_thermique`), 48 rows; future hours are
  placeholder rows with `valeurs_total` 0.0 and null components.
- `historique-production-electricite-quebec`: hourly, 2019-01-01 to 2026-01-01.
- `importations-exportations-avec-transits`: hourly, 48 rows, exports per market
  (negative = net import) and imports per market and source. Future hours are
  placeholders with zeros, so a date cutoff at "now" is applied. On 48 live rows
  `exportations_total` equalled the sum of the positive market values.
- All timestamps are UTC instants (local midnight EDT appears as 04:00Z).
- `/records` caps `limit` at 100 and `offset + limit` at 10000 (HTTP 400 past
  that); `/exports/json` streams up to the requested `limit` in one response,
  so it is used for the data and `/records?limit=0` only for `total_count`.
- Licence is CC BY-NC 4.0 on every dataset (non-commercial use, credit
  Hydro-Quebec); each response repeats it in provenance limits.
"""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from maplestats_mcp.modules.electricity import constants
from maplestats_mcp.modules.electricity.client import _check_limit, _parse_date
from maplestats_mcp.modules.electricity.schemas import (
    QuebecDataset,
    QuebecDemand,
    QuebecDemandPoint,
    QuebecGeneration,
    QuebecGenerationPoint,
    QuebecTrade,
    QuebecTradePoint,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.QUEBEC_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _limits(extra: str = "") -> str:
    return f"{extra} {constants.QUEBEC_LICENCE}".strip()


async def _get_json(url: str, params: dict[str, Any], context: str) -> Any:
    await _LIMITER.acquire()
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise NotFound(f"electricity:{context} dataset not found.") from exc
        if 400 <= status < 500:
            raise InvalidInput(
                f"electricity:{context} rejected the query (HTTP {status})."
            ) from exc
        raise UpstreamError(f"electricity:{context} returned HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"electricity:{context} did not respond in time.") from exc


def _timestamp(record: dict[str, Any], context: str) -> datetime:
    try:
        return datetime.fromisoformat(str(record["date"]))
    except (KeyError, ValueError) as exc:
        raise UpstreamError(f"electricity:{context} record has no valid date.") from exc


def _value(record: dict[str, Any], field: str) -> float | None:
    value = record.get(field)
    return float(value) if isinstance(value, int | float) else None


def _source_value(record: dict[str, Any], market: str, source: str) -> float | None:
    # The dataset spells the unknown source "unknow" for Ontario and "unknown" elsewhere.
    names = ("unknown", "unknow") if source == "unknown" else (source,)
    for name in names:
        value = _value(record, f"importations_sources_{market}_{name}")
        if value is not None:
            return value
    return None


def _where(start: date | None, end: date | None, not_null: str | None, cutoff: bool) -> str | None:
    clauses = []
    if start:
        clauses.append(f'date >= "{start.isoformat()}T00:00:00Z"')
    if end:
        clauses.append(f'date < "{(end + timedelta(days=1)).isoformat()}T00:00:00Z"')
    if cutoff:
        # Placeholder rows for hours not yet reached would otherwise read as zeros.
        clauses.append(f'date <= "{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}"')
    if not_null:
        clauses.append(f"{not_null} is not null")
    return " and ".join(clauses) or None


async def _fetch_rows(
    dataset_id: str,
    where: str | None,
    latest: bool,
    limit: int,
    cache_key: str,
    ttl: int,
    context: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Return (rows oldest-first, total matched, was_cached)."""
    base = f"{constants.QUEBEC_DATASETS_URL}/{dataset_id}"

    async def fetch() -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"limit": limit, "order_by": "date desc" if latest else "date"}
        count_params: dict[str, Any] = {"limit": 0}
        if where:
            params["where"] = where
            count_params["where"] = where
        rows = await _get_json(f"{base}/exports/json", params, context)
        counted = await _get_json(f"{base}/records", count_params, context)
        if not isinstance(rows, list) or not isinstance(counted, dict):
            raise UpstreamError(f"electricity:{context} answered in an unexpected shape.")
        return rows, int(counted.get("total_count", len(rows)))

    (rows, total), was_cached = await cached_fetch(cache_key, ttl, fetch)
    return (list(reversed(rows)) if latest else rows), total, was_cached


def _ttl(dataset: QuebecDataset) -> int:
    if dataset == "recent":
        return constants.QUEBEC_CACHE_TTL_RECENT_SECONDS
    return constants.QUEBEC_CACHE_TTL_HISTORY_SECONDS


def _check_dataset(dataset: str) -> None:
    if dataset not in ("recent", "history"):
        raise InvalidInput(f"dataset must be 'recent' or 'history', got {dataset!r}.")


def _range(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None]:
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    if start and end and start > end:
        raise InvalidInput("start_date must not be after end_date.")
    return start, end


async def get_demand(
    dataset: QuebecDataset = "recent",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> QuebecDemand:
    del lang
    _check_dataset(dataset)
    _check_limit(limit)
    start, end = _range(start_date, end_date)
    field = "valeurs_demandetotal" if dataset == "recent" else "moyenne_mw"
    dataset_id = constants.QUEBEC_DEMAND_DATASETS[dataset]
    where = _where(start, end, field, cutoff=False)
    latest = not (start or end)
    rows, total, was_cached = await _fetch_rows(
        dataset_id,
        where,
        latest,
        limit,
        f"electricity:qc:demand:{dataset}:{where}:{latest}:{limit}",
        _ttl(dataset),
        "quebec_demand",
    )
    points = [
        QuebecDemandPoint(timestamp=_timestamp(r, "quebec_demand"), demand_mw=_value(r, field))
        for r in rows
    ]
    values = [p.demand_mw for p in points if p.demand_mw is not None]
    last = points[-1] if points else None
    return QuebecDemand(
        dataset=dataset,
        interval="15 minutes" if dataset == "recent" else "hourly average",
        points=points,
        rows_matched=total,
        latest_timestamp=last.timestamp if last else None,
        latest_demand_mw=last.demand_mw if last else None,
        # Peak and average cover the returned rows only.
        peak_demand_mw=max(values) if values else None,
        average_demand_mw=round(statistics.fmean(values), 1) if values else None,
        provenance=make_provenance(
            source=constants.QUEBEC_SOURCE,
            url=f"{constants.QUEBEC_DATASETS_URL}/{dataset_id}",
            cached=was_cached,
            schema_name="electricity.QuebecDemand",
            freshness=(
                "recent: about two local days at 15 minutes, refreshed through the day"
                if dataset == "recent"
                else "archive ends 2025-01-01, not kept current"
            ),
            coverage="Quebec (Hydro-Quebec system) only",
            limits=_limits(
                f"Rows capped at {limit}; {total} rows matched. Start/end dates are UTC days."
            ),
        ),
    )


async def get_generation(
    dataset: QuebecDataset = "recent",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> QuebecGeneration:
    del lang
    _check_dataset(dataset)
    _check_limit(limit)
    start, end = _range(start_date, end_date)
    prefix = "valeurs_" if dataset == "recent" else ""
    dataset_id = constants.QUEBEC_GENERATION_DATASETS[dataset]
    where = _where(start, end, f"{prefix}hydraulique", cutoff=dataset == "recent")
    latest = not (start or end)
    rows, total, was_cached = await _fetch_rows(
        dataset_id,
        where,
        latest,
        limit,
        f"electricity:qc:generation:{dataset}:{where}:{latest}:{limit}",
        _ttl(dataset),
        "quebec_generation",
    )
    points = [
        QuebecGenerationPoint(
            timestamp=_timestamp(r, "quebec_generation"),
            total_mw=_value(r, f"{prefix}total"),
            hydro_mw=_value(r, f"{prefix}hydraulique"),
            wind_mw=_value(r, f"{prefix}eolien"),
            solar_mw=_value(r, f"{prefix}solaire"),
            thermal_mw=_value(r, f"{prefix}thermique"),
            other_mw=_value(r, f"{prefix}autres"),
        )
        for r in rows
    ]
    sources = ("hydro", "wind", "solar", "thermal", "other")
    means = {
        name: statistics.fmean(v for p in points if (v := getattr(p, f"{name}_mw")) is not None)
        for name in sources
        if any(getattr(p, f"{name}_mw") is not None for p in points)
    }
    total_mean = sum(means.values())
    return QuebecGeneration(
        dataset=dataset,
        points=points,
        rows_matched=total,
        average_share_percent=(
            {name: round(100 * m / total_mean, 2) for name, m in means.items()}
            if total_mean
            else {}
        ),
        provenance=make_provenance(
            source=constants.QUEBEC_SOURCE,
            url=f"{constants.QUEBEC_DATASETS_URL}/{dataset_id}",
            cached=was_cached,
            schema_name="electricity.QuebecGeneration",
            freshness=(
                "recent: hourly, about two local days"
                if dataset == "recent"
                else "archive ends 2026-01-01, not kept current"
            ),
            coverage="Hydro-Quebec system generation by source group",
            limits=_limits(
                f"Rows capped at {limit}; {total} rows matched. Shares use the mean of the "
                "returned rows."
            ),
        ),
    )


async def get_trade(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> QuebecTrade:
    del lang
    _check_limit(limit)
    start, end = _range(start_date, end_date)
    where = _where(start, end, None, cutoff=True)
    latest = not (start or end)
    rows, total, was_cached = await _fetch_rows(
        constants.QUEBEC_TRADE_DATASET,
        where,
        latest,
        limit,
        f"electricity:qc:trade:{where}:{latest}:{limit}",
        constants.QUEBEC_CACHE_TTL_RECENT_SECONDS,
        "quebec_trade",
    )
    points = [
        QuebecTradePoint(
            timestamp=_timestamp(r, "quebec_trade"),
            exports_total_mw=_value(r, "exportations_total"),
            net_exports_mw={
                m: _value(r, f"exportations_{m}") for m in constants.QUEBEC_TRADE_MARKETS
            },
            imports_mw={
                m: _value(r, f"importations_sources_{m}_total")
                for m in constants.QUEBEC_TRADE_MARKETS
            },
            import_sources_mw={
                m: {s: _source_value(r, m, s) for s in constants.QUEBEC_TRADE_SOURCES}
                for m in constants.QUEBEC_TRADE_MARKETS
            },
        )
        for r in rows
    ]
    return QuebecTrade(
        points=points,
        rows_matched=total,
        provenance=make_provenance(
            source=constants.QUEBEC_SOURCE,
            url=f"{constants.QUEBEC_DATASETS_URL}/{constants.QUEBEC_TRADE_DATASET}",
            cached=was_cached,
            schema_name="electricity.QuebecTrade",
            freshness="hourly, about two local days; hours not yet reached are excluded",
            coverage="markets: New England, New Brunswick, New York, Ontario; includes wheel-through",
            limits=_limits(
                f"Rows capped at {limit}; {total} rows matched. Start/end are UTC days."
            ),
        ),
    )
