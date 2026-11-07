"""MCP tools for BC Transit GTFS-Realtime feeds."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bc_transit import client
from maplestats_mcp.modules.bc_transit.schemas import (
    ServiceAlerts,
    StopTimePredictions,
    VehiclePositions,
)

Lang = Literal["en", "fr"]


@tool
async def bc_transit_get_vehicle_positions(
    system: str, route_id: str | None = None, limit: int = 50, lang: Lang = "en"
) -> VehiclePositions:
    """Live positions of BC Transit buses in one system: latitude/longitude,
    bearing, speed (km/h), route, trip, the stop each bus is at or
    approaching, and how full it is (occupancy_status).

    system is one of bct_victoria, bct_kelowna, bct_kamloops, bct_nanaimo,
    bct_prince_george, bct_fraser_valley, bct_north_okanagan,
    bct_comox_valley, bct_cowichan_valley, bct_campbell_river,
    bct_squamish, bct_whistler ("victoria" works too); the same keys as
    transit_* for the schedules. route_id is the route number ("55") or
    the feed's id ("55-VIC"). total_matches counts every match before
    limit (1-1000). Not TransLink (Metro Vancouver).
    Use for: where is my bus in Victoria or Kelowna, how many buses are on
    a route, how crowded a bus is, live transit maps in BC.
    Keywords: BC Transit, Victoria, Kelowna, Kamloops, Nanaimo, Whistler,
    bus, real-time, GTFS-RT, vehicle positions, live location, where is
    my bus, occupancy, British Columbia transit.
    Mots-clés : BC Transit, Victoria, Kelowna, Nanaimo, autobus, temps
    réel, GTFS-RT, position des autobus, localisation en direct, où est
    mon autobus, achalandage, transport en commun, Colombie-Britannique.
    """
    return await client.get_vehicle_positions(system, route_id, limit=limit, lang=lang)


@tool
async def bc_transit_get_stop_predictions(
    system: str,
    stop_id: str | None = None,
    route_id: str | None = None,
    include_past: bool = False,
    include_cancelled: bool = True,
    limit: int = 50,
    lang: Lang = "en",
) -> StopTimePredictions:
    """Real-time predicted departure times at BC Transit stops, with delay
    in seconds (positive = late), soonest first, and cancelled trips
    flagged (trip_status CANCELED, stop_status SKIPPED: that bus will not
    come).

    system as in bc_transit_get_vehicle_positions (e.g. "bct_victoria").
    Pass stop_id (the 6-digit stop number at the stop, e.g. "100715"),
    route_id ("55" or "55-VIC"), or both. Stops already served are dropped
    unless include_past is true; include_cancelled=false drops cancelled
    trips. A trip not yet started repeats its schedule (delay 0).
    limit is 1-1000.
    Use for: next bus at a stop in Victoria, Kelowna or Nanaimo, is my bus
    late or cancelled, how late a route is running.
    Keywords: BC Transit, next bus, arrival times, departures, delays,
    cancelled trips, real-time, GTFS-RT, trip updates, bus stop, Victoria,
    Kelowna.
    Mots-clés : BC Transit, prochain autobus, heures de passage, départs,
    retards, trajets annulés, temps réel, GTFS-RT, arrêt d'autobus,
    Victoria, Kelowna, Colombie-Britannique.
    """
    return await client.get_stop_predictions(
        system,
        stop_id,
        route_id,
        include_past=include_past,
        include_cancelled=include_cancelled,
        limit=limit,
        lang=lang,
    )


@tool
async def bc_transit_get_service_alerts(
    system: str,
    route_id: str | None = None,
    stop_id: str | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> ServiceAlerts:
    """Current BC Transit service alerts in one system: detours, stop
    closures and disruptions, with cause, effect, severity, affected routes
    and stops, and active periods. The header is often only "DETOUR"; the
    description has the detail. Alert text is English only.

    system as in bc_transit_get_vehicle_positions (e.g. "bct_kelowna").
    Optionally filter by route_id ("8" or "8-VIC") and/or stop_id.
    limit is 1-1000.
    Use for: is my route on detour, closed stops, construction affecting
    buses in Victoria, Kelowna, Kamloops or Nanaimo.
    Keywords: BC Transit, service alerts, detours, stop closures,
    disruptions, construction, bus, GTFS-RT, Victoria, Kelowna,
    British Columbia.
    Mots-clés : BC Transit, avis de service, alertes, détours,
    déviations, fermetures d'arrêts, perturbations, travaux, autobus,
    Colombie-Britannique.
    """
    return await client.get_service_alerts(system, route_id, stop_id, limit=limit, lang=lang)
