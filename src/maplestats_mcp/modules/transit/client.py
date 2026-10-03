"""Client for static GTFS feeds. See the module docstring for what was
confirmed live; the agencies are configured in constants.AGENCIES.

Nothing is stored on disk. The zip's central directory and the small
tables are cached in memory for hours; `stop_times.txt` is streamed by
range, and only the rows for the requested stop or route are kept (and
cached for an hour, keyed by stop or route, not by date, so asking about
another date does not rescan).
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.transit import constants, gtfs, national
from maplestats_mcp.modules.transit.constants import Agency
from maplestats_mcp.modules.transit.schemas import (
    AgencyFeed,
    AgencyList,
    Departure,
    DirectionSummary,
    FeedFile,
    FeedInfo,
    HourlyFrequency,
    RouteRecord,
    RouteSearch,
    RouteSummary,
    StopDepartures,
    StopRecord,
    StopSearch,
)
from maplestats_mcp.modules.transit.zipstream import (
    download_whole,
    head,
    members_of,
    read_blob_member,
    read_nested_zip,
    stream_member_lines,
    total_bytes,
)
from maplestats_mcp.shared.cache import cached_fetch, forget
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.remote_zip import ZipMember, list_members, read_member

_SCANS = asyncio.Semaphore(constants.MAX_CONCURRENT_SCANS)


@dataclass(frozen=True)
class FeedDirectory:
    url: str
    total_bytes: int
    last_modified: datetime | None
    members: dict[str, ZipMember]
    # The whole zip, held only for hosts that cannot serve byte ranges.
    blob: bytes | None = None


class TripRecord(NamedTuple):
    trip_id: str
    route_id: str
    service_id: str
    headsign: str | None
    direction_id: int | None


class StopCall(NamedTuple):
    row: gtfs.StopTimeRow
    trip: TripRecord


# The agencies of StatCan's national database, filled by `_load_national` the
# first time a "national:<id>" key is used (a fixed snapshot, so kept for the
# life of the process; the catalogue fetch itself is cached for a day).
_NATIONAL: dict[str, Agency] = {}


def _agency(key: str) -> Agency:
    if key.startswith(constants.NATIONAL_PREFIX):
        agency = _NATIONAL.get(key)
        if agency is None:
            raise InvalidInput(
                f"Unknown agency '{key}'. Use transit_list_national_agencies for the keys of "
                "StatCan's national database."
            )
        if agency.status != "available":
            raise InvalidInput(
                f"{key} is not served from the national database: {agency.status_reason}"
            )
        return agency
    agency = constants.AGENCIES.get(key)
    if agency is None:
        raise InvalidInput(
            f"Unknown agency '{key}'. Use one of: {', '.join(constants.AGENCIES)}, or "
            f"'{constants.NATIONAL_PREFIX}<id>' from transit_list_national_agencies."
        )
    return agency


async def _national_catalog() -> tuple[national.Catalog, bool]:
    async def fetch() -> national.Catalog:
        return await national.load_catalog()

    catalog, was_cached = await cached_fetch(
        "transit:national:catalog", constants.NATIONAL_CATALOG_TTL_SECONDS, fetch
    )
    _NATIONAL.clear()
    _NATIONAL.update(catalog.agencies)
    return catalog, was_cached


async def _load_national() -> national.Catalog:
    return (await _national_catalog())[0]


async def _resolve(key: str) -> Agency:
    """`_agency`, after loading the national catalogue when the key needs it."""
    if key.startswith(constants.NATIONAL_PREFIX):
        await _load_national()
    return _agency(key)


def _is_excluded(agency: Agency, row: dict[str, str]) -> bool:
    route_type = row.get("route_type", "")
    return bool(agency.excluded_route_types) and (
        route_type.isdigit() and int(route_type) in agency.excluded_route_types
    )


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")


def _last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# -- directory and tables ---------------------------------------------


async def _directory(key: str) -> tuple[FeedDirectory, bool]:
    agency = await _resolve(key)

    async def fetch() -> FeedDirectory:
        if agency.database == "statcan":
            # The inner zip is read whole (a deflated member cannot be read at
            # random) and then served from memory like a BC Transit feed.
            catalog = await _load_national()
            custom_id = key.removeprefix(constants.NATIONAL_PREFIX)
            member = catalog.members.get(national.member_path(custom_id))
            if member is None:
                raise UpstreamError(f"{key}: the feed is not in the national archive.")
            blob = await read_nested_zip(constants.NATIONAL_URL, member)
            return FeedDirectory(
                constants.NATIONAL_URL,
                len(blob),
                constants.NATIONAL_AS_OF,
                {m.name.rsplit("/", 1)[-1].lower(): m for m in members_of(blob, key)},
                blob,
            )
        if not agency.range_requests:
            blob, whole = await download_whole(agency.feed_url)
            blob_members = members_of(blob, agency.feed_url)
            return FeedDirectory(
                str(whole.url),
                len(blob),
                _last_modified(whole.headers.get("last-modified")),
                {m.name.rsplit("/", 1)[-1].lower(): m for m in blob_members},
                blob,
            )
        response = await head(agency.feed_url)
        final_url = str(response.url)
        members, total = await list_members(final_url)
        by_name = {m.name.rsplit("/", 1)[-1].lower(): m for m in members}
        return FeedDirectory(
            final_url, total, _last_modified(response.headers.get("last-modified")), by_name
        )

    return await cached_fetch(f"transit:dir:{key}", constants.CACHE_TTL_DIRECTORY_SECONDS, fetch)


async def _with_fresh_directory[T](key: str, action: Callable[[], Awaitable[T]]) -> T:
    """Run `action`; on a failure, reload the directory and try again.

    Two causes are covered: the zip was replaced under the cached offsets,
    and the host answered a transient 502 or dropped the connection (the
    City of Toronto's download host did both during the 2026-10-01 checks,
    on requests that succeeded a few seconds later). Three attempts, then
    the last error is raised.
    """
    for _ in range(2):
        try:
            return await action()
        except (UpstreamError, UpstreamUnavailable):
            forget(f"transit:dir:{key}")
    return await action()


def _member(directory: FeedDirectory, key: str, name: str) -> ZipMember | None:
    return directory.members.get(name)


async def _read_table_bytes(directory: FeedDirectory, member: ZipMember) -> bytes:
    if directory.blob is not None:
        return await run_in_pool(
            read_blob_member, directory.blob, member, max_bytes=constants.TABLE_MAX_BYTES
        )
    return await read_member(directory.url, member, max_bytes=constants.TABLE_MAX_BYTES)


async def _table(
    key: str, name: str, *, required: bool = True
) -> tuple[list[dict[str, str]], bool]:
    """A small GTFS table, parsed and cached. Optional files read as empty."""

    async def fetch() -> list[dict[str, str]]:
        async def once() -> list[dict[str, str]]:
            directory, _ = await _directory(key)
            member = _member(directory, key, name)
            if member is None:
                if required:
                    raise UpstreamError(f"{key}: the feed has no {name}.")
                return []
            data = await _read_table_bytes(directory, member)
            return await run_in_pool(gtfs.parse_table, data)

        return await _with_fresh_directory(key, once)

    return await cached_fetch(
        f"transit:table:{key}:{name}", constants.CACHE_TTL_TABLE_SECONDS, fetch
    )


async def _scan_stop_times(
    key: str,
    *,
    stop_ids: frozenset[str] | None = None,
    trip_ids: frozenset[str] | None = None,
) -> list[gtfs.StopTimeRow]:
    async def once() -> list[gtfs.StopTimeRow]:
        directory, _ = await _directory(key)
        member = _member(directory, key, "stop_times.txt")
        if member is None:
            raise UpstreamError(f"{key}: the feed has no stop_times.txt.")
        rows: list[gtfs.StopTimeRow] = []
        indexes: dict[str, int] | None = None
        async with _SCANS:
            async for batch in stream_member_lines(directory.url, member, blob=directory.blob):
                if indexes is None:
                    indexes = gtfs.column_indexes(batch[0])
                    batch = batch[1:]
                rows.extend(
                    await run_in_pool(
                        gtfs.filter_stop_times,
                        batch,
                        indexes,
                        stop_ids=stop_ids,
                        trip_ids=trip_ids,
                    )
                )
        return rows

    return await _with_fresh_directory(key, once)


async def _trips(
    key: str,
    *,
    route_id: str | None = None,
    trip_ids: frozenset[str] | None = None,
) -> list[TripRecord]:
    async def once() -> list[TripRecord]:
        directory, _ = await _directory(key)
        member = _member(directory, key, "trips.txt")
        if member is None:
            raise UpstreamError(f"{key}: the feed has no trips.txt.")
        data = await _read_table_bytes(directory, member)
        rows = await run_in_pool(gtfs.parse_table, data)
        return [
            TripRecord(
                trip_id=r["trip_id"],
                route_id=r["route_id"],
                service_id=r["service_id"],
                headsign=r.get("trip_headsign") or None,
                direction_id=int(r["direction_id"])
                if r.get("direction_id", "").isdigit()
                else None,
            )
            for r in rows
            if (route_id is None or r.get("route_id") == route_id)
            and (trip_ids is None or r.get("trip_id") in trip_ids)
        ]

    return await _with_fresh_directory(key, once)


async def _frequency_trips(key: str) -> frozenset[str]:
    """Trips described by frequencies.txt, which this module leaves out.

    Their stop_times are a template (Salaberry-de-Valleyfield's Communobus
    trips, checked 2026-10-03, start at 00:10:00 and repeat every 30 or 60
    minutes from frequencies.txt), so reporting them as listed would give
    wrong times. Most feeds ship the file empty or not at all.
    """
    rows, _ = await _table(key, "frequencies.txt", required=False)
    return frozenset(r["trip_id"] for r in rows if r.get("trip_id"))


# -- provenance --------------------------------------------------------


async def _provenance(
    key: str, directory: FeedDirectory, was_cached: bool, schema_name: str
) -> Provenance:
    agency = _agency(key)
    feed_info, _ = await _table(key, "feed_info.txt", required=False)
    start = gtfs.parse_gtfs_date(feed_info[0].get("feed_start_date")) if feed_info else None
    end = gtfs.parse_gtfs_date(feed_info[0].get("feed_end_date")) if feed_info else None
    coverage = f"Schedule valid {start} to {end}." if start and end else None
    if agency.database == "statcan":
        coverage = (
            f"{coverage or 'No feed_info.txt dates.'} StatCan validator window "
            f"{agency.window_start} to {agency.window_end}."
        )
    return make_provenance(
        source=f"transit:{key}",
        url=directory.url,
        cached=was_cached,
        schema_name=schema_name,
        as_of=directory.last_modified,
        freshness=agency.update_cadence,
        coverage=coverage,
        limits=(
            f"Licence: {agency.licence}. Attribution: {agency.attribution}"
            + (f" {agency.notes_en}" if agency.excluded_route_types else "")
            + (
                f" Compiled by Statistics Canada under {constants.NATIONAL_LICENCE}; "
                f"licence page: {agency.licence_url}. Data quality is taken as is "
                "(no fixes applied by StatCan)."
                if agency.database == "statcan"
                else ""
            )
        ),
    )


async def _check_date(key: str, day: date) -> None:
    feed_info, _ = await _table(key, "feed_info.txt", required=False)
    start = end = None
    if feed_info:
        start = gtfs.parse_gtfs_date(feed_info[0].get("feed_start_date"))
        end = gtfs.parse_gtfs_date(feed_info[0].get("feed_end_date"))
    agency = _agency(key)
    if agency.database == "statcan" and not (start and end):
        # Feeds without feed_info.txt dates: StatCan's validator window instead.
        start, end = agency.window_start, agency.window_end
    if start and end and not start <= day <= end:
        hint = (
            " This is a 2025 snapshot compiled by Statistics Canada: pass a service_date "
            "inside that window."
            if agency.database == "statcan"
            else ""
        )
        raise InvalidInput(
            f"{key}: the schedule covers {start} to {end}; {day} is outside it.{hint}"
        )


async def _timezone(key: str) -> str:
    """The zone for "today" and local times: a national feed's own agency.txt, else the config."""
    agency = _agency(key)
    if agency.database != "statcan":
        return agency.timezone
    rows, _ = await _table(key, "agency.txt", required=False)
    zone = rows[0].get("agency_timezone", "") if rows else ""
    try:
        ZoneInfo(zone)
    except (ValueError, KeyError, OSError):
        return agency.timezone
    return zone


