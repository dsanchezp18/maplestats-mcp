"""Tests for bc_transit/client.py using protobuf payloads shaped like the
live feeds of 2026-11-07 (see the module docstring): suffixed route ids,
cancelled trips with SKIPPED stops, generic alert headers.
"""

from __future__ import annotations

import re

import pytest
from google.transit import gtfs_realtime_pb2

from maplestats_mcp.modules.bc_transit import client, constants
from maplestats_mcp.modules.transit import constants as transit_constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

VICTORIA = 48
rt = gtfs_realtime_pb2


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _url(feed: str, operator_id: int = VICTORIA) -> str:
    return constants.feed_url(feed, operator_id)


def _feed() -> rt.FeedMessage:
    message = rt.FeedMessage()
    message.header.gtfs_realtime_version = "1.0"
    message.header.timestamp = 1794087845
    return message


def _vehicles_payload() -> bytes:
    message = _feed()
    for index, route in enumerate(("55-VIC", "95-VIC", "15-VIC")):
        vehicle = message.entity.add(id=str(index)).vehicle
        vehicle.trip.route_id = route
        vehicle.trip.trip_id = f"1176477{index}:1:2"
        vehicle.trip.start_date = "20261107"
        vehicle.trip.direction_id = 0
        vehicle.position.latitude = 48.4377556
        vehicle.position.longitude = -123.502106
        vehicle.position.speed = 13.33
        vehicle.current_status = rt.VehiclePosition.IN_TRANSIT_TO
        vehicle.occupancy_status = rt.VehiclePosition.MANY_SEATS_AVAILABLE
        vehicle.stop_id = "101567"
        vehicle.vehicle.id = "3131354234"
        vehicle.timestamp = 1794087844
    return message.SerializeToString()


def _trip_updates_payload() -> bytes:
    message = _feed()
    running = message.entity.add(id="0").trip_update
    running.trip.route_id = "72-VIC"
    running.trip.trip_id = "running"
    served = running.stop_time_update.add(stop_sequence=1, stop_id="100029")
    served.departure.time = 1794087000
    next_stop = running.stop_time_update.add(stop_sequence=2, stop_id="100012")
    next_stop.departure.time = 1794091800
    next_stop.departure.delay = 120
    next_stop.departure.uncertainty = 30
    last = running.stop_time_update.add(stop_sequence=3, stop_id="100010")
    last.arrival.time = 1794091920
    cancelled = message.entity.add(id="1").trip_update
    cancelled.trip.route_id = "72-VIC"
    cancelled.trip.trip_id = "cancelled"
    cancelled.trip.schedule_relationship = rt.TripDescriptor.CANCELED
    skipped = cancelled.stop_time_update.add(stop_sequence=2, stop_id="100012")
    skipped.departure.time = 1794091700
    skipped.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SKIPPED
    other = message.entity.add(id="2").trip_update
    other.trip.route_id = "7-VIC"
    other.stop_time_update.add(stop_sequence=1, stop_id="100012").departure.time = 1794091600
    return message.SerializeToString()


def _alerts_payload() -> bytes:
    message = _feed()
    alert = message.entity.add(id="ft-TX1307670").alert
    alert.informed_entity.add(route_id="8-VIC", stop_id="100742")
    alert.informed_entity.add(route_id="8-VIC", stop_id="100769")
    alert.header_text.translation.add(text="DETOUR")
    alert.description_text.translation.add(text="Route 8 detour.\r\nRegular route after.")
    alert.effect = rt.Alert.DETOUR
    alert.active_period.add(start=1793363940)
    other = message.entity.add(id="ft-2").alert
    other.informed_entity.add(route_id="1-VIC", stop_id="100715")
    other.header_text.translation.add(text="DETOUR")
    return message.SerializeToString()


def test_systems_match_the_static_transit_agencies():
    for key, (_, operator_id) in constants.SYSTEMS.items():
        feed = transit_constants.AGENCIES[key].feed_url
        assert re.search(rf"operatorIds={operator_id}$", feed), key


