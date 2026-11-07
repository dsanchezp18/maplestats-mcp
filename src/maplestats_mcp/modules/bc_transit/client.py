"""Client for BC Transit GTFS-Realtime feeds. See the module docstring for
the feed shapes confirmed live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from maplestats_mcp.modules.bc_transit import constants
from maplestats_mcp.modules.bc_transit.schemas import (
    AlertPeriod,
    ServiceAlert,
    ServiceAlerts,
    StopTimePrediction,
    StopTimePredictions,
    VehiclePosition,
    VehiclePositions,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_FRESHNESS = "real-time; BC Transit regenerates each feed every few seconds"
_FRESHNESS_FR = "temps réel ; BC Transit régénère chaque flux toutes les quelques secondes"
_CANCELED = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Value("CANCELED")


def resolve_system(system: str, lang: str = "en") -> tuple[str, str, int]:
    """Return (key, name, operator id); 'victoria' and 'bct_victoria' both work."""
    key = system.strip().lower().replace(" ", "_").replace("-", "_")
    if not key.startswith("bct_"):
        key = f"bct_{key}"
    if key not in constants.SYSTEMS:
        known = ", ".join(constants.SYSTEMS)
        raise_localized(
            InvalidInput,
            f"Unknown BC Transit system {system!r}. Known: {known}.",
            f"Réseau BC Transit inconnu : {system!r}. Réseaux connus : {known}.",
            lang,
        )
    name, operator_id = constants.SYSTEMS[key]
    return key, name, operator_id


async def _fetch_feed(
    feed: str, operator_id: int, ttl: int, *, lang: str = "en"
) -> tuple[Any, bool]:
    url = constants.feed_url(feed, operator_id)
    label = f"bc_transit:{feed}:{operator_id}"

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise_localized(
                UpstreamError,
                f"{label} returned HTTP {status}.",
                f"{label} a renvoyé le code HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"{label} did not respond in time.",
                f"{label} n'a pas répondu à temps.",
                lang,
            )
        message = gtfs_realtime_pb2.FeedMessage()
        try:
            message.ParseFromString(response.content)
        except DecodeError:
            raise_localized(
                UpstreamError,
                f"{label} did not return a valid GTFS-RT feed.",
                f"{label} n'a pas renvoyé un flux GTFS-RT valide.",
                lang,
            )
        return message

    return await cached_fetch(label, ttl, fetch)


def _epoch(value: int) -> datetime | None:
    # Protobuf reports an unset uint64 as 0, not None.
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _check_limit(limit: int, lang: str = "en") -> None:
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}; reçu {limit}.",
            lang,
        )


def short_name(route_id: str) -> str:
    """'55-VIC' -> '55'. The suffix names the system (checked live 2026-11-07)."""
    return route_id.rsplit("-", 1)[0] if "-" in route_id else route_id


def route_matches(feed_route: str, wanted: str) -> bool:
    """A route asked as '55' matches '55-VIC'; '55-VIC' must match exactly."""
    feed_route, wanted = feed_route.upper(), wanted.strip().upper()
    if "-" in wanted:
        return feed_route == wanted
    return short_name(feed_route) == wanted


def _provenance(
    feed: str,
    operator_id: int,
    was_cached: bool,
    schema_name: str,
    as_of: datetime | None,
    lang: str = "en",
    limits: str | None = None,
):
    return make_provenance(
        source=constants.SOURCE,
        url=constants.feed_url(feed, operator_id),
        cached=was_cached,
        schema_name=schema_name,
        as_of=as_of,
        freshness=pick(lang, _FRESHNESS, _FRESHNESS_FR),
        limits=limits,
        lang=lang,
    )


def _text(translated: Any) -> str | None:
    for translation in translated.translation:
        if translation.text:
            return translation.text.replace("\r\n", "\n")
    return None


def _enum(enum: Any, message: Any, field: str) -> str | None:
    return enum.Name(getattr(message, field)) if message.HasField(field) else None


async def get_vehicle_positions(
    system: str,
    route_id: str | None = None,
    *,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> VehiclePositions:
    """Live positions of one BC Transit system's buses, optionally for one route."""
    _check_limit(limit, lang)
    key, name, operator_id = resolve_system(system, lang)
    message, was_cached = await _fetch_feed(
        "vehicles", operator_id, constants.CACHE_TTL_REALTIME_SECONDS, lang=lang
    )
    vehicles: list[VehiclePosition] = []
    rt = gtfs_realtime_pb2
    for entity in message.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        trip = vehicle.trip
        if route_id and not route_matches(trip.route_id, route_id):
            continue
        position = vehicle.position if vehicle.HasField("position") else None
        vehicles.append(
            VehiclePosition(
                vehicle_id=vehicle.vehicle.id or vehicle.vehicle.label or None,
                route_id=trip.route_id or None,
                route_short_name=short_name(trip.route_id) if trip.route_id else None,
                trip_id=trip.trip_id or None,
                # Unset means SCHEDULED in the GTFS-RT spec.
                trip_status=rt.TripDescriptor.ScheduleRelationship.Name(trip.schedule_relationship),
                direction_id=trip.direction_id if trip.HasField("direction_id") else None,
                start_date=trip.start_date or None,
                start_time=trip.start_time or None,
                latitude=position.latitude if position else None,
                longitude=position.longitude if position else None,
                bearing=position.bearing if position and position.HasField("bearing") else None,
                # GTFS-RT speed is metres per second.
                speed_kmh=round(position.speed * 3.6, 1)
                if position and position.HasField("speed")
                else None,
                stop_id=vehicle.stop_id or None,
                current_stop_sequence=vehicle.current_stop_sequence
                if vehicle.HasField("current_stop_sequence")
                else None,
                current_status=_enum(
                    rt.VehiclePosition.VehicleStopStatus, vehicle, "current_status"
                ),
                occupancy_status=_enum(
                    rt.VehiclePosition.OccupancyStatus, vehicle, "occupancy_status"
                ),
                congestion_level=_enum(
                    rt.VehiclePosition.CongestionLevel, vehicle, "congestion_level"
                ),
                timestamp=_epoch(vehicle.timestamp),
            )
        )
    feed_time = _epoch(message.header.timestamp)
    return VehiclePositions(
        system=key,
        system_name=name,
        feed_timestamp=feed_time,
        total_matches=len(vehicles),
        vehicles=vehicles[:limit],
        provenance=_provenance(
            "vehicles", operator_id, was_cached, "bc_transit.VehiclePositions", feed_time, lang
        ),
    )