def _service_day(zone: str, day: str | None) -> date:
    if day:
        return gtfs.parse_iso_date(day)
    return datetime.now(ZoneInfo(zone)).date()


# -- agencies and feed info ---------------------------------------------


def _agency_feed(
    agency: Agency,
    lang: str,
    *,
    reachable: bool | None = None,
    zip_bytes: int | None = None,
    modified: datetime | None = None,
) -> AgencyFeed:
    notes = (agency.notes_fr if lang == "fr" else agency.notes_en) or None
    return AgencyFeed(
        key=agency.key,
        name=agency.name_fr if lang == "fr" else agency.name_en,
        name_en=agency.name_en,
        name_fr=agency.name_fr,
        city=agency.city,
        province=agency.province,
        timezone=agency.timezone,
        feed_url=agency.feed_url,
        source_page=agency.source_page,
        licence=agency.licence,
        licence_url=agency.licence_url,
        attribution=agency.attribution,
        update_cadence=agency.update_cadence,
        notes=notes,
        reachable=reachable,
        zip_bytes=zip_bytes,
        last_modified=modified,
        database=agency.database,
        status=agency.status,
        status_reason=agency.status_reason or None,
        live_agency_key=agency.live_agency_key,
        service_window_start=agency.window_start,
        service_window_end=agency.window_end,
        validator_errors=agency.validator_errors,
        validator_warnings=agency.validator_warnings,
    )


