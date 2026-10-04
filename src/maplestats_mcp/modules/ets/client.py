"""Client for Edmonton Transit Service GTFS-Realtime feeds. See the
module docstring for the feed shapes and ETS extensions confirmed live.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from maplestats_mcp.modules.ets import constants
from maplestats_mcp.modules.ets.schemas import (
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
_FRESHNESS = "real-time; ETS regenerates each feed about every 30 seconds"
_FRESHNESS_FR = "temps réel; ETS régénère chaque flux environ toutes les 30 secondes"


async def _fetch_feed(feed: str, ttl: int, *, lang: str = "en") -> tuple[Any, bool]:
    url = constants.FEEDS[feed]

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise_localized(
                UpstreamError,
                f"ets:{feed} returned HTTP {status}.",
                f"ets:{feed} a renvoyé le code HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"ets:{feed} did not respond in time.",
                f"ets:{feed} n'a pas répondu à temps.",
                lang,
            )
        message = gtfs_realtime_pb2.FeedMessage()
        try:
            message.ParseFromString(response.content)
        except DecodeError:
            raise_localized(
                UpstreamError,
                f"ets:{feed} did not return a valid GTFS-RT feed.",
                f"ets:{feed} n'a pas renvoyé un flux GTFS-RT valide.",
                lang,
            )
        return message

    return await cached_fetch(f"ets:{feed}", ttl, fetch)


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


def _provenance(
    feed: str,
    was_cached: bool,
    schema_name: str,
    as_of: datetime | None,
    lang: str = "en",
    limits: str | None = None,
):
    return make_provenance(
        source=constants.SOURCE,
        url=constants.FEEDS[feed],
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
            return translation.text
    return None


async def get_vehicle_positions(
    route_id: str | None = None,
    *,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> VehiclePositions:
    """Live positions of ETS vehicles, optionally for one route."""
    _check_limit(limit, lang)
    message, was_cached = await _fetch_feed(
        "vehicles", constants.CACHE_TTL_REALTIME_SECONDS, lang=lang
    )
    vehicles: list[VehiclePosition] = []
    for entity in message.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        if route_id and vehicle.trip.route_id != route_id:
            continue
        position = vehicle.position if vehicle.HasField("position") else None
        vehicles.append(
            VehiclePosition(
                vehicle_id=vehicle.vehicle.id or None,
                vehicle_label=vehicle.vehicle.label or None,
                route_id=vehicle.trip.route_id or None,
                trip_id=vehicle.trip.trip_id or None,
                direction_id=vehicle.trip.direction_id
                if vehicle.trip.HasField("direction_id")
                else None,
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
                timestamp=_epoch(vehicle.timestamp),
            )
        )
    feed_time = _epoch(message.header.timestamp)
    return VehiclePositions(
        feed_timestamp=feed_time,
        total_matches=len(vehicles),
        vehicles=vehicles[:limit],
        provenance=_provenance("vehicles", was_cached, "ets.VehiclePositions", feed_time, lang),
    )


async def get_stop_predictions(
    stop_id: str | None = None,
    route_id: str | None = None,
    *,
    include_past: bool = False,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> StopTimePredictions:
    """Predicted arrival/departure times and delays, soonest first."""
    _check_limit(limit, lang)
    if not stop_id and not route_id:
        raise_localized(
            InvalidInput,
            "Pass stop_id, route_id, or both -- the full feed is ~1,200 trips.",
            "indiquez stop_id, route_id ou les deux; le flux complet compte environ 1 200 trajets.",
            lang,
        )
    message, was_cached = await _fetch_feed(
        "trip_updates", constants.CACHE_TTL_REALTIME_SECONDS, lang=lang
    )
    predictions: list[StopTimePrediction] = []
    for entity in message.entity:
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        if route_id and update.trip.route_id != route_id:
            continue
        headsign = update.trip_properties.trip_headsign or None
        for stop_update in update.stop_time_update:
            if stop_id and stop_update.stop_id != stop_id:
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
                    route_id=update.trip.route_id or None,
                    trip_id=update.trip.trip_id or None,
                    headsign=headsign,
                    vehicle_label=update.vehicle.label or None,
                    stop_id=stop_update.stop_id or None,
                    stop_sequence=stop_update.stop_sequence
                    if stop_update.HasField("stop_sequence")
                    else None,
                    event=event,
                    predicted_time=_epoch(times.time),
                    scheduled_time=_epoch(times.scheduled_time),
                    delay_seconds=times.delay if times.HasField("delay") else None,
                )
            )
    feed_time = _epoch(message.header.timestamp)
    # Confirmed live: trips keep already-served stops in the feed, so
    # "next bus" answers must drop predictions before the feed time.
    if not include_past and feed_time:
        predictions = [
            p for p in predictions if p.predicted_time is None or p.predicted_time >= feed_time
        ]
    far_future = datetime.max.replace(tzinfo=UTC)
    predictions.sort(key=lambda p: p.predicted_time or far_future)
    return StopTimePredictions(
        feed_timestamp=feed_time,
        total_matches=len(predictions),
        predictions=predictions[:limit],
        provenance=_provenance(
            "trip_updates", was_cached, "ets.StopTimePredictions", feed_time, lang
        ),
    )


async def get_service_alerts(
    route_id: str | None = None,
    stop_id: str | None = None,
    *,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> ServiceAlerts:
    """Current ETS service alerts (detours, closures), optionally filtered."""
    _check_limit(limit, lang)
    message, was_cached = await _fetch_feed("alerts", constants.CACHE_TTL_ALERTS_SECONDS, lang=lang)
    alerts: list[ServiceAlert] = []
    for entity in message.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        route_ids = sorted({e.route_id for e in alert.informed_entity if e.route_id})
        stop_ids = sorted({e.stop_id for e in alert.informed_entity if e.stop_id})
        header = _text(alert.header_text)
        # A few alerts carry no informed_entity, only free text.
        if (
            route_id
            and route_id not in route_ids
            and (route_ids or not re.search(rf"\bRoute {re.escape(route_id)}\b", header or ""))
        ):
            continue
        if stop_id and stop_id not in stop_ids:
            continue
        period = alert.active_period[0] if alert.active_period else None
        alerts.append(
            ServiceAlert(
                alert_id=entity.id,
                header=header,
                description=_text(alert.description_text),
                cause=gtfs_realtime_pb2.Alert.Cause.Name(alert.cause),
                effect=gtfs_realtime_pb2.Alert.Effect.Name(alert.effect),
                severity=gtfs_realtime_pb2.Alert.SeverityLevel.Name(alert.severity_level),
                route_ids=route_ids,
                stop_ids=stop_ids,
                active_from=_epoch(period.start) if period else None,
                active_until=_epoch(period.end) if period else None,
            )
        )
    feed_time = _epoch(message.header.timestamp)
    return ServiceAlerts(
        feed_timestamp=feed_time,
        total_matches=len(alerts),
        alerts=alerts[:limit],
        provenance=_provenance(
            "alerts",
            was_cached,
            "ets.ServiceAlerts",
            feed_time,
            lang,
            # ETS writes its alert text in English only; say so to a French reader.
            limits=pick(
                lang,
                "",
                "Le texte des avis (titre et description) vient d'ETS, en anglais seulement.",
            )
            or None,
        ),
    )
