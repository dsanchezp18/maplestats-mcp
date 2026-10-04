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
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error, truncation_note_lang
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.licences_fr import licence_for_lang
from maplestats_mcp.shared.limits import fit_to_budget, join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _raise_for(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    try:
        body = exc.response.json()
        detail = "; ".join(body.get("errors") or []) or body.get("message") or ""
    except ValueError:
        detail = exc.response.text[:200]
    # `detail` is the API's own message, in English only.
    if status == 404:
        raise lang_error(
            NotFound, lang, f"{context}: {detail}", f"{context} (message de l'API) : {detail}"
        ) from exc
    if status == 400:
        raise lang_error(
            InvalidInput, lang, f"{context}: {detail}", f"{context} (message de l'API) : {detail}"
        ) from exc
    raise lang_error(
        UpstreamError,
        lang,
        f"{context} returned HTTP {status}: {detail}",
        f"{context} a répondu HTTP {status} (message de l'API) : {detail}",
    ) from exc


async def _get(path: str, params: dict[str, Any] | None = None, lang: str = "en") -> Any:
    await _LIMITER.acquire()
    context = f"dfo_iwls:{path}"
    try:
        return await api_get(f"{constants.BASE_URL}{path}", params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, context, lang)
    except httpx.HTTPError as exc:
        raise lang_error(
            UpstreamUnavailable,
            lang,
            f"{context} did not respond in time. Try again shortly.",
            f"{context} n'a pas répondu à temps. Réessayez dans un instant.",
        ) from exc


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


async def _all_stations(lang: str = "en") -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> Any:
        return await _get("/stations", lang=lang)

    return await cached_fetch("dfo-iwls:stations", constants.CACHE_TTL_STATIONS_SECONDS, fetch)


async def _station_by_code(code: str, lang: str = "en") -> dict[str, Any]:
    code = code.strip()
    if not code.isdigit():
        raise lang_error(
            InvalidInput,
            lang,
            f"station_code must be a CHS station code like '07120', got {code!r}.",
            f"station_code doit être un code de station du SHC comme « 07120 » ; reçu {code!r}.",
        )
    stations, _ = await _all_stations(lang)
    match = next((s for s in stations if s.get("code") == code.zfill(5)), None)
    if match is None:
        raise lang_error(
            NotFound,
            lang,
            f"No DFO tide station with code {code!r}. Use dfo_iwls_search_stations.",
            f"aucune station marégraphique du MPO avec le code {code!r}. Utilisez "
            "dfo_iwls_search_stations.",
        )
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
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.SEARCH_LIMIT_MAX} ; reçu {limit}.",
        )
    stations, cached = await _all_stations(lang)
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
            limits=fr_or_en(
                lang,
                f"Request: GET {constants.BASE_URL}/stations (the full list); the name "
                "filter, operating_only and series_code are applied here.",
                f"Requête : GET {constants.BASE_URL}/stations (la liste complète) ; le filtre "
                "sur le nom, operating_only et series_code sont appliqués ici. Les noms des "
                "stations sont les noms officiels publiés par le SHC.",
            ),
            freshness=fr_or_en(
                lang, "station list cached 24h", "liste des stations mise en cache 24 h"
            ),
            licence=licence_for_lang(
                constants.RATE_LIMIT_SOURCE, f"{constants.BASE_URL}/stations", lang
            ),
            lang=lang,
        ),
    )


async def get_station(station_code: str, lang: str = "en") -> StationDetail:
    station = await _station_by_code(station_code, lang)

    async def fetch() -> Any:
        return await _get(f"/stations/{station['id']}/metadata", lang=lang)

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
            licence=licence_for_lang(
                constants.RATE_LIMIT_SOURCE,
                f"{constants.BASE_URL}/stations/{station['id']}/metadata",
                lang,
            ),
            lang=lang,
        ),
    )