async def _probe(agency: Agency, lang: str) -> tuple[AgencyFeed, bool]:
    if not agency.range_requests:
        # BC Transit's host builds the whole zip (5 to 25 s) before it sends
        # any header, so listing the agencies does not poke twelve of them;
        # reachability stays unknown until a tool has downloaded the feed.
        return _agency_feed(agency, lang), False

    async def fetch() -> tuple[bool, int | None, datetime | None]:
        try:
            response = await head(agency.feed_url)
        except (UpstreamError, UpstreamUnavailable, httpx.HTTPError):
            return False, None, None
        return (
            True,
            total_bytes(response),
            _last_modified(response.headers.get("last-modified")),
        )

    (reachable, size, modified), was_cached = await cached_fetch(
        f"transit:probe:{agency.key}", constants.CACHE_TTL_DIRECTORY_SECONDS, fetch
    )
    return _agency_feed(agency, lang, reachable=reachable, zip_bytes=size, modified=modified), (
        was_cached
    )


async def list_agencies(*, lang: str = "en") -> AgencyList:
    """Every configured agency, with a live HEAD check of its zip (not for hosts
    that build the zip on request: their `reachable` stays null)."""
    probed = await asyncio.gather(*(_probe(a, lang) for a in constants.AGENCIES.values()))
    return AgencyList(
        total_matches=len(probed),
        agencies=[feed for feed, _ in probed],
        provenance=make_provenance(
            source="transit",
            url="see agencies[].feed_url",
            cached=all(cached for _, cached in probed),
            schema_name="transit.AgencyList",
            freshness="Each agency's zip is checked with a HEAD request (cached 10 minutes).",
            limits=(
                "Only agencies with an open static GTFS zip, no key, and range support are "
                "configured; see agencies[].licence and attribution for reuse terms."
            ),
        ),
    )


