"""transit/client.py against a small hand-built GTFS zip served by range.

The fixture feed has one bus route with two directions, a night trip that
runs past 24:00, a station with two platforms and a metro line, so the
service-day, station and exclusion rules are each exercised.
"""

from __future__ import annotations

import io
import re
import typing
import zipfile
from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.transit import client, constants, schemas
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

FILES = {
    "feed_info.txt": (
        "feed_publisher_name,feed_version,feed_start_date,feed_end_date\n"
        "Test Transit,v1,20261001,20261031\n"
    ),
    "agency.txt": "agency_id,agency_name\nA,Test Transit\n",
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type\n"
        "R1,10,Gare Centrale - Éléphant,3\n"
        "R2,M1,Metro Line,1\n"
    ),
    "stops.txt": (
        "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        "S1,,Central Station,51.0450,-114.0700,1,\n"
        "P1,,Central Station Platform A,51.0450,-114.0701,0,S1\n"
        "P2,,Central Station Platform B,51.0451,-114.0701,0,S1\n"
        "S3,777,Éléphant Park,51.1000,-114.1000,0,\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "WK,1,1,1,1,1,0,0,20261001,20261031\n"
        "WE,0,0,0,0,0,1,1,20261001,20261031\n"
    ),
    "calendar_dates.txt": "service_id,date,exception_type\nWK,20261012,2\n",
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id\n"
        "R1,WK,T1,Downtown,0\n"
        "R1,WK,T2,Downtown,0\n"
        "R1,WK,T3,Uptown,1\n"
        "R1,WE,T4,Downtown,0\n"
        "R1,WK,T5,Night,0\n"
        "R2,WK,T6,Metro,0\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,P1,1\n"
        "T1,08:10:00,08:10:00,S3,2\n"
        "T2,08:30:00,08:30:00,P2,1\n"
        "T2,08:40:00,08:40:00,S3,2\n"
        "T3,17:00:00,17:00:00,P1,1\n"
        "T3,17:10:00,17:10:00,S3,2\n"
        "T4,09:00:00,09:00:00,P1,1\n"
        "T5,25:10:00,25:10:00,P1,1\n"
        "T5,25:20:00,25:20:00,S3,2\n"
        "T6,08:05:00,08:05:00,P1,1\n"
    ),
}


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _serve(httpx_mock, agency: str, files: dict[str, str] | None = None) -> dict[str, bytes]:
    """Serve the zip at the agency's feed URL; `served["body"]` can be swapped."""
    served = {"body": _zip(files or FILES)}

    def respond(request: httpx.Request) -> httpx.Response:
        body = served["body"]
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={
                    "content-length": str(len(body)),
                    "last-modified": "Wed, 30 Sep 2026 14:00:00 GMT",
                },
            )
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    httpx_mock.add_callback(respond, url=constants.AGENCIES[agency].feed_url, is_reusable=True)
    return served


def test_agency_keys_match_the_schema_literal():
    assert set(constants.AGENCIES) == set(typing.get_args(schemas.AgencyKey))
    for agency in constants.AGENCIES.values():
        assert agency.licence
        assert agency.licence_url
        assert agency.attribution


async def test_list_agencies_reports_reachability(httpx_mock):
    _serve(httpx_mock, "calgary")
    for key, agency in constants.AGENCIES.items():
        if key != "calgary" and agency.range_requests:
            httpx_mock.add_response(url=agency.feed_url, status_code=404, is_reusable=True)
    result = await client.list_agencies(lang="fr")
    by_key = {a.key: a for a in result.agencies}
    assert by_key["calgary"].reachable is True
    assert by_key["calgary"].zip_bytes
    assert by_key["calgary"].last_modified
    assert by_key["oc_transpo"].reachable is False
    assert by_key["stm"].name.startswith("Société de transport")
    assert "métro" in (by_key["stm"].notes or "")


async def test_feed_info_counts_and_provenance(httpx_mock):
    _serve(httpx_mock, "calgary")
    info = await client.get_feed_info("calgary")
    assert (info.route_count, info.stop_count) == (2, 4)
    assert info.publisher_name == "Test Transit"
    assert info.feed_end_date == date(2026, 10, 31)
    assert info.agency_names == ["Test Transit"]
    assert {f.name for f in info.files} >= {"stop_times.txt", "trips.txt"}
    assert "Schedule valid 2026-10-01 to 2026-10-31" in (info.provenance.coverage or "")
    assert "Open Government Licence" in (info.provenance.licence or "")


async def test_unknown_agency_and_bad_limit_are_input_errors():
    with pytest.raises(InvalidInput, match="Unknown agency"):
        await client.search_routes("nowhere")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_routes("calgary", limit=0)


async def test_search_routes_folds_accents_and_filters_type(httpx_mock):
    _serve(httpx_mock, "calgary")
    by_name = await client.search_routes("calgary", "elephant")
    assert [r.route_id for r in by_name.routes] == ["R1"]
    by_number = await client.search_routes("calgary", "10")
    assert by_number.routes[0].route_type_name == "bus"
    metro = await client.search_routes("calgary", route_type=1)
    assert [r.route_id for r in metro.routes] == ["R2"]
    everything = await client.search_routes("calgary")
    assert everything.total_matches == 2