def test_route_matching():
    assert client.route_matches("55-VIC", "55")
    assert client.route_matches("55-VIC", "55-vic")
    assert not client.route_matches("55-VIC", "5")
    assert not client.route_matches("55-VIC", "55-KEL")
    assert client.short_name("55-VIC") == "55"


def test_unknown_system_raises():
    with pytest.raises(InvalidInput, match="bct_victoria"):
        client.resolve_system("vancouver")
    assert client.resolve_system("Prince George")[2] == 22


async def test_vehicle_positions_route_filter_and_fields(httpx_mock):
    httpx_mock.add_response(url=_url("vehicles"), content=_vehicles_payload())
    result = await client.get_vehicle_positions("victoria", "55")
    assert result.system == "bct_victoria" and result.total_matches == 1
    vehicle = result.vehicles[0]
    assert vehicle.route_id == "55-VIC" and vehicle.route_short_name == "55"
    assert vehicle.speed_kmh == 48.0
    assert vehicle.occupancy_status == "MANY_SEATS_AVAILABLE"
    assert vehicle.current_status == "IN_TRANSIT_TO"
    assert vehicle.trip_status == "SCHEDULED"
    assert "BC Transit" in (result.provenance.licence or "")


async def test_stop_predictions_flag_cancelled_and_drop_served(httpx_mock):
    httpx_mock.add_response(url=_url("trip_updates"), content=_trip_updates_payload())
    result = await client.get_stop_predictions("bct_victoria", route_id="72")
    assert [p.trip_id for p in result.predictions] == ["cancelled", "running", "running"]
    assert result.cancelled_trips == 1
    first = result.predictions[0]
    assert first.trip_status == "CANCELED" and first.stop_status == "SKIPPED"
    assert result.predictions[1].delay_seconds == 120
    assert result.predictions[1].uncertainty_seconds == 30
    assert result.predictions[2].event == "arrival"


async def test_stop_predictions_can_drop_cancelled(httpx_mock):
    httpx_mock.add_response(url=_url("trip_updates"), content=_trip_updates_payload())
    result = await client.get_stop_predictions(
        "victoria", stop_id="100012", include_cancelled=False
    )
    assert [p.route_short_name for p in result.predictions] == ["7", "72"]
    assert result.cancelled_trips == 0


async def test_stop_predictions_requires_a_filter():
    with pytest.raises(InvalidInput):
        await client.get_stop_predictions("victoria")


async def test_alerts_filters_and_text(httpx_mock):
    httpx_mock.add_response(url=_url("alerts"), content=_alerts_payload(), is_reusable=True)
    result = await client.get_service_alerts("victoria", route_id="8")
    [alert] = result.alerts
    assert alert.route_short_names == ["8"]
    assert alert.description == "Route 8 detour.\nRegular route after."
    assert alert.active_from is not None and alert.active_until is None
    by_stop = await client.get_service_alerts("victoria", stop_id="100715")
    assert [a.alert_id for a in by_stop.alerts] == ["ft-2"]


async def test_other_system_uses_its_operator_id(httpx_mock):
    httpx_mock.add_response(url=_url("alerts", 47), content=_alerts_payload())
    result = await client.get_service_alerts("kelowna")
    assert result.system_name == "Kelowna" and result.total_matches == 2
    assert result.provenance.url.endswith("operatorIds=47")


async def test_garbage_payload_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_url("alerts"), content=b"<html>maintenance</html>")
    with pytest.raises(UpstreamError):
        await client.get_service_alerts("victoria")


async def test_french_errors_and_provenance(httpx_mock):
    with pytest.raises(InvalidInput, match="Réseau BC Transit inconnu"):
        await client.get_service_alerts("surrey", lang="fr")
    httpx_mock.add_response(url=_url("alerts"), content=_alerts_payload())
    result = await client.get_service_alerts("victoria", lang="fr")
    assert (result.provenance.freshness or "").startswith("temps réel")
    assert "en anglais seulement" in (result.provenance.limits or "")
    assert "Conditions d'utilisation" in (result.provenance.licence or "")


async def test_limit_out_of_range_raises():
    with pytest.raises(InvalidInput):
        await client.get_vehicle_positions("victoria", limit=0)