async def list_national_agencies(
    *,
    query: str | None = None,
    province: str | None = None,
    status: str | None = None,
    lang: str = "en",
) -> AgencyList:
    """The feeds of StatCan's Canadian Public Transit Network Database.

    Each is 'available' (read from the national archive with agency
    'national:<id>'), 'overlaps_live' (the agency is read live instead) or
    'excluded' (terms or missing licence information; see status_reason).
    """
    if status is not None and status not in ("available", "overlaps_live", "excluded"):
        raise InvalidInput("status must be 'available', 'overlaps_live' or 'excluded'.")
    _, was_cached = await _national_catalog()
    needle = gtfs.fold(query) if query else None
    wanted = province.strip().upper() if province else None
    feeds = [
        _agency_feed(agency, lang)
        for agency in _NATIONAL.values()
        if (status is None or agency.status == status)
        and (wanted is None or agency.province == wanted)
        and (
            needle is None
            or needle in gtfs.fold(f"{agency.name_en} {agency.key.removeprefix('national:')}")
        )
    ]
    feeds.sort(key=lambda f: (f.province, f.name_en.casefold()))
    return AgencyList(
        total_matches=len(feeds),
        agencies=feeds,
        provenance=make_provenance(
            source="transit:statcan",
            url=constants.NATIONAL_URL,
            cached=was_cached,
            schema_name="transit.AgencyList",
            as_of=constants.NATIONAL_AS_OF,
            freshness=constants.NATIONAL_FRESHNESS,
            coverage=f"{len(_NATIONAL)} feeds in the database; product page {constants.NATIONAL_PAGE}.",
            limits=(
                f"Compiled by Statistics Canada under {constants.NATIONAL_LICENCE}. "
                f"{constants.NATIONAL_NOTICE} Each feed's licence_url and attribution are the "
                "ones StatCan recorded for it; check them before republishing."
            ),
        ),
    )