def _parse_time(
    value: str | None,
    name: str,
    default: datetime,
    *,
    end_of_day: bool = False,
    lang: str = "en",
) -> datetime:
    """Parse a bound; a date-only `end` means the end of that UTC day.

    end="2026-10-03" used to mean midnight at its start, so start=end on
    one date was refused and end="2026-10-02" left out all of October 2.
    """
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise lang_error(
            InvalidInput,
            lang,
            f"{name} must be an ISO date or datetime, got {value!r}.",
            f"{name} doit être une date ou une date-heure ISO ; reçu {value!r}.",
        ) from exc
    if end_of_day and len(value.strip()) == 10:
        parsed += timedelta(days=1)
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
    station = await _station_by_code(station_code, lang)
    series = next((ts for ts in station.get("timeSeries") or [] if ts["code"] == series_code), None)
    if series is None:
        available = [ts["code"] for ts in station.get("timeSeries") or []]
        raise lang_error(
            InvalidInput,
            lang,
            f"Station {station['code']} has no {series_code!r} series; available: {available}.",
            f"la station {station['code']} n'a pas de série {series_code!r} ; séries "
            f"disponibles : {available}.",
        )

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start_dt = _parse_time(start, "start", now, lang=lang)
    end_dt = _parse_time(end, "end", start_dt + timedelta(days=1), end_of_day=True, lang=lang)
    if end_dt <= start_dt:
        raise lang_error(
            InvalidInput,
            lang,
            f"end ({end_dt}) must be after start ({start_dt}).",
            f"end ({end_dt}) doit être postérieur à start ({start_dt}).",
        )
    cap = timedelta(days=constants.MAX_WINDOW_DAYS)
    whole_day_end = bool(end) and len((end or "").strip()) == 10
    if whole_day_end and cap < end_dt - start_dt <= cap + timedelta(days=1):
        # A date-only end one day past the cap is read as "up to that date".
        end_dt = start_dt + cap
    if end_dt - start_dt > cap:
        raise lang_error(
            InvalidInput,
            lang,
            f"The window must be {constants.MAX_WINDOW_DAYS} days or less.",
            f"la période doit être d'au plus {constants.MAX_WINDOW_DAYS} jours.",
        )

    params: dict[str, Any] = {
        "time-series-code": series_code,
        "from": _iso(start_dt),
        "to": _iso(end_dt),
    }
    effective_resolution = None if series_code in constants.EVENT_SERIES else resolution
    defaulted = False
    if (
        effective_resolution is None
        and series_code not in constants.EVENT_SERIES
        and end_dt - start_dt > timedelta(days=1)
    ):
        # Minute data over a week came to about 770 KB; past one day the
        # default is a coarser step, and limits says so.
        effective_resolution = constants.LONG_WINDOW_RESOLUTION
        defaulted = True
    if effective_resolution:
        params["resolution"] = effective_resolution

    async def fetch() -> Any:
        return await _get(f"/stations/{station['id']}/data", params, lang)

    rows, cached = await cached_fetch(
        f"dfo-iwls:data:{station['id']}:{params}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )
    name_key = "nameFr" if lang == "fr" else "nameEn"
    points = [
        WaterLevelPoint(
            time=datetime.fromisoformat(row["eventDate"]),
            value=row["value"],
            qc_flag=row.get("qcFlagCode"),
            reviewed=row.get("reviewed"),
        )
        for row in rows
        if row.get("value") is not None
    ]
    # Points run oldest first; over the byte budget, keep the most recent.
    kept = fit_to_budget(points[::-1])[::-1]
    data_url = str(httpx.URL(f"{constants.BASE_URL}/stations/{station['id']}/data", params=params))
    return WaterLevelSeries(
        station_code=station["code"],
        station_name=station.get("officialName") or station["code"],
        series_code=series_code,
        series_name=series.get(name_key) or series_code,
        start=start_dt,
        end=end_dt,
        resolution=effective_resolution,
        points=kept,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=data_url,
            cached=cached,
            schema_name="dfo_iwls.WaterLevelSeries",
            limits=join_limits(
                fr_or_en(
                    lang,
                    f"windows capped at {constants.MAX_WINDOW_DAYS} days per request",
                    f"période limitée à {constants.MAX_WINDOW_DAYS} jours par requête",
                ),
                fr_or_en(
                    lang,
                    f"no resolution was given for a window over one day, so "
                    f"{constants.LONG_WINDOW_RESOLUTION} was used; pass resolution to choose",
                    f"aucune résolution n'a été donnée pour une période de plus d'un jour : "
                    f"{constants.LONG_WINDOW_RESOLUTION} a été utilisée ; passez resolution "
                    "pour choisir",
                )
                if defaulted
                else None,
                truncation_note_lang(
                    lang,
                    returned=len(kept),
                    total=len(points),
                    unit="points (about 200 KB)",
                    unit_fr="points (environ 200 Ko)",
                    order="latest",
                    how_to_get_more="shorten the window or pass a coarser resolution",
                    how_to_get_more_fr="raccourcissez la période ou passez une résolution "
                    "plus grossière",
                ),
            ),
            licence=licence_for_lang(constants.RATE_LIMIT_SOURCE, data_url, lang),
            lang=lang,
        ),
    )
