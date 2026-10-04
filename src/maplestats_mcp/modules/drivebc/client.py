"""Client for DriveBC's Open511 API. See the package docstring for what was
confirmed live (licence, paging, the hard rate limit).

The whole active list is fetched once (one or two requests) and cached for
three minutes; every filter is applied in memory, so a burst of tool calls
costs one upstream request rather than one per call.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from maplestats_mcp.modules.drivebc import constants as c
from maplestats_mcp.modules.drivebc.schemas import (
    Area,
    AreaList,
    EventArea,
    EventCount,
    EventDetail,
    EventRoad,
    EventSearch,
    EventSummary,
    RoadEvent,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = "Live: DriveBC updates events as they change; cached here for three minutes."


async def _get(url: str, params: dict[str, Any]) -> Any:
    await get_limiter(c.SOURCE, c.RATE_LIMIT_PER_SECOND, c.RATE_LIMIT_CAPACITY).acquire()
    try:
        return await api_get(url, params={"format": "json", **params}, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            raise UpstreamUnavailable(
                "DriveBC's Open511 API is rate-limiting requests (HTTP 429); try again in a minute."
            ) from exc
        if status >= 500:
            raise UpstreamUnavailable(f"DriveBC's Open511 API answered HTTP {status}.") from exc
        raise UpstreamError(f"DriveBC's Open511 API answered HTTP {status} for {url}.") from exc
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise UpstreamUnavailable(f"DriveBC's Open511 API did not answer: {exc}") from exc
    except httpx.DecodingError as exc:
        raise UpstreamError(f"DriveBC's Open511 API returned non-JSON from {url}.") from exc


async def _events() -> tuple[list[dict[str, Any]], bool]:
    """Every ACTIVE event, all pages (the API reports no total, only an offset)."""

    async def fetch() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for page in range(c.MAX_PAGES):
            body = await _get(
                c.EVENTS_URL,
                {"status": "ACTIVE", "limit": c.PAGE_SIZE, "offset": page * c.PAGE_SIZE},
            )
            if not isinstance(body, dict) or "events" not in body:
                raise UpstreamError("DriveBC's Open511 events response has no 'events' list.")
            batch = list_or_empty(body, "events")
            events.extend(batch)
            if len(batch) < c.PAGE_SIZE:
                return events
        raise UpstreamError(
            f"DriveBC listed more than {c.PAGE_SIZE * c.MAX_PAGES} active events; refusing to "
            "page further."
        )

    return await cached_fetch("drivebc:events", c.CACHE_TTL_EVENTS, fetch)


async def _areas() -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> list[dict[str, Any]]:
        body = await _get(c.AREAS_URL, {})
        if not isinstance(body, dict) or "areas" not in body:
            raise UpstreamError("DriveBC's Open511 areas response has no 'areas' list.")
        return list_or_empty(body, "areas")

    return await cached_fetch("drivebc:areas", c.CACHE_TTL_AREAS, fetch)


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    # Seen live with a -07:00 offset; a naive value is read as UTC so sorting never mixes kinds.
    return parsed.replace(tzinfo=UTC) if parsed and parsed.tzinfo is None else parsed


def _first_point(geography: dict[str, Any]) -> tuple[float | None, float | None]:
    coords: Any = geography.get("coordinates")
    # Point: [lon, lat]; LineString: [[lon, lat], ...]; deeper for Multi*.
    while isinstance(coords, list) and coords and isinstance(coords[0], list):
        coords = coords[0]
    if isinstance(coords, list) and len(coords) >= 2:
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            return None, None
    return None, None


def _record(raw: dict[str, Any]) -> RoadEvent:
    geography = raw.get("geography") or {}
    latitude, longitude = _first_point(geography)
    return RoadEvent(
        event_id=str(raw.get("id", "")),
        headline=raw.get("headline") or None,
        event_type=str(raw.get("event_type") or ""),
        subtypes=[str(s) for s in list_or_empty(raw, "event_subtypes")],
        severity=raw.get("severity") or None,
        status=raw.get("status") or None,
        description=raw.get("description") or None,
        roads=[
            EventRoad(
                name=r.get("name") or None,
                from_point=r.get("from") or None,
                to_point=r.get("to") or None,
                direction=r.get("direction") or None,
                state=r.get("state") or None,
            )
            for r in list_or_empty(raw, "roads")
        ],
        areas=[
            EventArea(area_id=str(a.get("id", "")), name=str(a.get("name", "")))
            for a in list_or_empty(raw, "areas")
        ],
        created=_time(raw.get("created")),
        updated=_time(raw.get("updated")),
        schedule=[str(i) for i in list_or_empty(raw.get("schedule") or {}, "intervals")],
        geometry_type=geography.get("type"),
        latitude=latitude,
        longitude=longitude,
        url=str(raw.get("url") or f"{c.EVENTS_URL}/{raw.get('id', '')}"),
    )


def _provenance(schema: str, cached: bool, coverage: str | None = None) -> Provenance:
    return make_provenance(
        source=c.SOURCE,
        url=f"{c.EVENTS_URL}?format=json&status=ACTIVE&limit={c.PAGE_SIZE}",
        cached=cached,
        schema_name=schema,
        freshness=_FRESHNESS,
        coverage=coverage,
        limits=(
            "Active events on provincial highways managed by the BC government; municipal "
            "streets are not covered. Text is English only."
        ),
        licence=c.LICENCE,
    )


def _upper(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is None or not value.strip():
        return None
    wanted = value.strip().upper().replace(" ", "_")
    if wanted not in allowed:
        raise InvalidInput(f"{name} must be one of {', '.join(allowed)}; got '{value}'.")
    return wanted


def _bbox(bbox: list[float] | None) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if len(bbox) != 4:
        raise InvalidInput("bbox is [min_lon, min_lat, max_lon, max_lat].")
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (min_lon < max_lon and min_lat < max_lat):
        raise InvalidInput(f"bbox must have min < max on both axes, got {bbox}.")
    return min_lon, min_lat, max_lon, max_lat


def _points(geography: dict[str, Any]) -> list[tuple[float, float]]:
    coords: Any = geography.get("coordinates")
    if geography.get("type") == "Point":
        coords = [coords]
    points: list[tuple[float, float]] = []
    for pair in coords or []:
        if isinstance(pair, list) and len(pair) >= 2:
            try:
                points.append((float(pair[0]), float(pair[1])))
            except (TypeError, ValueError):
                continue
    return points


def _road_matches(raw: dict[str, Any], road: str) -> bool:
    """'Highway 1', 'hwy 1', '1' all match Highway 1 but not Highway 16."""
    wanted = road.strip().casefold()
    for prefix in ("highway ", "hwy ", "hwy"):
        wanted = wanted.removeprefix(prefix)
    for r in list_or_empty(raw, "roads"):
        name = str(r.get("name") or "").casefold()
        if (
            name == wanted
            or name == f"highway {wanted}"
            or (not wanted.isdigit() and wanted in name)
        ):
            return True
    return False


def _area_matches(raw: dict[str, Any], area: str) -> bool:
    wanted = area.strip().casefold()
    for a in list_or_empty(raw, "areas"):
        area_id = str(a.get("id", "")).casefold()
        name = str(a.get("name", "")).casefold()
        if wanted in (area_id, area_id.removeprefix("drivebc.ca/")) or wanted in name:
            return True
    return False


def _filter(
    events: list[dict[str, Any]],
    *,
    event_type: str | None,
    severity: str | None,
    subtype: str | None,
    area: str | None,
    road: str | None,
    bbox: list[float] | None,
    query: str | None,
) -> list[dict[str, Any]]:
    kind = _upper(event_type, c.EVENT_TYPES, "event_type")
    level = _upper(severity, c.SEVERITIES, "severity")
    box = _bbox(bbox)
    sub = subtype.strip().upper().replace(" ", "_") if subtype and subtype.strip() else None
    needle = query.strip().casefold() if query and query.strip() else None
    kept = []
    for raw in events:
        if kind and raw.get("event_type") != kind:
            continue
        if level and raw.get("severity") != level:
            continue
        if sub and sub not in list_or_empty(raw, "event_subtypes"):
            continue
        if area and not _area_matches(raw, area):
            continue
        if road and not _road_matches(raw, road):
            continue
        if box and not any(
            box[0] <= lon <= box[2] and box[1] <= lat <= box[3]
            for lon, lat in _points(raw.get("geography") or {})
        ):
            continue
        if needle and needle not in str(raw.get("description") or "").casefold():
            continue
        kept.append(raw)
    return kept


def _sort(events: list[dict[str, Any]]) -> None:
    """MAJOR first, then most recently updated (two stable sorts)."""
    events.sort(
        key=lambda raw: _time(raw.get("updated")) or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    events.sort(key=lambda raw: raw.get("severity") != "MAJOR")


async def search_events(
    *,
    event_type: str | None = None,
    severity: str | None = None,
    subtype: str | None = None,
    area: str | None = None,
    road: str | None = None,
    bbox: list[float] | None = None,
    query: str | None = None,
    limit: int = c.LIMIT_DEFAULT,
) -> EventSearch:
    """Active events matching every filter given, MAJOR first, newest first."""
    if not 1 <= limit <= c.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {c.LIMIT_MAX}, got {limit}.")
    filters = {
        "event_type": event_type,
        "severity": severity,
        "subtype": subtype,
        "area": area,
        "road": road,
        "bbox": bbox,
        "query": query,
    }
    _filter([], **filters)  # bad arguments fail before any request
    events, cached = await _events()
    kept = _filter(events, **filters)
    _sort(kept)
    return EventSearch(
        total_active=len(events),
        total_matches=len(kept),
        events=[_record(raw) for raw in kept[:limit]],
        provenance=_provenance(
            "drivebc.EventSearch",
            cached,
            f"{len(kept)} of {len(events)} active events match; showing {min(limit, len(kept))}.",
        ),
    )


async def get_event(event_id: str) -> EventDetail:
    """One active event with its full GeoJSON geometry."""
    wanted = event_id.strip()
    if not wanted:
        raise InvalidInput("event_id must not be empty (e.g. 'drivebc.ca/RIDE-102765').")
    events, cached = await _events()
    for raw in events:
        ident = str(raw.get("id", ""))
        if wanted in (ident, ident.removeprefix("drivebc.ca/")):
            km = raw.get("+linear_reference_km")
            return EventDetail(
                event=_record(raw),
                geometry=raw.get("geography") or {},
                linear_reference_km=float(km) if isinstance(km, int | float) else None,
                provenance=_provenance("drivebc.EventDetail", cached),
            )
    raise NotFound(
        f"No active DriveBC event '{event_id}'. It may have ended; use drivebc_search_events."
    )


def _group_values(raw: dict[str, Any], group_by: str) -> list[str]:
    if group_by == "event_type":
        return [str(raw.get("event_type") or "unknown")]
    if group_by == "severity":
        return [str(raw.get("severity") or "unknown")]
    if group_by == "subtype":
        return [str(s) for s in list_or_empty(raw, "event_subtypes")] or ["none"]
    if group_by == "area":
        return [str(a.get("name") or a.get("id")) for a in list_or_empty(raw, "areas")] or ["none"]
    return [str(r.get("name") or "unnamed") for r in list_or_empty(raw, "roads")] or ["none"]


async def summarize_events(
    group_by: str = "area",
    *,
    event_type: str | None = None,
    severity: str | None = None,
    area: str | None = None,
    road: str | None = None,
) -> EventSummary:
    """Counts of active events by one field, after the same filters as the search."""
    if group_by not in c.GROUP_FIELDS:
        raise InvalidInput(f"group_by must be one of {', '.join(c.GROUP_FIELDS)}.")
    _filter(
        [],
        event_type=event_type,
        severity=severity,
        subtype=None,
        area=area,
        road=road,
        bbox=None,
        query=None,
    )
    events, cached = await _events()
    kept = _filter(
        events,
        event_type=event_type,
        severity=severity,
        subtype=None,
        area=area,
        road=road,
        bbox=None,
        query=None,
    )
    totals: Counter[str] = Counter()
    major: Counter[str] = Counter()
    for raw in kept:
        for value in _group_values(raw, group_by):
            totals[value] += 1
            major[value] += raw.get("severity") == "MAJOR"
    return EventSummary(
        group_by=group_by,
        total_matches=len(kept),
        groups=[
            EventCount(value=value, events=count, major=major[value])
            for value, count in totals.most_common()
        ],
        provenance=_provenance("drivebc.EventSummary", cached),
    )


async def list_areas() -> AreaList:
    """The 11 Ministry districts, with the number of active events in each."""
    areas, areas_cached = await _areas()
    events, events_cached = await _events()
    counts: Counter[str] = Counter(
        str(a.get("id", "")) for raw in events for a in list_or_empty(raw, "areas")
    )
    return AreaList(
        areas=[
            Area(
                area_id=str(a.get("id", "")),
                name=str(a.get("name", "")),
                geonames_url=a.get("url") or None,
                active_events=counts[str(a.get("id", ""))],
            )
            for a in areas
        ],
        provenance=make_provenance(
            source=c.SOURCE,
            url=f"{c.AREAS_URL}?format=json",
            cached=areas_cached and events_cached,
            schema_name="drivebc.AreaList",
            freshness="Districts are static; event counts are live (cached three minutes).",
            licence=c.LICENCE,
        ),
    )
