"""MCP tools for Edmonton Transit Service GTFS-Realtime feeds."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ets import client
from maplestats_mcp.modules.ets.schemas import (
    ServiceAlerts,
    StopTimePredictions,
    VehiclePositions,
)

Lang = Literal["en", "fr"]


@tool
async def ets_get_vehicle_positions(
    route_id: str | None = None, limit: int = 50, lang: Lang = "en"
) -> VehiclePositions:
    """Live positions of Edmonton Transit Service buses and LRT trains:
    latitude/longitude, bearing, speed (km/h), route, trip, and the stop
    each vehicle is at or approaching.

    route_id is the GTFS route id, which for ETS buses is the route
    number (e.g. "4", "922"). total_matches counts every match before
    limit (1-1000) is applied.
    Use for: where is my bus, how many buses are running on a route,
    live transit maps for Edmonton.
    Keywords: Edmonton, ETS, transit, bus, LRT, real-time, GTFS-RT,
    vehicle positions, live location, where is my bus, public
    transportation.
    Mots-clés : Edmonton, ETS, transport en commun, autobus, SLR, temps
    réel, GTFS-RT, position des véhicules, localisation en direct,
    transport public.
    """
    return await client.get_vehicle_positions(route_id, limit=limit, lang=lang)


@tool
async def ets_get_stop_predictions(
    stop_id: str | None = None,
    route_id: str | None = None,
    include_past: bool = False,
    limit: int = 50,
    lang: Lang = "en",
) -> StopTimePredictions:
    """Real-time predicted arrival/departure times at Edmonton Transit
    Service stops, with scheduled time and delay in seconds (positive =
    late), soonest first.

    Pass stop_id (the ETS stop number shown at the stop, e.g. "1321"),
    route_id (e.g. "4"), or both; at least one is required because the
    full feed covers ~1,200 active trips. Stops a trip has already
    served are dropped unless include_past is true. limit is 1-1000.
    Use for: next bus at a stop, how late a route is running, on-time
    performance snapshots.
    Keywords: Edmonton, ETS, next bus, arrival times, departures,
    delays, on-time performance, real-time, GTFS-RT, trip updates, bus
    stop, transit.
    Mots-clés : Edmonton, ETS, prochain autobus, heures d'arrivée,
    départs, retards, ponctualité, temps réel, GTFS-RT, arrêt
    d'autobus, transport en commun.
    """
    return await client.get_stop_predictions(
        stop_id, route_id, include_past=include_past, limit=limit, lang=lang
    )


@tool
async def ets_get_service_alerts(
    route_id: str | None = None,
    stop_id: str | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> ServiceAlerts:
    """Current Edmonton Transit Service alerts: detours, stop closures,
    and disruptions, with cause, effect, severity, affected routes and
    stops, and the active period. Alert text is English only.

    Optionally filter by route_id (e.g. "124") and/or stop_id. limit is
    1-1000.
    Use for: is my route on detour, closed stops, construction impacts
    on Edmonton transit.
    Keywords: Edmonton, ETS, service alerts, detours, stop closures,
    disruptions, construction, transit, bus, LRT, GTFS-RT.
    Mots-clés : Edmonton, ETS, avis de service, détours, fermetures
    d'arrêts, perturbations, travaux, transport en commun, autobus, SLR.
    """
    return await client.get_service_alerts(route_id, stop_id, limit=limit, lang=lang)
