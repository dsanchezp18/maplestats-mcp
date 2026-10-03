"""Live smoke test for the DriveBC Open511 module.

Every tool is called against api.open511.gov.bc.ca. The host rate-limits
hard (about one request every five seconds), so the module fetches the
active list once and filters it in memory; this script makes one extra
independent request to check that list against the API's own filters.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from maplestats_mcp.modules.drivebc import client, constants


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += not ok

    everything = await client.search_events(limit=500)
    check(everything.total_active > 20, f"{everything.total_active} active events")
    check(
        everything.total_matches == len(everything.events) == everything.total_active,
        "an unfiltered search returns every active event",
    )
    check(
        all(e.event_id and e.event_type and e.latitude and e.longitude for e in everything.events),
        "every event has an id, a type and a location",
    )
    lats_ok = all(48 <= (e.latitude or 0) <= 60.1 for e in everything.events)
    lons_ok = all(-139.1 <= (e.longitude or 0) <= -114 for e in everything.events)
    check(lats_ok and lons_ok, "every first point is in British Columbia (lat/lon not swapped)")

    # Independent check: the API's own severity filter, after the rate-limit pause.
    await asyncio.sleep(6)
    async with httpx.AsyncClient(timeout=60) as web:
        upstream = await web.get(
            constants.EVENTS_URL,
            params={"format": "json", "status": "ACTIVE", "severity": "MAJOR", "limit": 500},
        )
    major = await client.search_events(severity="MAJOR", limit=500)
    if upstream.status_code == 200:
        ids = {e["id"] for e in upstream.json()["events"]}
        check(
            {e.event_id for e in major.events} == ids,
            f"MAJOR filter in memory ({major.total_matches}) equals the API's own filter "
            f"({len(ids)})",
        )
    else:
        check(False, f"independent MAJOR request answered HTTP {upstream.status_code}")

    highway1 = await client.search_events(road="Highway 1", limit=500)
    check(
        all(any(r.name == "Highway 1" for r in e.roads) for e in highway1.events),
        f"road='Highway 1' gives {highway1.total_matches} events, none on Highway 16 or 19",
    )
    lower = await client.search_events(area="Lower Mainland", limit=500)
    check(lower.total_matches > 0, f"{lower.total_matches} events in the Lower Mainland")
    box = await client.search_events(bbox=[-123.45, 48.99, -122.45, 49.49], limit=500)
    check(box.total_matches > 0, f"{box.total_matches} events in the Greater Vancouver box")

    first = everything.events[0]
    detail = await client.get_event(first.event_id)
    check(
        detail.geometry.get("type") in ("Point", "LineString"),
        f"{first.event_id}: geometry {detail.geometry.get('type')}",
    )

    summary = await client.summarize_events("event_type")
    check(
        sum(g.events for g in summary.groups) == summary.total_matches == everything.total_active,
        f"counts by type {[(g.value, g.events) for g in summary.groups]} add up",
    )
    by_area = await client.summarize_events("area")
    areas = await client.list_areas()
    check(len(areas.areas) == 11, f"{len(areas.areas)} districts")
    check(
        sum(a.active_events for a in areas.areas) == sum(g.events for g in by_area.groups),
        "district counts in list_areas equal the area summary",
    )
    check(
        all(
            "Open Government Licence - British Columbia" in (r.provenance.licence or "")
            for r in (everything, detail, summary, areas)
        ),
        "every result carries the OGL-BC licence",
    )

    print("DRIVEBC SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