async def get_feed_info(agency_key: str, *, lang: str = "en") -> FeedInfo:
    """The feed's own metadata, file sizes and counts of routes and stops."""
    agency = await _resolve(agency_key)
    directory, dir_cached = await _directory(agency_key)
    feed_info, _ = await _table(agency_key, "feed_info.txt", required=False)
    agency_rows, _ = await _table(agency_key, "agency.txt", required=False)
    routes, _ = await _table(agency_key, "routes.txt")
    stops, _ = await _table(agency_key, "stops.txt")
    info = feed_info[0] if feed_info else {}
    if directory.blob is None:
        feed, _ = await _probe(agency, lang)
    else:
        # The zip was just downloaded whole; a second request would make the
        # host build it again, so its size and date come from that download.
        feed = _agency_feed(
            agency,
            lang,
            reachable=True,
            zip_bytes=directory.total_bytes,
            modified=directory.last_modified,
        )
    return FeedInfo(
        agency=feed,
        publisher_name=info.get("feed_publisher_name") or None,
        feed_version=info.get("feed_version") or None,
        feed_start_date=gtfs.parse_gtfs_date(info.get("feed_start_date")),
        feed_end_date=gtfs.parse_gtfs_date(info.get("feed_end_date")),
        agency_names=[r["agency_name"] for r in agency_rows if r.get("agency_name")],
        route_count=len(routes),
        stop_count=len(stops),
        files=[
            FeedFile(name=m.name, compressed_bytes=m.compressed_size, uncompressed_bytes=m.size)
            for m in directory.members.values()
        ],
        provenance=await _provenance(agency_key, directory, dir_cached, "transit.FeedInfo"),
    )


# -- routes ------------------------------------------------------------


def _route_record(row: dict[str, str]) -> RouteRecord:
    route_type = int(row["route_type"]) if row.get("route_type", "").lstrip("-").isdigit() else None
    return RouteRecord(
        route_id=row["route_id"],
        short_name=row.get("route_short_name") or None,
        long_name=row.get("route_long_name") or None,
        route_type=route_type,
        route_type_name=constants.ROUTE_TYPES.get(route_type) if route_type is not None else None,
        description=row.get("route_desc") or None,
        color=row.get("route_color") or None,
    )


