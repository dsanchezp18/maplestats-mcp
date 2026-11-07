"""Live smoke test for the BC Transit GTFS-Realtime module.

Every system's three feeds are read; Victoria also checks the route and
stop filters against what the unfiltered feed holds.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.bc_transit import client, constants


async def main() -> int:
    failures = 0
    for key in constants.SYSTEMS:
        vehicles = await client.get_vehicle_positions(key, limit=1000)
        alerts = await client.get_service_alerts(key, limit=1000)
        route = next((v.route_short_name for v in vehicles.vehicles if v.route_short_name), None)
        predictions = (
            await client.get_stop_predictions(key, route_id=route, limit=1000) if route else None
        )
        print(
            f"OK: {key}: vehicles={vehicles.total_matches} alerts={alerts.total_matches} "
            f"route {route} predictions={predictions.total_matches if predictions else '-'} "
            f"cancelled={predictions.cancelled_trips if predictions else '-'}"
        )
        # A system with no bus out (late night) is not a failure; a bad feed raises.
        failures += vehicles.feed_timestamp is None

    key = "bct_victoria"
    vehicles = await client.get_vehicle_positions(key, limit=1000)
    print(f"    first vehicle={vehicles.vehicles[0] if vehicles.vehicles else None}")
    if vehicles.vehicles:
        failures += vehicles.vehicles[0].latitude is None
        route = vehicles.vehicles[0].route_short_name or ""
        expected = sum(v.route_short_name == route for v in vehicles.vehicles)
        on_route = await client.get_vehicle_positions(key, route)
        print(f"OK: vehicles on route {route}: {on_route.total_matches} (expected {expected})")
        failures += on_route.total_matches != expected
        predictions = await client.get_stop_predictions(key, route_id=route, limit=5)
        print(
            f"    first prediction={predictions.predictions[0] if predictions.predictions else None}"
        )
        failures += not predictions.predictions
        stop = predictions.predictions[0].stop_id if predictions.predictions else None
        if stop:
            at_stop = await client.get_stop_predictions(key, stop_id=stop, limit=5)
            print(f"OK: predictions at stop {stop}: {at_stop.total_matches}")
            failures += at_stop.total_matches == 0 or any(
                p.stop_id != stop for p in at_stop.predictions
            )

    alerts = await client.get_service_alerts(key, limit=1000)
    print(f"    first alert={alerts.alerts[0].header if alerts.alerts else None}")
    tagged = next((a.route_short_names[0] for a in alerts.alerts if a.route_short_names), None)
    if tagged:
        by_route = await client.get_service_alerts(key, route_id=tagged)
        print(f"OK: alerts for route {tagged}: {by_route.total_matches}")
        failures += by_route.total_matches == 0

    print("BC TRANSIT SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
