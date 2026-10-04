"""Live smoke test for the static GTFS transit module.

Every tool is called against each agency's real zip. Three reconciliations
check the answers against something other than the code under test:

1. Calgary's whole zip (18 MB) is downloaded and read with `zipfile` and
   `csv`; the range-streamed stop listing, route count and stop count must
   equal what that independent read gives.
2. For every agency, a route's `trips_on_date` (from trips.txt and the
   calendar) must equal the number of those trips found in the streamed
   stop_times.txt, so no active trip is missing from the scan.
3. STM's metro lines must be absent from routes and departures.
4. BC Transit's host serves neither HEAD nor byte ranges, so its zip is
   downloaded whole; Victoria's counts are checked against an independent
   `zipfile` read, the same way as Calgary's.

5. StatCan's national database (23-26-0003): the catalogue's statuses are
   checked (live overlaps named, TransLink excluded), then a capped sample
   of nested feeds (none over 15 MB compressed) is run through every tool,
   and Barrie's counts and one stop's departures are compared with an
   independent read that fetches the nested zip with plain httpx ranges
   and zlib/zipfile. Requests go one every two seconds, so this
   part takes a few minutes.

Pass agency keys as arguments to run only those (the independent
reconciliations run for the keys that have one); pass `national` to run
only the national part, or `national:<id>` keys for single national feeds.

The first scan of each agency streams tens of MB, so the run takes a few
minutes; the City of Toronto's host answers some requests with a transient
502 and the module retries them.
"""

from __future__ import annotations

import asyncio
import csv
import io
import struct
import sys
import zipfile
import zlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.transit import client, constants, national
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.remote_zip import ZipMember

# A point in each core, a search radius in metres, and the least routes and
# stops a real feed has (a sanity floor, not a count to match).
CORES: dict[str, tuple[float, float, int, int, int]] = {
    "calgary": (51.0447, -114.0719, 400, 50, 1000),
    "stm": (45.5088, -73.5540, 400, 50, 1000),
    "oc_transpo": (45.4215, -75.6972, 400, 50, 1000),
    "via_rail": (43.6453, -79.3806, 1000, 5, 100),
    "go_transit": (43.6453, -79.3806, 1000, 10, 100),
    "up_express": (43.6453, -79.3806, 1000, 1, 3),
    "bct_victoria": (48.4284, -123.3656, 400, 30, 1000),
    "bct_kelowna": (49.8880, -119.4960, 1500, 10, 300),
    "bct_kamloops": (50.6745, -120.3273, 1500, 10, 300),
    "bct_nanaimo": (49.1659, -123.9401, 1500, 10, 300),
    "bct_prince_george": (53.9171, -122.7497, 1500, 10, 300),
    "bct_fraser_valley": (49.1579, -121.9514, 1500, 10, 300),
    "bct_north_okanagan": (50.2670, -119.2720, 1500, 10, 200),
    "bct_comox_valley": (49.6735, -124.9028, 3000, 5, 200),
    "bct_cowichan_valley": (48.7787, -123.7079, 3000, 5, 100),
    "bct_campbell_river": (50.0244, -125.2475, 3000, 5, 100),
    "bct_squamish": (49.7016, -123.1558, 3000, 3, 50),
    "bct_whistler": (50.1163, -122.9574, 3000, 5, 100),
    "exo_trains": (45.4951, -73.5711, 1500, 5, 50),
    "exo_chambly_richelieu_carignan": (45.4495, -73.2878, 3000, 5, 100),
    "exo_laurentides": (45.7804, -74.0036, 3000, 5, 100),
    "exo_la_presquile": (45.4000, -74.0330, 3000, 5, 100),
    "exo_sorel_varennes": (45.6833, -73.4333, 3000, 5, 100),
    "exo_sud_ouest": (45.3800, -73.7500, 3000, 5, 100),
    "exo_vallee_du_richelieu": (45.5667, -73.2000, 3000, 5, 100),
    "exo_lassomption": (45.7422, -73.4500, 3000, 5, 100),
    "exo_terrebonne_mascouche": (45.7000, -73.6470, 3000, 5, 100),
    "exo_sainte_julie": (45.5833, -73.3333, 3000, 3, 50),
    "exo_le_richelain_roussillon": (45.4200, -73.4990, 3000, 5, 100),
    "rtc_quebec": (46.8139, -71.2080, 500, 50, 1000),
    "stl_laval": (45.5583, -73.7215, 500, 30, 1000),
    "sts_sherbrooke": (45.4042, -71.8929, 800, 20, 500),
    "stq_ferries": (46.8130, -71.2010, 2000, 3, 6),
    "sttr_trois_rivieres": (46.3432, -72.5477, 1000, 10, 300),
    "rimouski": (48.4490, -68.5230, 1500, 3, 50),
    "rouyn_noranda": (48.2366, -79.0230, 1500, 3, 50),
    "stsv_valleyfield": (45.2580, -74.1300, 2000, 3, 50),
}