async def search_routes(
    agency_key: str,
    query: str | None = None,
    *,
    route_type: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> RouteSearch:
    """Routes whose id, short name, long name or description contain `query`."""
    del lang
    agency = await _resolve(agency_key)
    _check_limit(limit)
    directory, dir_cached = await _directory(agency_key)
    rows, _ = await _table(agency_key, "routes.txt")
    needle = gtfs.fold(query) if query else None
    matches: list[tuple[int, RouteRecord]] = []
    for row in rows:
        if _is_excluded(agency, row):
            continue
        record = _route_record(row)
        if route_type is not None and record.route_type != route_type:
            continue
        rank = 0
        if needle:
            fields = [
                gtfs.fold(v or "")
                for v in (record.route_id, record.short_name, record.long_name, record.description)
            ]
            if needle in (fields[0], fields[1]):
                rank = 0
            elif any(needle in f for f in fields):
                rank = 1
            else:
                continue
        matches.append((rank, record))
    matches.sort(key=lambda m: (m[0], _natural(m[1].short_name or m[1].route_id)))
    return RouteSearch(
        agency=agency_key,
        query=query,
        total_matches=len(matches),
        routes=[record for _, record in matches[:limit]],
        provenance=await _provenance(agency_key, directory, dir_cached, "transit.RouteSearch"),
    )


def _natural(text: str) -> tuple[int, str]:
    digits = "".join(ch for ch in text if ch.isdigit())
    return (int(digits) if digits else 10**9, text)


async def _resolve_route(agency_key: str, route: str) -> RouteRecord:
    agency = _agency(agency_key)
    rows, _ = await _table(agency_key, "routes.txt")
    rows = [r for r in rows if not _is_excluded(agency, r)]
    exact = [r for r in rows if r["route_id"] == route]
    named = [r for r in rows if r.get("route_short_name", "").casefold() == route.casefold()]
    found = exact or named
    if not found:
        raise NotFound(
            f"{agency_key}: no route with id or short name '{route}'. Use transit_search_routes."
        )
    if len(found) > 1:
        ids = ", ".join(r["route_id"] for r in found[:10])
        raise InvalidInput(
            f"{agency_key}: '{route}' matches several routes ({ids}); pass the route_id."
        )
    return _route_record(found[0])


# -- stops -------------------------------------------------------------


def _stop_record(row: dict[str, str], distance: float | None = None) -> StopRecord:
    def number(key: str) -> float | None:
        try:
            return float(row[key])
        except (KeyError, ValueError):
            return None

    def integer(key: str) -> int | None:
        return int(row[key]) if row.get(key, "").isdigit() else None

    return StopRecord(
        stop_id=row["stop_id"],
        stop_code=row.get("stop_code") or None,
        name=row.get("stop_name", ""),
        latitude=number("stop_lat"),
        longitude=number("stop_lon"),
        location_type=integer("location_type"),
        parent_station=row.get("parent_station") or None,
        wheelchair_boarding=integer("wheelchair_boarding"),
        distance_m=round(distance, 1) if distance is not None else None,
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


async def search_stops(
    agency_key: str,
    query: str | None = None,
    *,
    near_latitude: float | None = None,
    near_longitude: float | None = None,
    radius_m: float = 500.0,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> StopSearch:
    """Stops by name, code or id, and/or within `radius_m` of a point."""
    del lang
    await _resolve(agency_key)
    _check_limit(limit)
    if (near_latitude is None) != (near_longitude is None):
        raise InvalidInput("Pass near_latitude and near_longitude together.")
    if not query and near_latitude is None:
        raise InvalidInput("Pass a query, a point (near_latitude/near_longitude), or both.")
    if radius_m <= 0:
        raise InvalidInput("radius_m must be positive.")
    directory, dir_cached = await _directory(agency_key)
    rows, _ = await _table(agency_key, "stops.txt")
    needle = gtfs.fold(query) if query else None
    matches: list[tuple[float, int, StopRecord]] = []
    for row in rows:
        distance: float | None = None
        if near_latitude is not None and near_longitude is not None:
            try:
                distance = _haversine_m(
                    near_latitude, near_longitude, float(row["stop_lat"]), float(row["stop_lon"])
                )
            except (KeyError, ValueError):
                continue
            if distance > radius_m:
                continue
        rank = 2
        if needle:
            name = gtfs.fold(row.get("stop_name", ""))
            if needle in (gtfs.fold(row["stop_id"]), gtfs.fold(row.get("stop_code", ""))):
                rank = 0
            elif name.startswith(needle):
                rank = 1
            elif needle in name:
                rank = 2
            else:
                continue
        matches.append(
            (distance if distance is not None else 0.0, rank, _stop_record(row, distance))
        )
    matches.sort(key=lambda m: (m[1], m[0], m[2].name))
    if near_latitude is not None and not needle:
        matches.sort(key=lambda m: m[0])
    return StopSearch(
        agency=agency_key,
        query=query,
        total_matches=len(matches),
        stops=[stop for _, _, stop in matches[:limit]],
        provenance=await _provenance(agency_key, directory, dir_cached, "transit.StopSearch"),
    )


async def _resolve_stop(agency_key: str, stop: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    rows, _ = await _table(agency_key, "stops.txt")
    by_id = [r for r in rows if r["stop_id"] == stop]
    found = by_id or [r for r in rows if r.get("stop_code") == stop]
    if not found:
        raise NotFound(f"{agency_key}: no stop with id or code '{stop}'. Use transit_search_stops.")
    if len(found) > 1:
        ids = ", ".join(r["stop_id"] for r in found[:10])
        raise InvalidInput(
            f"{agency_key}: '{stop}' matches several stops ({ids}); pass the stop_id."
        )
    chosen = found[0]
    children = [r for r in rows if r.get("parent_station") == chosen["stop_id"]]
    return chosen, children[: constants.STOP_FAMILY_MAX]


async def get_stop_departures(
    agency_key: str,
    stop: str,
    *,
    service_date: str | None = None,
    start_time: str | None = None,
    route: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> StopDepartures:
    """Scheduled departures at a stop (and a station's platforms) on a date."""
    del lang
    agency = await _resolve(agency_key)
    _check_limit(limit)
    zone = await _timezone(agency_key)
    day = _service_day(zone, service_date)
    if start_time:
        from_seconds = gtfs.parse_start_time(start_time)
    elif day == datetime.now(ZoneInfo(zone)).date():
        now = datetime.now(ZoneInfo(zone))
        from_seconds = now.hour * 3600 + now.minute * 60
    else:
        from_seconds = 0
    await _check_date(agency_key, day)
    directory, dir_cached = await _directory(agency_key)
    chosen, children = await _resolve_stop(agency_key, stop)
    stop_ids = frozenset([chosen["stop_id"], *(c["stop_id"] for c in children)])
    route_record = await _resolve_route(agency_key, route) if route else None

    async def fetch() -> list[StopCall]:
        rows = await _scan_stop_times(agency_key, stop_ids=stop_ids)
        trips = await _trips(agency_key, trip_ids=frozenset(r.trip_id for r in rows))
        by_trip = {t.trip_id: t for t in trips}
        return [StopCall(r, by_trip[r.trip_id]) for r in rows if r.trip_id in by_trip]

    calls, scan_cached = await cached_fetch(
        f"transit:stop:{agency_key}:{','.join(sorted(stop_ids))}",
        constants.CACHE_TTL_SCAN_SECONDS,
        fetch,
    )
    templated = await _frequency_trips(agency_key)
    if templated:
        calls = [c for c in calls if c.trip.trip_id not in templated]
    calendar, _ = await _table(agency_key, "calendar.txt", required=False)
    calendar_dates, _ = await _table(agency_key, "calendar_dates.txt", required=False)
    today = gtfs.active_services(calendar, calendar_dates, day)
    yesterday = gtfs.active_services(calendar, calendar_dates, gtfs.previous_day(day))
    routes, _ = await _table(agency_key, "routes.txt")
    route_by_id = {r["route_id"]: r for r in routes if not _is_excluded(agency, r)}

    entries: list[tuple[int, bool, StopCall]] = []
    for call in calls:
        if route_record and call.trip.route_id != route_record.route_id:
            continue
        if call.trip.route_id not in route_by_id:
            continue
        seconds = gtfs.to_seconds(call.row.departure)
        if seconds is None:
            seconds = gtfs.to_seconds(call.row.arrival)
        if seconds is None:
            continue
        if call.trip.service_id in today and seconds >= from_seconds:
            entries.append((seconds, False, call))
        # A trip that began the previous service day and runs past 24:00.
        if (
            call.trip.service_id in yesterday
            and seconds >= 86400
            and seconds - 86400 >= from_seconds
        ):
            entries.append((seconds - 86400, True, call))
    entries.sort(key=lambda e: (e[0], e[2].trip.route_id, e[2].trip.trip_id))

    departures: list[Departure] = []
    for effective, after_midnight, call in entries[:limit]:
        route_row = route_by_id.get(call.trip.route_id, {})
        departures.append(
            Departure(
                route_id=call.trip.route_id,
                route_short_name=route_row.get("route_short_name") or None,
                route_long_name=route_row.get("route_long_name") or None,
                headsign=call.trip.headsign,
                direction_id=call.trip.direction_id,
                trip_id=call.trip.trip_id,
                stop_id=call.row.stop_id,
                stop_sequence=call.row.stop_sequence,
                arrival_time=call.row.arrival or None,
                departure_time=call.row.departure or call.row.arrival,
                local_time=gtfs.to_clock(effective),
                after_midnight_of_previous_service_day=after_midnight,
            )
        )
    return StopDepartures(
        agency=agency_key,
        stop=_stop_record(chosen),
        stop_ids_included=sorted(stop_ids),
        service_date=day,
        from_time=gtfs.to_gtfs_time(from_seconds),
        total_matches=len(entries),
        departures=departures,
        provenance=await _provenance(
            agency_key, directory, dir_cached and scan_cached, "transit.StopDepartures"
        ),
    )


# -- route summary -------------------------------------------------------


async def get_route_summary(
    agency_key: str,
    route: str,
    *,
    service_date: str | None = None,
    lang: str = "en",
) -> RouteSummary:
    """Trips, first/last departures, stops served and frequency by hour on a date."""
    del lang
    await _resolve(agency_key)
    day = _service_day(await _timezone(agency_key), service_date)
    await _check_date(agency_key, day)
    directory, dir_cached = await _directory(agency_key)
    record = await _resolve_route(agency_key, route)
    templated = await _frequency_trips(agency_key)
    all_trips = [
        t for t in await _trips(agency_key, route_id=record.route_id) if t.trip_id not in templated
    ]
    calendar, _ = await _table(agency_key, "calendar.txt", required=False)
    calendar_dates, _ = await _table(agency_key, "calendar_dates.txt", required=False)
    services = gtfs.active_services(calendar, calendar_dates, day)
    trips = [t for t in all_trips if t.service_id in services]
    trip_ids = frozenset(t.trip_id for t in trips)

    async def fetch() -> list[gtfs.StopTimeRow]:
        return await _scan_stop_times(agency_key, trip_ids=trip_ids) if trip_ids else []

    rows, scan_cached = await cached_fetch(
        f"transit:route:{agency_key}:{record.route_id}:{day}",
        constants.CACHE_TTL_SCAN_SECONDS,
        fetch,
    )
    stops, _ = await _table(agency_key, "stops.txt")
    stop_by_id = {s["stop_id"]: s for s in stops}

    by_trip: dict[str, list[gtfs.StopTimeRow]] = {}
    for row in rows:
        by_trip.setdefault(row.trip_id, []).append(row)
    first_departure: dict[str, int] = {}
    for trip_id, trip_rows in by_trip.items():
        first = min(trip_rows, key=lambda r: r.stop_sequence)
        seconds = gtfs.to_seconds(first.departure) or gtfs.to_seconds(first.arrival)
        if seconds is not None:
            first_departure[trip_id] = seconds

    served = {r.stop_id for r in rows}
    stations = {stop_by_id.get(s, {}).get("parent_station") or s for s in served}
    names = {stop_by_id[s]["stop_name"] for s in served if s in stop_by_id}

    trip_by_id = {t.trip_id: t for t in trips}
    hourly: Counter[tuple[int | None, int]] = Counter()
    per_direction: dict[int | None, list[TripRecord]] = {}
    for trip_id, seconds in first_departure.items():
        trip = trip_by_id[trip_id]
        hourly[(trip.direction_id, seconds // 3600)] += 1
        per_direction.setdefault(trip.direction_id, []).append(trip)

    def ordered(direction: int | None) -> int:
        return -1 if direction is None else direction

    directions = []
    for direction in sorted(per_direction, key=ordered):
        group = per_direction[direction]
        times = [first_departure[t.trip_id] for t in group]
        headsigns = Counter(t.headsign for t in group if t.headsign)
        directions.append(
            DirectionSummary(
                direction_id=direction,
                headsigns=[h for h, _ in headsigns.most_common(5)],
                trips=len(group),
                first_departure=gtfs.to_gtfs_time(min(times)),
                last_departure=gtfs.to_gtfs_time(max(times)),
            )
        )
    return RouteSummary(
        agency=agency_key,
        route=record,
        service_date=day,
        trips_in_feed=len(all_trips),
        trips_on_date=len(trips),
        distinct_stop_ids=len(served),
        distinct_stations=len(stations),
        distinct_stop_names=len(names),
        directions=directions,
        hourly=[
            HourlyFrequency(
                direction_id=direction,
                hour=hour,
                trips=count,
                average_headway_minutes=round(60 / count, 1) if count > 1 else None,
            )
            for (direction, hour), count in sorted(
                hourly.items(), key=lambda kv: (ordered(kv[0][0]), kv[0][1])
            )
        ],
        provenance=await _provenance(
            agency_key, directory, dir_cached and scan_cached, "transit.RouteSummary"
        ),
    )
