"""Pure GTFS helpers: table parsing, times, service calendars, line filters.

No network here, so everything is unit-testable on small strings.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date, timedelta
from typing import NamedTuple

from maplestats_mcp.shared.errors import InvalidInput

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TIME = re.compile(r"^\s*(\d{1,3}):([0-5]\d)(?::([0-5]\d))?\s*$")


def parse_table(data: bytes) -> list[dict[str, str]]:
    """Rows of a GTFS CSV as dicts; tolerant of a BOM and stray spaces in headers.

    VIA Rail's feed is Windows-1252, not UTF-8 (an accented e arrives as a
    lone 0xE9 byte), so a file that is not valid UTF-8 is read as cp1252.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [name.strip() for name in reader.fieldnames or []]
    return [{key: (value or "").strip() for key, value in row.items() if key} for row in reader]


def to_seconds(value: str | None) -> int | None:
    """GTFS time 'H:MM:SS' (hours may pass 24) as seconds, or None when blank."""
    if not value or not value.strip():
        return None
    match = _TIME.match(value)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0)


def to_clock(seconds: int) -> str:
    """Seconds since the service day started as HH:MM:SS, hours wrapped to 00-23."""
    seconds %= 86400
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def to_gtfs_time(seconds: int) -> str:
    """Seconds as the GTFS HH:MM:SS form, hours not wrapped."""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_start_time(value: str) -> int:
    seconds = to_seconds(value)
    if seconds is None:
        raise InvalidInput(f"start_time must look like 'HH:MM' or 'HH:MM:SS', got '{value}'.")
    return seconds


def parse_gtfs_date(value: str | None) -> date | None:
    if not value or len(value.strip()) != 8:
        return None
    try:
        text = value.strip()
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"date must be YYYY-MM-DD, got '{value}'.") from exc


def active_services(
    calendar: list[dict[str, str]], calendar_dates: list[dict[str, str]], day: date
) -> set[str]:
    """service_ids running on `day`: weekly pattern, then dated additions/removals.

    A feed may omit calendar.txt entirely (Edmonton's does), in which case
    calendar_dates.txt alone defines service.
    """
    weekday = _WEEKDAYS[day.weekday()]
    services: set[str] = set()
    for row in calendar:
        start, end = parse_gtfs_date(row.get("start_date")), parse_gtfs_date(row.get("end_date"))
        if row.get(weekday) == "1" and start and end and start <= day <= end:
            services.add(row["service_id"])
    stamp = day.strftime("%Y%m%d")
    for row in calendar_dates:
        if row.get("date") != stamp:
            continue
        if row.get("exception_type") == "1":
            services.add(row["service_id"])
        elif row.get("exception_type") == "2":
            services.discard(row["service_id"])
    return services


def previous_day(day: date) -> date:
    return day - timedelta(days=1)


def fold(text: str) -> str:
    """Lower-case and strip accents so 'Montreal' finds 'Montréal'."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


class StopTimeRow(NamedTuple):
    trip_id: str
    arrival: str
    departure: str
    stop_id: str
    stop_sequence: int


def column_indexes(header: bytes) -> dict[str, int]:
    names = header.lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace").split(",")
    return {name.strip().strip('"'): i for i, name in enumerate(names)}


def _fields(line: bytes) -> list[str]:
    if b'"' in line:
        return next(csv.reader([line.decode("utf-8", errors="replace")]))
    return line.decode("utf-8", errors="replace").split(",")


def _row_from(line: bytes, indexes: dict[str, int]) -> StopTimeRow | None:
    fields = _fields(line)
    try:
        return StopTimeRow(
            trip_id=fields[indexes["trip_id"]],
            arrival=fields[indexes["arrival_time"]].strip(),
            departure=fields[indexes["departure_time"]].strip(),
            stop_id=fields[indexes["stop_id"]],
            stop_sequence=int(fields[indexes["stop_sequence"]]),
        )
    except (IndexError, KeyError, ValueError):
        return None


def filter_stop_times(
    lines: list[bytes],
    indexes: dict[str, int],
    *,
    stop_ids: frozenset[str] | None = None,
    trip_ids: frozenset[str] | None = None,
) -> list[StopTimeRow]:
    """Rows of stop_times.txt for the given stops or trips (exactly one is given).

    A substring or prefix test runs first, in C, on every line; only the
    survivors are parsed, and their stop/trip id is re-checked on the parsed
    field, so an id that merely appears inside another column never matches.
    """
    if (stop_ids is None) == (trip_ids is None):
        raise ValueError("Pass exactly one of stop_ids or trip_ids.")
    needle = (
        re.compile(
            b'(?:^|,)"?(?:'
            + b"|".join(re.escape(s.encode()) for s in sorted(stop_ids))
            + b')"?(?:,|$)'
        )
        if stop_ids
        else None
    )
    trip_bytes = {t.encode() for t in trip_ids} if trip_ids else set()
    found: list[StopTimeRow] = []
    for line in lines:
        if not line:
            continue
        if needle is not None:
            if not needle.search(line):
                continue
        elif not trip_bytes or line.partition(b",")[0].strip(b'"') not in trip_bytes:
            continue
        row = _row_from(line, indexes)
        if row is None:
            continue
        if stop_ids is not None and row.stop_id not in stop_ids:
            continue
        if trip_ids is not None and row.trip_id not in trip_ids:
            continue
        found.append(row)
    return found
