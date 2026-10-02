"""Pure GTFS helpers: times, calendars, table parsing and line filtering."""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.transit import gtfs
from maplestats_mcp.shared.errors import InvalidInput


def test_times_pass_24_hours_and_wrap_for_the_clock():
    assert gtfs.to_seconds("08:05:30") == 8 * 3600 + 5 * 60 + 30
    assert gtfs.to_seconds("25:10:00") == 25 * 3600 + 600
    assert gtfs.to_seconds(" 7:05 ") == 7 * 3600 + 300
    assert gtfs.to_seconds("") is None
    assert gtfs.to_seconds("soon") is None
    assert gtfs.to_clock(25 * 3600 + 600) == "01:10:00"
    assert gtfs.to_gtfs_time(25 * 3600 + 600) == "25:10:00"


def test_bad_start_time_and_date_are_input_errors():
    with pytest.raises(InvalidInput, match="start_time"):
        gtfs.parse_start_time("noon")
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        gtfs.parse_iso_date("10/06/2026")
    assert gtfs.parse_gtfs_date("20261006") == date(2026, 10, 6)
    assert gtfs.parse_gtfs_date("2026") is None


def test_parse_table_strips_bom_and_spaces():
    data = "﻿stop_id, stop_name\n 1 , Central \n".encode()
    assert gtfs.parse_table(data) == [{"stop_id": "1", "stop_name": "Central"}]


def test_active_services_weekly_pattern_with_exceptions():
    calendar = [
        {
            "service_id": "WK",
            "monday": "1",
            "tuesday": "1",
            "saturday": "0",
            "start_date": "20261001",
            "end_date": "20261031",
        }
    ]
    dates = [
        {"service_id": "WK", "date": "20261012", "exception_type": "2"},
        {"service_id": "EXTRA", "date": "20261012", "exception_type": "1"},
    ]
    assert gtfs.active_services(calendar, dates, date(2026, 10, 6)) == {"WK"}
    assert gtfs.active_services(calendar, dates, date(2026, 10, 12)) == {"EXTRA"}
    assert gtfs.active_services(calendar, dates, date(2026, 11, 2)) == set()
    # No calendar.txt at all: dated additions alone define service.
    assert gtfs.active_services([], dates, date(2026, 10, 12)) == {"EXTRA"}


def test_fold_removes_accents():
    assert gtfs.fold("Montréal Éléphant") == "montreal elephant"


HEADER = b"trip_id,arrival_time,departure_time,stop_id,stop_sequence"


def test_filter_stop_times_by_stop_checks_the_parsed_field():
    indexes = gtfs.column_indexes(HEADER)
    lines = [
        b"T1,08:00:00,08:00:00,100,1",
        b"T2,08:00:00,08:00:00,1000,1",  # 100 is only a prefix of 1000
        b"100,08:00:00,08:00:00,555,1",  # 100 appears as a trip id, not a stop
        b'"T3",09:00:00,09:00:00,"100",2',
        b"",
        b"T4,bad,bad,100,x",  # unparsable sequence is dropped
    ]
    rows = gtfs.filter_stop_times(lines, indexes, stop_ids=frozenset({"100"}))
    assert [(r.trip_id, r.stop_sequence) for r in rows] == [("T1", 1), ("T3", 2)]


def test_filter_stop_times_by_trip_and_argument_guard():
    indexes = gtfs.column_indexes(b"\xef\xbb\xbf" + HEADER)
    lines = [b"T1,08:00:00,08:00:00,1,1", b"T10,08:00:00,08:00:00,2,1"]
    rows = gtfs.filter_stop_times(lines, indexes, trip_ids=frozenset({"T1"}))
    assert [r.stop_id for r in rows] == ["1"]
    with pytest.raises(ValueError, match="exactly one"):
        gtfs.filter_stop_times(lines, indexes)
