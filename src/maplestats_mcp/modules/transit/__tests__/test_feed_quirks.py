"""Real-world GTFS quirks and feed-host failures, beyond the hand-built happy path.

The UP Express fixture below keeps the exact shape of the live feed, read by
byte range (no full download) on 2026-10-03 from
https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/UP-GTFS.zip
(898,079 bytes): every table starts with a UTF-8 BOM and uses CRLF line
endings, there is no calendar.txt (calendar_dates.txt alone defines service,
one service_id per date), tables carry optional extra columns, and each
trip's stop_times rows are written in descending stop_sequence order. Rows
are trimmed to one service day; the trips.txt rows follow the live column
order and headsigns, filled in for the trip ids seen in stop_times.txt.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.transit import client, constants, gtfs
from maplestats_mcp.shared.errors import UpstreamError

BOM = "﻿"


def _crlf(*lines: str) -> str:
    return BOM + "".join(f"{line}\r\n" for line in lines)


UP_EXPRESS = {
    "agency.txt": _crlf(
        "agency_id,agency_name,agency_url,agency_timezone,agency_lang,agency_phone,agency_fare_url",
        "UPExpress,UP Express,https://www.upexpress.com,America/Toronto,en,"
        "Local: 416-869-3300; 1-844-GET-ON-UP (438-6687),"
        "https://www.upexpress.com/ways-to-pay/up-express-fares",
    ),
    "routes.txt": _crlf(
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_color,"
        "route_text_color",
        "UP,UPExpress,UP,Union Pearson Express,2,0075D2,FFFFFF",
    ),
    "stops.txt": _crlf(
        "stop_id,stop_name,stop_lat,stop_lon,zone_id,stop_url,location_type,parent_station,"
        "wheelchair_boarding,stop_code",
        "WE,Weston GO/UP,43.70029,-79.51368,,https://www.upexpress.com/up-express-stations/"
        "weston-station,0,,1,",
        "UN,UP Express Union Station,43.644238,-79.383555,,https://www.upexpress.com/"
        "up-express-stations/union-station,0,,1,",
        "PA,UP Express Pearson Airport,43.682683,-79.612968,,https://www.upexpress.com/"
        "up-express-stations/pearson-station,0,,1,",
        "MD,Mount Dennis GO/UP,43.68749,-79.48703,,https://www.upexpress.com/"
        "up-express-stations/mountdennis-station,0,,1,",
        "BL,Bloor GO/UP,43.656928,-79.450192,,https://www.upexpress.com/"
        "up-express-stations/bloor-station,0,,1,",
    ),
    "feed_info.txt": _crlf(
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,"
        "feed_version",
        "Metrolinx,https://www.metrolinx.com,en,20260903,20270302,20260903104434",
    ),
    "calendar_dates.txt": _crlf(
        "service_id,date,exception_type",
        "20261011,20261011,1",
        "20261012,20261012,1",
    ),
    "trips.txt": _crlf(
        "route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id,"
        "wheelchair_accessible,bikes_allowed",
        "UP,20261012,20261012-4301,UP Express Pearson Airport,0,UP01,UNPA,1,2",
        "UP,20261011,20261011-4008,UP Express Union Station,1,UP02,PAUN,1,2",
        "UP,20261011,20261011-4109,UP Express Pearson Airport,0,UP02,UNPA,1,2",
        "UP,20261011,20261011-4110,UP Express Union Station,1,UP03,PAUN,1,2",
        "UP,20261011,20261011-4211,UP Express Pearson Airport,0,UP03,UNPA,1,2",
        "UP,20261011,20261011-4212,UP Express Union Station,1,UP04,PAUN,1,2",
    ),
    "stop_times.txt": _crlf(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type,"
        "shape_dist_traveled",
        "20261012-4301,05:23:00,05:23:00,PA,5,0,0,24365",
        "20261012-4301,05:11:00,05:11:00,WE,4,0,0,12927",
        "20261012-4301,05:07:00,05:07:00,MD,3,0,0,10877",
        "20261012-4301,05:03:00,05:03:00,BL,2,0,0,6183",
        "20261012-4301,04:55:00,04:55:00,UN,1,0,0,0",
        "20261011-4008,08:07:00,08:07:00,UN,5,0,0,24365",
        "20261011-4008,07:58:00,07:58:00,BL,4,0,0,18182",
        "20261011-4008,07:54:00,07:54:00,MD,3,0,0,15326",
        "20261011-4008,07:51:00,07:51:00,WE,2,0,0,11438",
        "20261011-4008,07:39:00,07:39:00,PA,1,0,0,0",
        "20261011-4109,08:43:00,08:43:00,PA,5,0,0,24365",
        "20261011-4109,08:31:00,08:31:00,WE,4,0,0,12927",
        "20261011-4109,08:27:00,08:27:00,MD,3,0,0,10877",
        "20261011-4109,08:23:00,08:23:00,BL,2,0,0,6183",
        "20261011-4109,08:15:00,08:15:00,UN,1,0,0,0",
        "20261011-4110,09:22:00,09:22:00,UN,5,0,0,24365",
        "20261011-4110,09:13:00,09:13:00,BL,4,0,0,18182",
        "20261011-4110,09:09:00,09:09:00,MD,3,0,0,15326",
        "20261011-4110,09:06:00,09:06:00,WE,2,0,0,11438",
        "20261011-4110,08:54:00,08:54:00,PA,1,0,0,0",
        "20261011-4211,09:58:00,09:58:00,PA,5,0,0,24365",
        "20261011-4211,09:46:00,09:46:00,WE,4,0,0,12927",
        "20261011-4211,09:42:00,09:42:00,MD,3,0,0,10877",
        "20261011-4211,09:38:00,09:38:00,BL,2,0,0,6183",
        "20261011-4211,09:30:00,09:30:00,UN,1,0,0,0",
        "20261011-4212,10:37:00,10:37:00,UN,5,0,0,24365",
        "20261011-4212,10:28:00,10:28:00,BL,4,0,0,18182",
        "20261011-4212,10:24:00,10:24:00,MD,3,0,0,15326",
        "20261011-4212,10:21:00,10:21:00,WE,2,0,0,11438",
        "20261011-4212,10:09:00,10:09:00,PA,1,0,0,0",
    ),
}


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            # A fixed timestamp: these bytes are parametrize ids, and a clock-stamped
            # zip gives each pytest-xdist worker different test ids ("Different tests
            # were collected", CI 3.12, 2026-10-05).
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text)
    return buffer.getvalue()


def _serve_ranges(httpx_mock, agency: str, body: bytes, status: int = 206) -> None:
    """Answer HEAD with the size and each GET with the bytes of its Range."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        if status != 206:
            return httpx.Response(status, content=body)
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    httpx_mock.add_callback(respond, url=constants.AGENCIES[agency].feed_url, is_reusable=True)


