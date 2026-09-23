"""Tests for ets/client.py using protobuf payloads shaped like the live
ETS feeds (see the module docstring), including the ETS-specific
`scheduled_time` and `trip_properties.trip_headsign` extensions.
"""

from __future__ import annotations

import pytest
from google.transit import gtfs_realtime_pb2

from maple_data_mcp.modules.ets import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _feed() -> gtfs_realtime_pb2.FeedMessage:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1790131990
    return message


def _vehicles_payload() -> bytes:
    message = _feed()
    for vehicle_id, route in (("4311", "922"), ("4400", "4")):
        entity = message.entity.add(id=vehicle_id)
        entity.vehicle.trip.route_id = route
        entity.vehicle.trip.trip_id = f"trip-{route}"
        entity.vehicle.position.latitude = 53.528
        entity.vehicle.position.longitude = -113.677
        entity.vehicle.position.speed = 10.0
        entity.vehicle.vehicle.label = vehicle_id
        entity.vehicle.timestamp = 1790131978
    return message.SerializeToString()


def _trip_updates_payload() -> bytes:
    message = _feed()
    entity = message.entity.add(id="32757996")
    update = entity.trip_update
    update.trip.route_id = "922"
    update.trip.trip_id = "32757996"
    update.trip_properties.trip_headsign = "922 Rosenthal"
    update.vehicle.label = "4311"
    later = update.stop_time_update.add(stop_sequence=3, stop_id="8540")
    later.departure.time = 1790131907
    later.departure.delay = -13
    later.departure.scheduled_time = 1790131920
    sooner = update.stop_time_update.add(stop_sequence=2, stop_id="8536")
    sooner.departure.time = 1790131872
    sooner.departure.delay = 12
    last = update.stop_time_update.add(stop_sequence=18, stop_id="8929")
    last.arrival.time = 1790132578
    last.arrival.delay = -62
    return message.SerializeToString()


def _alerts_payload() -> bytes:
    message = _feed()
    tagged = message.entity.add(id="1")
    tagged.alert.informed_entity.add(route_id="523", stop_id="1321")
    tagged.alert.header_text.translation.add(text="Stop 1321 closed", language="en")
    tagged.alert.effect = gtfs_realtime_pb2.Alert.Effect.DETOUR
    text_only = message.entity.add(id="2")
    text_only.alert.header_text.translation.add(text="Planned Detour for Route 124", language="en")
    text_only.alert.active_period.add(start=1777201200, end=1793509200)
    return message.SerializeToString()


async def test_vehicle_positions_filter_and_speed(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["vehicles"], content=_vehicles_payload())
    result = await client.get_vehicle_positions("922")
    assert result.total_matches == 1
    vehicle = result.vehicles[0]
    assert vehicle.vehicle_label == "4311"
    assert vehicle.speed_kmh == 36.0
    assert result.feed_timestamp is not None


async def test_stop_predictions_sorted_and_arrival_fallback(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["trip_updates"], content=_trip_updates_payload())
    result = await client.get_stop_predictions(route_id="922", include_past=True)
    assert [p.stop_id for p in result.predictions] == ["8536", "8540", "8929"]
    assert result.predictions[0].headsign == "922 Rosenthal"
    assert result.predictions[1].scheduled_time is not None
    assert result.predictions[2].event == "arrival"
    assert result.predictions[2].delay_seconds == -62


async def test_stop_predictions_requires_a_filter():
    with pytest.raises(InvalidInput):
        await client.get_stop_predictions()


async def test_alerts_route_filter_uses_entities_then_text(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["alerts"], content=_alerts_payload())
    tagged = await client.get_service_alerts(route_id="523")
    assert [a.alert_id for a in tagged.alerts] == ["1"]
    assert tagged.alerts[0].effect == "DETOUR"
    text_only = await client.get_service_alerts(route_id="124")
    assert [a.alert_id for a in text_only.alerts] == ["2"]
    assert text_only.alerts[0].active_until is not None


async def test_garbage_payload_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["alerts"], content=b"<html>maintenance</html>")
    with pytest.raises(UpstreamError):
        await client.get_service_alerts()


async def test_limit_out_of_range_raises():
    with pytest.raises(InvalidInput):
        await client.get_vehicle_positions(limit=0)


async def test_stop_predictions_drop_served_stops_by_default(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["trip_updates"], content=_trip_updates_payload())
    result = await client.get_stop_predictions(route_id="922")
    # Only the final arrival (1790132578) is after the feed time (1790131990).
    assert [p.stop_id for p in result.predictions] == ["8929"]


async def test_alert_text_route_match_is_whole_number(httpx_mock):
    httpx_mock.add_response(url=constants.FEEDS["alerts"], content=_alerts_payload())
    result = await client.get_service_alerts(route_id="12")
    assert result.alerts == []
