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

# A point in each downtown core, used to find a busy stop.
CORES = {
    "calgary": (51.0447, -114.0719),
    "stm": (45.5088, -73.5540),
    "oc_transpo": (45.4215, -75.6972),
    "ttc": (43.6532, -79.3832),
}


def _independent_calgary_counts(day: date) -> dict[str, str | int]:
    """Counts for Calgary from a full download, with plain csv and zipfile."""
    url = constants.AGENCIES["calgary"].feed_url
    body = httpx.get(url, follow_redirects=True, timeout=300).content
    archive = zipfile.ZipFile(io.BytesIO(body))

    def rows(name: str) -> list[dict[str, str]]:
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
    stops = rows("stops.txt")
    target = next(
        r
        for r in stops
        if abs(float(r["stop_lat"]) - CORES["calgary"][0]) < 0.003
        and abs(float(r["stop_lon"]) - CORES["calgary"][1]) < 0.003
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

    agencies = await client.list_agencies()
    check(
        all(a.reachable for a in agencies.agencies),
        f"all {agencies.total_matches} feeds answer a HEAD request",
    )

    for key, (lat, lon) in CORES.items():
        agency = constants.AGENCIES[key]
        today = datetime.now(ZoneInfo(agency.timezone)).date()
        info = await client.get_feed_info(key)
        covers = (info.feed_end_date is None or info.feed_end_date >= today) and (
            info.feed_start_date is None or info.feed_start_date <= today
        )
        check(covers, f"{key}: feed {info.feed_start_date}..{info.feed_end_date} covers {today}")
        check(
            info.route_count > 50 and info.stop_count > 1000,
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

        near = await client.search_stops(key, near_latitude=lat, near_longitude=lon, radius_m=400)
        check(bool(near.stops), f"{key}: {near.total_matches} stops within 400 m of the core")

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

        route = next(
            r
            for r in routes.routes
            if r.route_type == 3 and r.short_name and r.short_name.isdigit()
        )
        summary = await client.get_route_summary(key, route.route_id)
        scanned = sum(h.trips for h in summary.hourly)
        check(
            summary.trips_on_date > 0 and scanned == summary.trips_on_date,
            f"{key}: route {route.short_name} runs {summary.trips_on_date} trips today "
            f"({scanned} found in stop_times)",
        )

    # STM metro lines stay out of results.
    metro = await client.search_routes("stm", route_type=1)
    check(metro.total_matches == 0, "stm: metro lines are not reported")

    # Calgary against a full independent download.
    cal_today = datetime.now(ZoneInfo("America/Edmonton")).date()
    truth = _independent_calgary_counts(cal_today)
    cal_info = await client.get_feed_info("calgary")
    check(
        (cal_info.route_count, cal_info.stop_count) == (truth["routes"], truth["stops"]),
        f"calgary: {cal_info.route_count} routes / {cal_info.stop_count} stops "
        f"equal the full-download counts",
    )
    cal_stop = await client.get_stop_departures(
        "calgary", str(truth["stop_id"]), start_time="00:00", limit=500
    )
    check(
        cal_stop.total_matches == truth["departures"],
        f"calgary stop {truth['stop_id']}: {cal_stop.total_matches} departures "
        f"equal the independent count {truth['departures']}",
    )

    print("TRANSIT SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