async def test_search_stops_by_name_code_and_distance(httpx_mock):
    _serve(httpx_mock, "calgary")
    by_name = await client.search_stops("calgary", "elephant")
    assert [s.stop_id for s in by_name.stops] == ["S3"]
    by_code = await client.search_stops("calgary", "777")
    assert by_code.stops[0].stop_id == "S3"
    near = await client.search_stops(
        "calgary", near_latitude=51.0450, near_longitude=-114.0700, radius_m=300
    )
    assert near.stops[0].stop_id == "S1"
    assert near.stops[0].distance_m == 0.0
    assert {s.stop_id for s in near.stops} == {"S1", "P1", "P2"}
    with pytest.raises(InvalidInput, match="query"):
        await client.search_stops("calgary")
    with pytest.raises(InvalidInput, match="together"):
        await client.search_stops("calgary", near_latitude=51.0)


async def test_departures_of_a_station_include_its_platforms(httpx_mock):
    _serve(httpx_mock, "calgary")
    result = await client.get_stop_departures(
        "calgary", "S1", service_date="2026-10-06", start_time="08:00"
    )
    assert result.stop_ids_included == ["P1", "P2", "S1"]
    assert [(d.trip_id, d.local_time) for d in result.departures] == [
        ("T1", "08:00:00"),
        ("T6", "08:05:00"),
        ("T2", "08:30:00"),
        ("T3", "17:00:00"),
        ("T5", "01:10:00"),
    ]
    night = result.departures[-1]
    assert night.departure_time == "25:10:00"
    assert night.after_midnight_of_previous_service_day is False
    assert result.total_matches == 5
    assert result.service_date == date(2026, 10, 6)


async def test_after_midnight_trips_of_the_previous_service_day(httpx_mock):
    _serve(httpx_mock, "calgary")
    result = await client.get_stop_departures(
        "calgary", "P1", service_date="2026-10-06", start_time="00:00", route="10"
    )
    assert [(d.trip_id, d.after_midnight_of_previous_service_day) for d in result.departures] == [
        ("T5", True),  # Monday's night trip, 01:10 on Tuesday
        ("T1", False),
        ("T3", False),
        ("T5", False),  # Tuesday's own night trip, after midnight into Wednesday
    ]
    assert result.departures[0].local_time == "01:10:00"


async def test_holiday_removes_the_weekday_service(httpx_mock):
    _serve(httpx_mock, "calgary")
    # 2026-10-12 removes WK; the weekend service T4 does not run on a Monday.
    holiday = await client.get_stop_departures(
        "calgary", "P1", service_date="2026-10-12", start_time="00:00"
    )
    assert holiday.departures == []
    sunday = await client.get_stop_departures(
        "calgary", "P1", service_date="2026-10-11", start_time="00:00"
    )
    assert [d.trip_id for d in sunday.departures] == ["T4"]


async def test_departures_errors(httpx_mock):
    _serve(httpx_mock, "calgary")
    with pytest.raises(InvalidInput, match="outside"):
        await client.get_stop_departures("calgary", "S1", service_date="2027-01-05")
    with pytest.raises(NotFound, match="no stop"):
        await client.get_stop_departures("calgary", "ZZ", service_date="2026-10-06")
    with pytest.raises(NotFound, match="no route"):
        await client.get_stop_departures("calgary", "S1", service_date="2026-10-06", route="999")


async def test_route_summary_counts_trips_and_headways(httpx_mock):
    _serve(httpx_mock, "calgary")
    summary = await client.get_route_summary("calgary", "10", service_date="2026-10-06")
    assert summary.trips_in_feed == 5
    assert summary.trips_on_date == 4  # T4 is the weekend service
    assert summary.distinct_stop_ids == 3  # P1, P2 and S3
    assert summary.distinct_stations == 2  # platforms P1 and P2 merge into S1
    assert summary.distinct_stop_names == 3
    by_direction = {d.direction_id: d for d in summary.directions}
    assert by_direction[0].trips == 3
    assert by_direction[0].first_departure == "08:00:00"
    assert by_direction[0].last_departure == "25:10:00"
    assert by_direction[1].headsigns == ["Uptown"]
    hourly = {(h.direction_id, h.hour): h for h in summary.hourly}
    assert hourly[(0, 8)].trips == 2
    assert hourly[(0, 8)].average_headway_minutes == 30.0
    assert hourly[(0, 25)].average_headway_minutes is None


async def test_route_summary_unknown_route(httpx_mock):
    _serve(httpx_mock, "calgary")
    with pytest.raises(NotFound, match="no route"):
        await client.get_route_summary("calgary", "nope", service_date="2026-10-06")