async def get_stop_predictions(
    system: str,
    stop_id: str | None = None,
    route_id: str | None = None,
    *,
    include_past: bool = False,
    include_cancelled: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> StopTimePredictions:
    """Predicted departure (or final arrival) times and delays, soonest first."""
    _check_limit(limit, lang)
    if not stop_id and not route_id:
        raise_localized(
            InvalidInput,
            "Pass stop_id, route_id, or both -- Victoria's feed alone has ~14,000 stop updates.",
            "indiquez stop_id, route_id ou les deux ; le flux de Victoria compte à lui seul "
            "environ 14 000 passages.",
            lang,
        )
    key, name, operator_id = resolve_system(system, lang)
    message, was_cached = await _fetch_feed(
        "trip_updates", operator_id, constants.CACHE_TTL_REALTIME_SECONDS, lang=lang
    )
    rt = gtfs_realtime_pb2
    predictions: list[StopTimePrediction] = []
    for entity in message.entity:
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        trip = update.trip
        if route_id and not route_matches(trip.route_id, route_id):
            continue
        cancelled = trip.schedule_relationship == _CANCELED
        if cancelled and not include_cancelled:
            continue
        trip_status = rt.TripDescriptor.ScheduleRelationship.Name(trip.schedule_relationship)
        for stop_update in update.stop_time_update:
            if stop_id and stop_update.stop_id != stop_id.strip():
                continue
            # Prefer departure; the last stop of a trip only has arrival.
            if stop_update.HasField("departure"):
                event, times = "departure", stop_update.departure
            elif stop_update.HasField("arrival"):
                event, times = "arrival", stop_update.arrival
            else:
                continue
            predictions.append(
                StopTimePrediction(
                    route_id=trip.route_id or None,
                    route_short_name=short_name(trip.route_id) if trip.route_id else None,
                    trip_id=trip.trip_id or None,
                    trip_status=trip_status,
                    start_date=trip.start_date or None,
                    stop_id=stop_update.stop_id or None,
                    stop_sequence=stop_update.stop_sequence
                    if stop_update.HasField("stop_sequence")
                    else None,
                    stop_status=rt.TripUpdate.StopTimeUpdate.ScheduleRelationship.Name(
                        stop_update.schedule_relationship
                    ),
                    event=event,
                    predicted_time=_epoch(times.time),
                    delay_seconds=times.delay if times.HasField("delay") else None,
                    uncertainty_seconds=times.uncertainty
                    if times.HasField("uncertainty")
                    else None,
                )
            )
    feed_time = _epoch(message.header.timestamp)
    # Trips keep stops already served, so "next bus" drops times before the feed.
    if not include_past and feed_time:
        predictions = [
            p for p in predictions if p.predicted_time is None or p.predicted_time >= feed_time
        ]
    far_future = datetime.max.replace(tzinfo=UTC)
    predictions.sort(key=lambda p: p.predicted_time or far_future)
    return StopTimePredictions(
        system=key,
        system_name=name,
        feed_timestamp=feed_time,
        total_matches=len(predictions),
        cancelled_trips=len({p.trip_id for p in predictions if p.trip_status == "CANCELED"}),
        predictions=predictions[:limit],
        provenance=_provenance(
            "trip_updates",
            operator_id,
            was_cached,
            "bc_transit.StopTimePredictions",
            feed_time,
            lang,
        ),
    )


async def get_service_alerts(
    system: str,
    route_id: str | None = None,
    stop_id: str | None = None,
    *,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> ServiceAlerts:
    """Current service alerts (detours, stop closures) for one system."""
    _check_limit(limit, lang)
    key, name, operator_id = resolve_system(system, lang)
    message, was_cached = await _fetch_feed(
        "alerts", operator_id, constants.CACHE_TTL_ALERTS_SECONDS, lang=lang
    )
    rt = gtfs_realtime_pb2
    alerts: list[ServiceAlert] = []
    for entity in message.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        route_ids = sorted({e.route_id for e in alert.informed_entity if e.route_id})
        stop_ids = sorted({e.stop_id for e in alert.informed_entity if e.stop_id})
        if route_id and not any(route_matches(r, route_id) for r in route_ids):
            continue
        if stop_id and stop_id.strip() not in stop_ids:
            continue
        periods = [
            AlertPeriod(start=_epoch(p.start), end=_epoch(p.end)) for p in alert.active_period
        ]
        starts = [p.start for p in periods if p.start]
        ends = [p.end for p in periods if p.end]
        open_start = not periods or len(starts) < len(periods)
        open_end = not periods or len(ends) < len(periods)
        alerts.append(
            ServiceAlert(
                alert_id=entity.id,
                header=_text(alert.header_text),
                description=_text(alert.description_text),
                cause=rt.Alert.Cause.Name(alert.cause),
                effect=rt.Alert.Effect.Name(alert.effect),
                severity=rt.Alert.SeverityLevel.Name(alert.severity_level),
                route_ids=route_ids,
                route_short_names=sorted({short_name(r) for r in route_ids}),
                stop_ids=stop_ids,
                active_from=None if open_start else min(starts),
                active_until=None if open_end else max(ends),
                active_periods=periods,
            )
        )
    feed_time = _epoch(message.header.timestamp)
    return ServiceAlerts(
        system=key,
        system_name=name,
        feed_timestamp=feed_time,
        total_matches=len(alerts),
        alerts=alerts[:limit],
        provenance=_provenance(
            "alerts",
            operator_id,
            was_cached,
            "bc_transit.ServiceAlerts",
            feed_time,
            lang,
            limits=pick(
                lang,
                "",
                "Le texte des avis vient de BC Transit, en anglais seulement.",
            )
            or None,
        ),
    )
