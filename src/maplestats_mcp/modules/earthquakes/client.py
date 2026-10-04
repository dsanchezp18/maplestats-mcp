"""Client for the Earthquakes Canada FDSN event service.

Requests `format=text` and parses the pipe-separated table by header
name, so a reordered or extended column set still reads correctly.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx

from maplestats_mcp.modules.earthquakes import constants
from maplestats_mcp.modules.earthquakes.schemas import Earthquake, EarthquakeSearchResult
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_KM_PER_DEGREE = 111.19
_EVENT_ID = re.compile(r"^\d{8}\.\d{4}(\d{3})?$")


async def _fetch(params: dict[str, Any], lang: str = "en") -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(constants.BASE_URL, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ""
            if exc.response.status_code in (400, 422):
                raise lang_error(
                    InvalidInput,
                    lang,
                    f"earthquakes: the service rejected the query: {exc.response.text[:200]}",
                    f"earthquakes : le service a refusé la requête (texte du service, en "
                    f"anglais) : {exc.response.text[:200]}",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"earthquakes: {constants.BASE_URL} returned HTTP {exc.response.status_code}.",
                f"earthquakes : {constants.BASE_URL} a répondu HTTP {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"earthquakes: {constants.BASE_URL} could not be reached.",
                f"earthquakes : {constants.BASE_URL} est injoignable.",
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
            raise lang_error(
                UpstreamError,
                lang,
                "earthquakes: expected a text table, got markup.",
                "earthquakes : un tableau texte était attendu, le service a renvoyé du balisage.",
            )
        raise lang_error(
            UpstreamError,
            lang,
            "earthquakes: response has no header row.",
            "earthquakes : la réponse n'a pas de ligne d'en-tête.",
        )
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


def _date(value: str | None, name: str, lang: str = "en") -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise lang_error(
            InvalidInput,
            lang,
            f"{name} must be YYYY-MM-DD, got {value!r}.",
            f"{name} doit être au format AAAA-MM-JJ ; reçu {value!r}.",
        ) from exc


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
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX} ; reçu {limit}.",
        )
    params: dict[str, Any] = {"format": "text"}
    if event_id:
        event_id = event_id.strip()
        if not _EVENT_ID.match(event_id):
            raise lang_error(
                InvalidInput,
                lang,
                f"event_id must look like 20260924.1414001 or 20260924.1414, got {event_id!r}.",
                f"event_id doit avoir la forme 20260924.1414001 ou 20260924.1414 ; reçu "
                f"{event_id!r}.",
            )
        # The service looks up by minute only; narrow to the exact event after.
        params["eventid"] = event_id[:13]
    else:
        end_date = _date(end, "end", lang) or datetime.now(UTC).date()
        start_date = _date(start, "start", lang) or end_date - timedelta(
            days=constants.DAYS_DEFAULT
        )
        if start_date > end_date:
            raise lang_error(
                InvalidInput,
                lang,
                f"start {start_date} is after end {end_date}.",
                f"start ({start_date}) est postérieur à end ({end_date}).",
            )
        if (end_date - start_date).days > constants.MAX_SPAN_DAYS:
            raise lang_error(
                InvalidInput,
                lang,
                f"Date range is limited to {constants.MAX_SPAN_DAYS} days; narrow start/end.",
                f"La période est limitée à {constants.MAX_SPAN_DAYS} jours ; resserrez "
                "start et end.",
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
                raise lang_error(
                    InvalidInput,
                    lang,
                    "latitude, longitude and radius_km go together.",
                    "latitude, longitude et radius_km doivent être fournis ensemble.",
                )
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 < radius_km <= 5000):
                raise lang_error(
                    InvalidInput,
                    lang,
                    "Invalid point or radius_km (must be 0-5000).",
                    "Point ou radius_km invalide (radius_km doit être entre 0 et 5000).",
                )
            params.update(
                latitude=latitude,
                longitude=longitude,
                maxradius=round(radius_km / _KM_PER_DEGREE, 4),
            )
        if bbox is not None:
            west, south, east, north = bbox
            if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
                raise lang_error(
                    InvalidInput,
                    lang,
                    "bbox must be (west, south, east, north) in degrees.",
                    "bbox doit être (ouest, sud, est, nord) en degrés.",
                )
            params.update(
                minlatitude=south, maxlatitude=north, minlongitude=west, maxlongitude=east
            )
        # The service honours FDSN `limit` (newest first, confirmed live
        # 2026-10-03). Without it, limit=2 over 2021-2025 downloaded all
        # 34,973 events; one extra row says whether more match.
        params["limit"] = limit + 1
    text, cached = await _fetch(params, lang)
    quakes = parse_text(text, lang)
    if event_id and len(event_id) > 13:
        quakes = [q for q in quakes if q.event_id == event_id]
    if event_id and not quakes:
        raise lang_error(
            NotFound,
            lang,
            f"No Earthquakes Canada event {event_id!r}.",
            f"aucun événement {event_id!r} dans le catalogue de Séismes Canada.",
        )
    kept = quakes[:limit]
    has_more = len(quakes) > limit
    url = str(httpx.URL(constants.BASE_URL, params=params))
    return EarthquakeSearchResult(
        earthquakes=kept,
        total_matches=None if has_more else len(quakes),
        has_more=has_more,
        returned_count=len(kept),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="earthquakes.EarthquakeSearchResult",
            freshness=fr_or_en(
                lang,
                "catalogue updates within minutes; cached 5 min",
                "catalogue mis à jour en quelques minutes ; mis en cache 5 min",
            ),
            limits=fr_or_en(
                lang,
                f"date range up to {constants.MAX_SPAN_DAYS} days",
                f"période d'au plus {constants.MAX_SPAN_DAYS} jours",
            ),
            lang=lang,
        ),
    )