async def test_live_shaped_up_express_feed_reads_through_every_tool(httpx_mock):
    _serve_ranges(httpx_mock, "up_express", _zip(UP_EXPRESS))
    info = await client.get_feed_info("up_express")
    # The BOM must not leak into the first column name of any table.
    assert info.publisher_name == "Metrolinx"
    assert info.feed_end_date == date(2027, 3, 2)
    assert info.agency_names == ["UP Express"]
    assert (info.route_count, info.stop_count) == (1, 5)

    routes = await client.search_routes("up_express", route_type=2)
    assert [(r.route_id, r.route_type_name, r.color) for r in routes.routes] == [
        ("UP", "rail", "0075D2")
    ]
    stops = await client.search_stops("up_express", "union")
    assert stops.stops[0].stop_id == "UN"
    assert stops.stops[0].stop_code is None  # trailing empty column on a CRLF line

    # No calendar.txt: the date-named service_ids of calendar_dates.txt decide,
    # so the 2026-10-12 trip 4301 stays out of 2026-10-11.
    departures = await client.get_stop_departures(
        "up_express", "UN", service_date="2026-10-11", start_time="07:00"
    )
    assert [(d.trip_id[-4:], d.local_time) for d in departures.departures] == [
        ("4008", "08:07:00"),
        ("4109", "08:15:00"),
        ("4110", "09:22:00"),
        ("4211", "09:30:00"),
        ("4212", "10:37:00"),
    ]

    # Rows arrive in descending stop_sequence; the first departure is still sequence 1.
    summary = await client.get_route_summary("up_express", "UP", service_date="2026-10-11")
    assert (summary.trips_in_feed, summary.trips_on_date) == (6, 5)
    assert summary.distinct_stop_ids == 5
    by_direction = {d.direction_id: d for d in summary.directions}
    assert by_direction[0].headsigns == ["UP Express Pearson Airport"]
    assert (by_direction[0].first_departure, by_direction[0].last_departure) == (
        "08:15:00",
        "09:30:00",
    )
    assert (by_direction[1].first_departure, by_direction[1].last_departure) == (
        "07:39:00",
        "10:09:00",
    )