def _independent_counts(key: str, day: date) -> dict[str, str | int]:
    """Counts for one agency from a full download, with plain csv and zipfile."""
    url = constants.AGENCIES[key].feed_url
    body = httpx.get(url, follow_redirects=True, timeout=300).content
    archive = zipfile.ZipFile(io.BytesIO(body))

    def rows(name: str) -> list[dict[str, str]]:
        with archive.open(name) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
            return [{k.strip(): v.strip() for k, v in r.items()} for r in csv.DictReader(text)]

    def active(on: date) -> set[str]:
        weekday = on.strftime("%A").lower()
        stamp = on.strftime("%Y%m%d")
        # BC Transit's feeds have no calendar.txt; service is calendar_dates only.
        ids = {
            r["service_id"]
            for r in (rows("calendar.txt") if "calendar.txt" in archive.namelist() else [])
            if r[weekday] == "1" and r["start_date"] <= stamp <= r["end_date"]
        }
        for r in rows("calendar_dates.txt"):
            if r["date"] == stamp:
                (ids.add if r["exception_type"] == "1" else ids.discard)(r["service_id"])
        return ids

    today, yesterday = active(day), active(day - timedelta(days=1))
    trip_service = {r["trip_id"]: r["service_id"] for r in rows("trips.txt")}
    stops = rows("stops.txt")
    # Every stop near the core: the first one can have no service on the probe day
    # (weekend-only or seasonal), so the busiest is checked instead.
    near = {
        r["stop_id"]
        for r in stops
        if abs(float(r["stop_lat"]) - CORES[key][0]) < 0.003
        and abs(float(r["stop_lon"]) - CORES[key][1]) < 0.003
    }
    counts: dict[str, int] = {}
    for r in rows("stop_times.txt"):
        if r["stop_id"] not in near:
            continue
        hours = int((r["departure_time"] or r["arrival_time"]).split(":")[0])
        service = trip_service.get(r["trip_id"])
        counts[r["stop_id"]] = (
            counts.get(r["stop_id"], 0)
            + (service in today)
            + (service in yesterday and hours >= 24)
        )
    target = max(near, key=lambda stop_id: (counts.get(stop_id, 0), stop_id))
    count = counts.get(target, 0)
    return {
        "routes": len(rows("routes.txt")),
        "stops": len(stops),
        "stop_id": target,
        "departures": count,
    }


NATIONAL_SAMPLE = (
    "barrie_transit",
    "winnipeg_transit",
    "halifax_transit",
    "saskatoon_transit",
    "edmonton_transit_service",
    "yellowknife_transit",
    "whitehorse_transit",
    "societe_transport_levis",
)
NATIONAL_MAX_MEMBER_BYTES = 15 * 1024 * 1024


