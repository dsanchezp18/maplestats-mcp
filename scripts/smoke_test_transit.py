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

Pass agency keys as arguments to run only those (the independent
reconciliations run for the keys that have one).

The first scan of each agency streams tens of MB, so the run takes a few
minutes; the City of Toronto's host answers some requests with a transient
502 and the module retries them.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
import zipfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.transit import client, constants

# A point in each core, a search radius in metres, and the least routes and
# stops a real feed has (a sanity floor, not a count to match).
CORES: dict[str, tuple[float, float, int, int, int]] = {
    "calgary": (51.0447, -114.0719, 400, 50, 1000),
    "stm": (45.5088, -73.5540, 400, 50, 1000),
    "oc_transpo": (45.4215, -75.6972, 400, 50, 1000),
    "ttc": (43.6532, -79.3832, 400, 50, 1000),
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
    target = next(
        r
        for r in stops
        if abs(float(r["stop_lat"]) - CORES[key][0]) < 0.003
        and abs(float(r["stop_lon"]) - CORES[key][1]) < 0.003
    )["stop_id"]
    count = 0
    for r in rows("stop_times.txt"):
        if r["stop_id"] != target:
            continue
        hours = int((r["departure_time"] or r["arrival_time"]).split(":")[0])
        service = trip_service.get(r["trip_id"])
        count += service in today
        count += service in yesterday and hours >= 24
    return {
        "routes": len(rows("routes.txt")),
        "stops": len(stops),
        "stop_id": target,
        "departures": count,
    }


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += not ok

    keys = sys.argv[1:] or list(CORES)
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

        # One stop only: each stop is a full pass over stop_times.txt
        # (71 MB compressed for the TTC), so scanning more is slow.
        best_stop = near.stops[0]
        best = await client.get_stop_departures(
            key, best_stop.stop_id, start_time="00:00", limit=500
        )
        check(
            best.total_matches > 0,
            f"{key}: stop {best_stop.stop_id} ({best_stop.name}) has "
            f"{best.total_matches} scheduled departures today",
        )
        times = [d.local_time for d in best.departures]
        check(len(best.departures) == min(best.total_matches, 500), f"{key}: listing size")
        check(
            all(d.route_id for d in best.departures),
            f"{key}: every departure names its route",
        )
        print(f"    first: {best.departures[0].route_short_name} {times[0]}")

        # Rail and small-town feeds have non-numeric names and few routes, so
        # the first routes that run today are tried instead of a numbered bus.
        candidates = [r for r in routes.routes if r.route_type in (2, 3)][:5]
        route = candidates[0]
        summary = await client.get_route_summary(key, route.route_id)
        for route in candidates[1:]:
            if summary.trips_on_date > 0:
                break
            summary = await client.get_route_summary(key, route.route_id)
        scanned = sum(h.trips for h in summary.hourly)
        check(
            summary.trips_on_date > 0 and scanned == summary.trips_on_date,
            f"{key}: route {route.short_name or route.long_name} runs "
            f"{summary.trips_on_date} trips today ({scanned} found in stop_times)",
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

    print("TRANSIT SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