async def test_optional_columns_missing_and_untimed_stops(httpx_mock):
    # A minimal but valid feed: no feed_info.txt, no stop_code/parent_station,
    # no trip_headsign/direction_id, and an intermediate stop left untimed
    # (GTFS allows blank times between timepoints).
    files = {
        "routes.txt": "route_id,route_type\nR9,3\n",
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            'A,"Main St, North",50.0,-100.0\n'
            "B,Middle,50.1,-100.1\n"
            "C,End,50.2,-100.2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\nD,1,1,1,1,1,1,1,20260101,20261231\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\nR9,D,X1\nR9,D,X2\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "X1,07:00:00,07:00:00,A,1\n"
            "X1,,,B,2\n"
            "X1,07:20:00,07:20:00,C,3\n"
            "X2,07:30:00,07:30:00,A,1\n"
            "X2,,,B,2\n"
            "X2,07:50:00,07:50:00,C,3\n"
        ),
    }
    _serve_ranges(httpx_mock, "calgary", _zip(files))
    named = await client.search_stops("calgary", "main st, north")
    assert [(s.stop_id, s.stop_code, s.parent_station) for s in named.stops] == [("A", None, None)]
    untimed = await client.get_stop_departures(
        "calgary", "B", service_date="2026-10-06", start_time="00:00"
    )
    assert untimed.departures == []
    summary = await client.get_route_summary("calgary", "R9", service_date="2026-10-06")
    assert summary.route.short_name is None
    assert [(d.direction_id, d.headsigns, d.trips) for d in summary.directions] == [(None, [], 2)]
    assert summary.hourly[0].average_headway_minutes == 30.0
    assert summary.provenance.coverage is None  # no feed_info.txt dates to report


GTFS_HEADER = b"trip_id,arrival_time,departure_time,stop_id,stop_sequence"


def test_stop_times_with_spaces_after_commas_still_match():
    # Header names are stripped (column_indexes) and so are stops.txt values
    # (parse_table), so a padded stop_times.txt must give the same ids.
    indexes = gtfs.column_indexes(b"trip_id, arrival_time, departure_time, stop_id, stop_sequence")
    lines = [b"T1, 08:00:00, 08:00:00, P1, 1", b"T2, 08:30:00, 08:30:00, P10, 1"]
    by_stop = gtfs.filter_stop_times(lines, indexes, stop_ids=frozenset({"P1"}))
    assert [(r.trip_id, r.stop_id, r.departure) for r in by_stop] == [("T1", "P1", "08:00:00")]
    by_trip = gtfs.filter_stop_times(lines, indexes, trip_ids=frozenset({"T2"}))
    assert [r.stop_id for r in by_trip] == ["P10"]


def test_stop_times_with_trip_id_not_first_and_quoted_commas():
    # GTFS does not fix column order, and a quoted stop_headsign may hold a comma.
    indexes = gtfs.column_indexes(
        b"stop_id,stop_sequence,stop_headsign,trip_id,arrival_time,departure_time"
    )
    lines = [
        b'P1,1,"Downtown, via Main",T1,08:00:00,08:00:00',
        b"P2,2,,T1,08:05:00,08:05:00",
        b"P1,1,,T2,09:00:00,09:00:00",
    ]
    by_trip = gtfs.filter_stop_times(lines, indexes, trip_ids=frozenset({"T1"}))
    assert [(r.stop_id, r.stop_sequence) for r in by_trip] == [("P1", 1), ("P2", 2)]
    by_stop = gtfs.filter_stop_times(lines, indexes, stop_ids=frozenset({"P1"}))
    assert [(r.trip_id, r.departure) for r in by_stop] == [("T1", "08:00:00"), ("T2", "09:00:00")]


# -- hosts that fail ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "match", "requests"),
    [
        # A portal error page served as 200 instead of the zip.
        (200, b"<!DOCTYPE html><html><title>Maintenance</title></html>", "not a valid ZIP", 1),
        # A transfer cut short: no end-of-central-directory record.
        (200, _zip(UP_EXPRESS)[:400], "not a valid ZIP", 1),
        # 503 is retried (three attempts), then becomes a typed error.
        (503, b"", "HTTP 503", 3),
    ],
)
async def test_whole_download_host_failures_are_typed(httpx_mock, status, body, match, requests):
    url = constants.AGENCIES["bct_victoria"].feed_url
    httpx_mock.add_response(url=url, status_code=status, content=body, is_reusable=True)
    with pytest.raises(UpstreamError, match=match):
        await client.get_feed_info("bct_victoria")
    assert len(httpx_mock.get_requests()) == requests


@pytest.mark.parametrize(
    ("body", "status", "match"),
    [
        # 206 bytes that are not a zip (a replaced file, an HTML page).
        (b"<html>not a feed</html>" * 40, 206, "not a ZIP file"),
        # A host that ignores Range and sends the whole body with 200.
        (_zip(UP_EXPRESS), 200, "range requests"),
    ],
)
async def test_range_host_with_bad_bytes_is_an_upstream_error(httpx_mock, body, status, match):
    _serve_ranges(httpx_mock, "calgary", body, status=status)
    with pytest.raises(UpstreamError, match=match):
        await client.get_feed_info("calgary")


async def test_range_host_5xx_is_retried_then_typed(httpx_mock):
    httpx_mock.add_response(
        url=constants.AGENCIES["calgary"].feed_url, status_code=503, is_reusable=True
    )
    with pytest.raises(UpstreamError, match="HTTP 503"):
        await client.get_feed_info("calgary")
    # One HEAD, then the one-byte range fallback with its six attempts.
    methods = [r.method for r in httpx_mock.get_requests()]
    assert methods == ["HEAD"] + ["GET"] * 6
