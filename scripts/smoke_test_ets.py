"""Live smoke test for the Edmonton Transit Service GTFS-Realtime module."""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ets import client


async def main() -> int:
    failures = 0
    vehicles = await client.get_vehicle_positions(limit=3)
    print(f"OK: vehicles total={vehicles.total_matches} feed={vehicles.feed_timestamp}")
    print(f"    first={vehicles.vehicles[0] if vehicles.vehicles else None}")
    failures += not vehicles.vehicles or vehicles.vehicles[0].latitude is None

    route = next((v.route_id for v in vehicles.vehicles if v.route_id), None)
    if route:
        on_route = await client.get_vehicle_positions(route)
        print(f"OK: vehicles on route {route}: {on_route.total_matches}")
        failures += on_route.total_matches == 0
        predictions = await client.get_stop_predictions(route_id=route, limit=3)
        print(f"OK: predictions route {route} total={predictions.total_matches}")
        print(f"    first={predictions.predictions[0] if predictions.predictions else None}")
        failures += not predictions.predictions
        stop = predictions.predictions[0].stop_id if predictions.predictions else None
        if stop:
            at_stop = await client.get_stop_predictions(stop_id=stop, limit=5)
            print(f"OK: predictions at stop {stop}: {at_stop.total_matches}")
            failures += at_stop.total_matches == 0

    alerts = await client.get_service_alerts(limit=1000)
    print(f"OK: alerts total={alerts.total_matches}")
    print(f"    first={alerts.alerts[0].header if alerts.alerts else None}")
    tagged = next((a.route_ids[0] for a in alerts.alerts if a.route_ids), None)
    if tagged:
        by_route = await client.get_service_alerts(route_id=tagged)
        print(f"OK: alerts for route {tagged}: {by_route.total_matches}")
        failures += by_route.total_matches == 0

    print("ETS SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