def _mid_window_wednesday(start: date, end: date) -> date:
    day = start + timedelta(days=(end - start).days // 2)
    while day.weekday() != 2:
        day += timedelta(days=1)
    return day if day <= end else day - timedelta(days=7)


def _independent_national(member: ZipMember, day: date) -> dict[str, str | int]:
    """Counts from the nested zip fetched with httpx ranges and read with zipfile.

    Shares nothing with the module under test except the outer archive's
    central directory offsets.
    """
    url = constants.NATIONAL_URL
    # StatCan's network drops the TLS handshake of a client that does not offer
    # HTTP/2 in ALPN (AGENTS.md, "Three things that look removable").
    web = httpx.Client(http2=True, timeout=300)
    header = web.get(
        url, headers={"Range": f"bytes={member.header_offset}-{member.header_offset + 29}"}
    ).content
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = member.header_offset + 30 + name_len + extra_len
    body = web.get(
        url, headers={"Range": f"bytes={start}-{start + member.compressed_size - 1}"}
    ).content
    archive = zipfile.ZipFile(io.BytesIO(zlib.decompress(body, -15)))
    names = archive.namelist()

    def rows(name: str) -> list[dict[str, str]]:
        if name not in names:
            return []
        with archive.open(name) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
            return [{k.strip(): v.strip() for k, v in r.items()} for r in csv.DictReader(text)]

    def active(on: date) -> set[str]:
        weekday = on.strftime("%A").lower()
        stamp = on.strftime("%Y%m%d")
        ids = {
            r["service_id"]
            for r in rows("calendar.txt")
            if r[weekday] == "1" and r["start_date"] <= stamp <= r["end_date"]
        }
        for r in rows("calendar_dates.txt"):
            if r["date"] == stamp:
                (ids.add if r["exception_type"] == "1" else ids.discard)(r["service_id"])
        return ids

    today, yesterday = active(day), active(day - timedelta(days=1))
    trip_service = {r["trip_id"]: r["service_id"] for r in rows("trips.txt")}
    counts: dict[str, int] = {}
    for r in rows("stop_times.txt"):
        hours = int((r["departure_time"] or r["arrival_time"]).split(":")[0])
        service = trip_service.get(r["trip_id"])
        counts[r["stop_id"]] = (
            counts.get(r["stop_id"], 0)
            + (service in today)
            + (service in yesterday and hours >= 24)
        )
    busiest = max(counts, key=lambda k: counts[k])
    return {
        "routes": len(rows("routes.txt")),
        "stops": len(rows("stops.txt")),
        "stop_id": busiest,
        "departures": counts[busiest],
    }


async def national_checks(check: Callable[[bool, str], None], keys: list[str]) -> None:
    result = await client.list_national_agencies()
    by_key = {a.key: a for a in result.agencies}
    statuses = {
        s: sum(a.status == s for a in result.agencies)
        for s in ("available", "overlaps_live", "excluded")
    }
    check(
        result.total_matches >= 130,
        f"national catalogue lists {result.total_matches} feeds {statuses}",
    )
    check(
        statuses["overlaps_live"] == len(constants.NATIONAL_OVERLAPS)
        and all(by_key[f"national:{k}"].live_agency_key for k in constants.NATIONAL_OVERLAPS),
        "every configured overlap is in the catalogue and names its live agency",
    )
    check(
        by_key["national:translink_vancouver"].status == "excluded",
        "TransLink is excluded from the national feeds",
    )
    check(
        all(a.licence_url and a.attribution for a in result.agencies if a.status == "available"),
        "every available feed carries a licence page and an attribution line",
    )
    sample = keys or [f"national:{k}" for k in NATIONAL_SAMPLE]
    catalog = await client._load_national()
    for key in sample:
        member = catalog.members[national.member_path(key.removeprefix("national:"))]
        small = member.compressed_size <= NATIONAL_MAX_MEMBER_BYTES
        check(small, f"{key}: nested zip {member.compressed_size:,} bytes is within the smoke cap")
        if not small:
            continue
        agency = by_key[key]
        assert agency.service_window_start and agency.service_window_end
        day = _mid_window_wednesday(agency.service_window_start, agency.service_window_end)
        info = await client.get_feed_info(key)
        check(
            info.route_count > 0 and info.stop_count > 0,
            f"{key}: {info.route_count} routes, {info.stop_count} stops (window "
            f"{agency.service_window_start}..{agency.service_window_end}, probing {day})",
        )
        routes = await client.search_routes(key, limit=500)
        check(routes.total_matches == info.route_count, f"{key}: route search returns all routes")
        named = await client.search_stops(key, "a", limit=5)
        check(bool(named.stops), f"{key}: stop name search finds stops")
        stop = named.stops[0]
        departures = await client.get_stop_departures(
            key, stop.stop_id, service_date=str(day), start_time="00:00", limit=500
        )
        check(
            all(d.route_id for d in departures.departures),
            f"{key}: stop {stop.stop_id} has {departures.total_matches} departures on {day}",
        )
        candidates = [r for r in routes.routes if r.route_type in (2, 3)][:6]
        summary = await client.get_route_summary(key, candidates[0].route_id, service_date=str(day))
        for route in candidates[1:]:
            if summary.trips_on_date > 0:
                break
            summary = await client.get_route_summary(key, route.route_id, service_date=str(day))
        scanned = sum(h.trips for h in summary.hourly)
        check(
            summary.trips_on_date > 0 and scanned == summary.trips_on_date,
            f"{key}: route {summary.route.short_name or summary.route.long_name} runs "
            f"{summary.trips_on_date} trips on {day} ({scanned} found in stop_times)",
        )
        check(
            "Statistics Canada" in (summary.provenance.limits or "")
            and summary.provenance.url == constants.NATIONAL_URL,
            f"{key}: provenance names the StatCan compilation and the agency's own terms",
        )
    try:
        await client.search_routes("national:calgary_transit")
        check(False, "an overlapping national feed is refused")
    except InvalidInput as exc:
        check("agency='calgary'" in str(exc), "an overlapping national feed points to the live key")
    if "national:barrie_transit" in sample:
        barrie = by_key["national:barrie_transit"]
        assert barrie.service_window_start and barrie.service_window_end
        day = _mid_window_wednesday(barrie.service_window_start, barrie.service_window_end)
        barrie_zip = catalog.members[national.member_path("barrie_transit")]
        truth = await asyncio.to_thread(_independent_national, barrie_zip, day)
        info = await client.get_feed_info("national:barrie_transit")
        check(
            (info.route_count, info.stop_count) == (truth["routes"], truth["stops"]),
            f"barrie_transit: {info.route_count} routes / {info.stop_count} stops equal the "
            "independent read",
        )
        stop = await client.get_stop_departures(
            "national:barrie_transit",
            str(truth["stop_id"]),
            service_date=str(day),
            start_time="00:00",
            limit=500,
        )
        check(
            stop.total_matches == truth["departures"],
            f"barrie_transit stop {truth['stop_id']}: {stop.total_matches} departures equal "
            f"the independent count {truth['departures']}",
        )


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += not ok

    args = sys.argv[1:]
    national_keys = [a for a in args if a.startswith("national:")]
    only_national = "national" in args or bool(national_keys)
    keys = [a for a in args if a != "national" and not a.startswith("national:")]
    if not args:
        keys = list(CORES)
    agencies = await client.list_agencies()
    check(
        all(a.reachable for a in agencies.agencies if a.reachable is not None),
        f"all {agencies.total_matches} feeds answer a live probe (BC Transit's are not probed)",
    )
    check(
        set(CORES) == set(constants.AGENCIES),
        "the smoke test covers every configured agency",
    )

    for key in keys:
        lat, lon, radius, min_routes, min_stops = CORES[key]
        agency = constants.AGENCIES[key]
        today = datetime.now(ZoneInfo(agency.timezone)).date()
        info = await client.get_feed_info(key)
        covers = (info.feed_end_date is None or info.feed_end_date >= today) and (
            info.feed_start_date is None or info.feed_start_date <= today
        )
        check(covers, f"{key}: feed {info.feed_start_date}..{info.feed_end_date} covers {today}")
        check(
            info.route_count >= min_routes and info.stop_count >= min_stops,
            f"{key}: {info.route_count} routes, {info.stop_count} stops",
        )

        routes = await client.search_routes(key, limit=500)
        if agency.excluded_route_types:
            check(
                routes.total_matches < info.route_count,
                f"{key}: route search drops excluded lines "
                f"({routes.total_matches} of {info.route_count})",
            )
        else:
            check(
                routes.total_matches == info.route_count,
                f"{key}: route search returns all {info.route_count} routes",
            )

        near = await client.search_stops(
            key, near_latitude=lat, near_longitude=lon, radius_m=radius
        )
        check(bool(near.stops), f"{key}: {near.total_matches} stops within {radius} m of the core")

        # One stop at a time: each stop is a full pass over stop_times.txt
        # (tens of MB compressed for the large agencies), so scanning many is slow. Suburban
        # and small-town networks (exo's sectors) run little or nothing on
        # weekends, so a few nearby stops are tried, then the next Wednesday.
        weekday = today + timedelta(days=(2 - today.weekday()) % 7)
        day_label, service_date = "today", None
        best_stop, best = near.stops[0], None
        for when, label in ((None, "today"), (str(weekday), str(weekday))):
            for candidate in near.stops[:4]:
                result = await client.get_stop_departures(
                    key, candidate.stop_id, service_date=when, start_time="00:00", limit=500
                )
                if result.total_matches:
                    best_stop, best, day_label, service_date = candidate, result, label, when
                    break
            if best is not None:
                break
        check(
            best is not None,
            f"{key}: stop {best_stop.stop_id} ({best_stop.name}) has "
            f"{best.total_matches if best else 0} scheduled departures {day_label}",
        )
        if best is not None:
            times = [d.local_time for d in best.departures]
            check(len(best.departures) == min(best.total_matches, 500), f"{key}: listing size")
            check(
                all(d.route_id for d in best.departures),
                f"{key}: every departure names its route",
            )
            print(f"    first: {best.departures[0].route_short_name} {times[0]}")

        # Rail and small-town feeds have non-numeric names and few routes, so
        # the first routes that run on the date are tried instead of a numbered bus.
        # STQ's crossings are ferries (route_type 4).
        candidates = [r for r in routes.routes if r.route_type in (2, 3, 4)][:10]
        route = candidates[0]
        summary = await client.get_route_summary(key, route.route_id, service_date=service_date)
        for route in candidates[1:]:
            if summary.trips_on_date > 0:
                break
            summary = await client.get_route_summary(key, route.route_id, service_date=service_date)
        scanned = sum(h.trips for h in summary.hourly)
        check(
            summary.trips_on_date > 0 and scanned == summary.trips_on_date,
            f"{key}: route {summary.route.short_name or summary.route.long_name} runs "
            f"{summary.trips_on_date} trips {day_label} ({scanned} found in stop_times)",
        )

    # STM metro lines stay out of results.
    if "stm" in keys:
        metro = await client.search_routes("stm", route_type=1)
        check(metro.total_matches == 0, "stm: metro lines are not reported")

    # Calgary (range reads) and Victoria (whole-zip path) against a full independent download.
    for key in ("calgary", "bct_victoria"):
        if key not in keys:
            continue
        tz = ZoneInfo(constants.AGENCIES[key].timezone)
        truth = _independent_counts(key, datetime.now(tz).date())
        info = await client.get_feed_info(key)
        check(
            (info.route_count, info.stop_count) == (truth["routes"], truth["stops"]),
            f"{key}: {info.route_count} routes / {info.stop_count} stops "
            f"equal the full-download counts",
        )
        stop = await client.get_stop_departures(
            key, str(truth["stop_id"]), start_time="00:00", limit=500
        )
        check(
            stop.total_matches == truth["departures"],
            f"{key} stop {truth['stop_id']}: {stop.total_matches} departures "
            f"equal the independent count {truth['departures']}",
        )

    if not args or only_national:
        await national_checks(check, national_keys)

    print("TRANSIT SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
