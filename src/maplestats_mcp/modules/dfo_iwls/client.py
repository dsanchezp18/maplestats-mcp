"""HTTP client for the DFO/CHS Integrated Water Level System API.

See constants.py for the API behaviour confirmed live. Callers work
with five-digit CHS station codes (what tide tables print); the
internal station `id` the data route needs is resolved here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.dfo_iwls import constants
from maplestats_mcp.modules.dfo_iwls.schemas import (
    Datum,
    StationDetail,
    StationSearchResult,
    StationSummary,
    TimeSeriesInfo,
    WaterLevelPoint,
    WaterLevelSeries,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _raise_for(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    try:
        body = exc.response.json()
        detail = "; ".join(body.get("errors") or []) or body.get("message") or ""
    except ValueError:
        detail = exc.response.text[:200]
    if status == 404:
        raise NotFound(f"{context}: {detail}") from exc
    if status == 400:
        raise InvalidInput(f"{context}: {detail}") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    await _LIMITER.acquire()
    context = f"dfo_iwls:{path}"
    try:
        return await api_get(f"{constants.BASE_URL}{path}", params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{context} did not respond in time. Try again shortly.") from exc


def _station(obj: dict[str, Any], lang: str) -> StationSummary:
    name_key = "nameFr" if lang == "fr" else "nameEn"
    return StationSummary(
        code=obj["code"],
        id=obj["id"],
        name=obj.get("officialName") or obj["code"],
        alternative_name=obj.get("alternativeName") or None,
        latitude=obj.get("latitude"),
        longitude=obj.get("longitude"),
        operating=bool(obj.get("operating")),
        station_type=obj.get("type"),
        time_series=[
            TimeSeriesInfo(code=ts["code"], name=ts.get(name_key) or ts.get("nameEn") or ts["code"])
            for ts in obj.get("timeSeries") or []
        ],
    )


async def _all_stations() -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> Any:
        return await _get("/stations")

    return await cached_fetch("dfo-iwls:stations", constants.CACHE_TTL_STATIONS_SECONDS, fetch)


async def _station_by_code(code: str) -> dict[str, Any]:
    code = code.strip()
    if not code.isdigit():
        raise InvalidInput(f"station_code must be a CHS station code like '07120', got {code!r}.")
    stations, _ = await _all_stations()
    match = next((s for s in stations if s.get("code") == code.zfill(5)), None)
    if match is None:
        raise NotFound(f"No DFO tide station with code {code!r}. Use dfo_iwls_search_stations.")
    return match


async def search_stations(
    query: str = "",
    *,
    operating_only: bool = True,
    series_code: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> StationSearchResult:
    """Case-insensitive substring match on official and alternative names."""
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    stations, cached = await _all_stations()
    needle = query.strip().lower()
    matches = [
        s
        for s in stations
        if (not operating_only or s.get("operating"))
        and (
            not needle
            or needle in (s.get("officialName") or "").lower()
            or needle in (s.get("alternativeName") or "").lower()
            or needle == s.get("code")
        )
        and (
            not series_code
            or any(ts.get("code") == series_code for ts in s.get("timeSeries") or [])
        )
    ]
    return StationSearchResult(
        stations=[_station(s, lang) for s in matches[:limit]],
        total_matches=len(matches),
        returned_count=min(len(matches), limit),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/stations",
            cached=cached,
            schema_name="dfo_iwls.StationSearchResult",
            freshness="station list cached 24h",
        ),
    )


async def get_station(station_code: str, lang: str = "en") -> StationDetail:
    station = await _station_by_code(station_code)

    async def fetch() -> Any:
        return await _get(f"/stations/{station['id']}/metadata")

    meta, cached = await cached_fetch(
        f"dfo-iwls:metadata:{station['id']}", constants.CACHE_TTL_METADATA_SECONDS, fetch
    )
    return StationDetail(
        station=_station(station, lang),
        region_code=meta.get("chsRegionCode"),
        is_tidal=meta.get("isTidal"),
        is_tide_table_reference_port=meta.get("isTideTableReferencePort"),
        established_year=meta.get("establishedYear"),
        datums=[Datum(code=d["code"], offset=d.get("offset")) for d in meta.get("datums") or []],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/stations/{station['id']}/metadata",
            cached=cached,
            schema_name="dfo_iwls.StationDetail",
        ),
    )


def _parse_time(value: str | None, name: str, default: datetime) -> datetime:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an ISO date or datetime, got {value!r}.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def get_water_levels(
    station_code: str,
    series_code: str = "wlp-hilo",
    *,
    start: str | None = None,
    end: str | None = None,
    resolution: str | None = None,
    lang: str = "en",
) -> WaterLevelSeries:
    """One station's series over a window of at most 7 days (UTC).

    Defaults to today plus 24 hours. `resolution` is ignored for
    `wlp-hilo`, which the API answers with `[]` if one is sent.
    """
    station = await _station_by_code(station_code)
    series = next((ts for ts in station.get("timeSeries") or [] if ts["code"] == series_code), None)
    if series is None:
        available = [ts["code"] for ts in station.get("timeSeries") or []]
        raise InvalidInput(
            f"Station {station['code']} has no {series_code!r} series; available: {available}."
        )

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start_dt = _parse_time(start, "start", now)
    end_dt = _parse_time(end, "end", start_dt + timedelta(days=1))
    if end_dt <= start_dt:
        raise InvalidInput(f"end ({end_dt}) must be after start ({start_dt}).")
    if end_dt - start_dt > timedelta(days=constants.MAX_WINDOW_DAYS):
        raise InvalidInput(f"The window must be {constants.MAX_WINDOW_DAYS} days or less.")

    params: dict[str, Any] = {
        "time-series-code": series_code,
        "from": _iso(start_dt),
        "to": _iso(end_dt),
    }
    effective_resolution = None if series_code in constants.EVENT_SERIES else resolution
    if effective_resolution:
        params["resolution"] = effective_resolution

    async def fetch() -> Any:
        return await _get(f"/stations/{station['id']}/data", params)

    rows, cached = await cached_fetch(
        f"dfo-iwls:data:{station['id']}:{params}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )
    name_key = "nameFr" if lang == "fr" else "nameEn"
    return WaterLevelSeries(
        station_code=station["code"],
        station_name=station.get("officialName") or station["code"],
        series_code=series_code,
        series_name=series.get(name_key) or series_code,
        start=start_dt,
        end=end_dt,
        resolution=effective_resolution,
        points=[
            WaterLevelPoint(
                time=datetime.fromisoformat(row["eventDate"]),
                value=row["value"],
                qc_flag=row.get("qcFlagCode"),
                reviewed=row.get("reviewed"),
            )
            for row in rows
            if row.get("value") is not None
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/stations/{station['id']}/data",
            cached=cached,
            schema_name="dfo_iwls.WaterLevelSeries",
            limits=f"windows capped at {constants.MAX_WINDOW_DAYS} days per request",
        ),
    )
