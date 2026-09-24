"""Client for the Earthquakes Canada FDSN event service.

Requests `format=text` and parses the pipe-separated table by header
name, so a reordered or extended column set still reads correctly.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx

from maple_data_mcp.modules.earthquakes import constants
from maple_data_mcp.modules.earthquakes.schemas import Earthquake, EarthquakeSearchResult
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_KM_PER_DEGREE = 111.19
_EVENT_ID = re.compile(r"^\d{8}\.\d{4}(\d{3})?$")


async def _fetch(params: dict[str, Any]) -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(constants.BASE_URL, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ""
            if exc.response.status_code in (400, 422):
                raise InvalidInput(
                    f"earthquakes: the service rejected the query: {exc.response.text[:200]}"
                ) from exc
            raise UpstreamError(
                f"earthquakes: {constants.BASE_URL} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"earthquakes: {constants.BASE_URL} could not be reached."
            ) from exc
        return "" if response.status_code == 204 else response.text

    return await cached_fetch(
        f"earthquakes:{sorted(params.items())}", constants.CACHE_TTL_SECONDS, fetch
    )


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _location(value: str | None, lang: Literal["en", "fr"]) -> str | None:
    if not value:
        return None
    # "62 km WSW of X, YT/62 km OSO de X, YT"; place names hold no "/".
    parts = value.split("/")
    if len(parts) != 2:
        return value
    return (parts[1] if lang == "fr" else parts[0]).strip()


def parse_text(text: str, lang: Literal["en", "fr"] = "en") -> list[Earthquake]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    if not lines[0].startswith("#"):
        if lines[0].lstrip().lower().startswith(("<!doctype", "<html", "<?xml")):
            raise UpstreamError("earthquakes: expected a text table, got markup.")
        raise UpstreamError("earthquakes: response has no header row.")
    header = [h.strip().lower() for h in lines[0].lstrip("#").split("|")]
    quakes = []
    for line in lines[1:]:
        row = dict(zip(header, (v.strip() for v in line.split("|")), strict=False))
        quakes.append(
            Earthquake(
                event_id=row.get("eventid", ""),
                time=_time(row.get("time")),
                latitude=_float(row.get("latitude")),
                longitude=_float(row.get("longitude")),
                depth_km=_float(row.get("depth/km")),
                magnitude=_float(row.get("magnitude")),
                magnitude_type=row.get("magtype") or None,
                location=_location(row.get("eventlocationname"), lang),
            )
        )
    quakes.sort(key=lambda q: q.time or datetime.min.replace(tzinfo=UTC), reverse=True)
    return quakes


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInput(f"{name} must be YYYY-MM-DD, got {value!r}.") from exc


async def search(
    *,
    start: str | None = None,
    end: str | None = None,
    min_magnitude: float | None = None,
    max_magnitude: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    event_id: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> EarthquakeSearchResult:
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")
    params: dict[str, Any] = {"format": "text"}
    if event_id:
        event_id = event_id.strip()
        if not _EVENT_ID.match(event_id):
            raise InvalidInput(
                f"event_id must look like 20260924.1414001 or 20260924.1414, got {event_id!r}."
            )
        # The service looks up by minute only; narrow to the exact event after.
        params["eventid"] = event_id[:13]
    else:
        end_date = _date(end, "end") or datetime.now(UTC).date()
        start_date = _date(start, "start") or end_date - timedelta(days=constants.DAYS_DEFAULT)
        if start_date > end_date:
            raise InvalidInput(f"start {start_date} is after end {end_date}.")
        if (end_date - start_date).days > constants.MAX_SPAN_DAYS:
            raise InvalidInput(
                f"Date range is limited to {constants.MAX_SPAN_DAYS} days; narrow start/end."
            )
        params["starttime"] = f"{start_date.isoformat()}T00:00:00"
        params["endtime"] = f"{end_date.isoformat()}T23:59:59"
        if min_magnitude is not None:
            params["minmagnitude"] = min_magnitude
        if max_magnitude is not None:
            params["maxmagnitude"] = max_magnitude
        point = (latitude, longitude, radius_km)
        if any(v is not None for v in point):
            if latitude is None or longitude is None or radius_km is None:
                raise InvalidInput("latitude, longitude and radius_km go together.")
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 < radius_km <= 5000):
                raise InvalidInput("Invalid point or radius_km (must be 0-5000).")
            params.update(
                latitude=latitude,
                longitude=longitude,
                maxradius=round(radius_km / _KM_PER_DEGREE, 4),
            )
        if bbox is not None:
            west, south, east, north = bbox
            if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
                raise InvalidInput("bbox must be (west, south, east, north) in degrees.")
            params.update(
                minlatitude=south, maxlatitude=north, minlongitude=west, maxlongitude=east
            )
    text, cached = await _fetch(params)
    quakes = parse_text(text, lang)
    if event_id and len(event_id) > 13:
        quakes = [q for q in quakes if q.event_id == event_id]
    if event_id and not quakes:
        raise NotFound(f"No Earthquakes Canada event {event_id!r}.")
    kept = quakes[:limit]
    return EarthquakeSearchResult(
        earthquakes=kept,
        total_matches=len(quakes),
        returned_count=len(kept),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=str(httpx.URL(constants.BASE_URL, params=params)),
            cached=cached,
            schema_name="earthquakes.EarthquakeSearchResult",
            freshness="catalogue updates within minutes; cached 5 min",
            limits=f"date range up to {constants.MAX_SPAN_DAYS} days",
        ),
    )