async def test_stm_metro_is_not_reported(httpx_mock):
    _serve(httpx_mock, "stm")
    routes = await client.search_routes("stm")
    assert [r.route_id for r in routes.routes] == ["R1"]
    with pytest.raises(NotFound, match="no route"):
        await client.get_route_summary("stm", "M1", service_date="2026-10-06")
    departures = await client.get_stop_departures(
        "stm", "S1", service_date="2026-10-06", start_time="08:00"
    )
    assert "T6" not in [d.trip_id for d in departures.departures]
    assert "métro" in (departures.provenance.limits or "")


async def test_replaced_zip_is_retried_with_a_fresh_directory(httpx_mock):
    served = _serve(httpx_mock, "calgary")
    assert (await client.search_routes("calgary")).total_matches == 2
    # The feed is replaced: a longer routes table moves every later offset,
    # so the cached directory now points into the wrong bytes.
    changed = dict(FILES)
    changed["routes.txt"] = FILES["routes.txt"] + "R3,11,Third,3\n"
    served["body"] = _zip(changed)
    stops = await client.search_stops("calgary", "elephant")
    assert [s.stop_id for s in stops.stops] == ["S3"]


async def test_missing_required_table_is_an_upstream_error(httpx_mock):
    _serve(httpx_mock, "calgary", {k: v for k, v in FILES.items() if k != "routes.txt"})
    with pytest.raises(UpstreamError, match="routes.txt"):
        await client.search_routes("calgary")


async def test_head_failures_fall_back_to_a_one_byte_range(httpx_mock):
    # An agency host answered HEAD with 502 while ranged GETs worked.
    body = _zip(FILES)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(502)
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(
            206,
            content=body[start : end + 1],
            headers={"content-range": f"bytes {start}-{end}/{len(body)}"},
        )

    httpx_mock.add_callback(
        respond, url=constants.AGENCIES["oc_transpo"].feed_url, is_reusable=True
    )
    info = await client.get_feed_info("oc_transpo")
    assert (info.route_count, info.stop_count) == (2, 4)
    assert info.agency.zip_bytes == len(body)


# -- feeds from hosts without byte ranges (BC Transit) --------------------


def _serve_whole(httpx_mock, agency: str, files: dict[str, str] | None = None) -> None:
    """Serve the zip the way BC Transit's host does: GET only, Range ignored."""
    body = _zip(files or FILES)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(405, headers={"allow": "GET"})
        return httpx.Response(
            200,
            content=body,
            headers={"last-modified": "Fri, 02 Oct 2026 20:15:04 GMT"},
        )

    httpx_mock.add_callback(respond, url=constants.AGENCIES[agency].feed_url, is_reusable=True)


def test_bc_transit_agencies_are_read_whole():
    bc = [a for k, a in constants.AGENCIES.items() if k.startswith("bct_")]
    assert len(bc) == 12
    assert all(not a.range_requests and a.province == "BC" for a in bc)
    assert all("operatorIds=" in a.feed_url for a in bc)
    assert len({a.feed_url for a in bc}) == 12
    assert all(a.range_requests for k, a in constants.AGENCIES.items() if not k.startswith("bct_"))


async def test_feed_without_range_support_is_read_from_a_whole_download(httpx_mock):
    _serve_whole(httpx_mock, "bct_victoria")
    info = await client.get_feed_info("bct_victoria")
    assert (info.route_count, info.stop_count) == (2, 4)
    assert info.agency.licence.startswith("BC Transit Open Data Terms")
    assert info.provenance.as_of is not None
    result = await client.get_stop_departures(
        "bct_victoria", "S1", service_date="2026-10-06", start_time="08:00"
    )
    assert [(d.trip_id, d.local_time) for d in result.departures] == [
        ("T1", "08:00:00"),
        ("T6", "08:05:00"),
        ("T2", "08:30:00"),
        ("T3", "17:00:00"),
        ("T5", "01:10:00"),
    ]
    summary = await client.get_route_summary("bct_victoria", "R1", service_date="2026-10-06")
    assert summary.trips_on_date == 4
    # One download served the tables and the stop_times scans alike.
    gets = [r for r in httpx_mock.get_requests() if r.method == "GET"]
    assert len(gets) == 1
    assert all("range" not in r.headers for r in gets)


async def test_listing_does_not_probe_hosts_that_build_the_zip_on_request(httpx_mock):
    for agency in constants.AGENCIES.values():
        if agency.range_requests:
            httpx_mock.add_response(url=agency.feed_url, status_code=404, is_reusable=True)
    result = await client.list_agencies()
    kelowna = next(a for a in result.agencies if a.key == "bct_kelowna")
    assert kelowna.reachable is None
    assert kelowna.zip_bytes is None
    assert not [r for r in httpx_mock.get_requests() if "tmix" in str(r.url)]


async def test_whole_download_over_the_limit_is_refused(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "WHOLE_MAX_BYTES", 100)
    _serve_whole(httpx_mock, "bct_victoria")
    with pytest.raises(UpstreamError, match="limit"):
        await client.get_feed_info("bct_victoria")
