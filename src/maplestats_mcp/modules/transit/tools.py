"""MCP tools for static GTFS transit schedules (TTC, STM, OC Transpo, Calgary)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.transit import client, constants
from maplestats_mcp.modules.transit.schemas import (
    AgencyKey,
    AgencyList,
    FeedInfo,
    RouteSearch,
    RouteSummary,
    StopDepartures,
    StopSearch,
)

Lang = Literal["en", "fr"]


@tool
async def transit_list_agencies(lang: Lang = "en") -> AgencyList:
    """The transit agencies whose published static GTFS schedule this
    server reads (TTC Toronto, STM Montreal buses, OC Transpo Ottawa,
    Calgary Transit), with each feed's URL, licence, required attribution
    line, update cadence and a live check that the zip answers.

    The key of each agency is what the other transit_ tools take as
    `agency`. TransLink (Vancouver) is not offered: its terms require
    users to identify themselves to TransLink first.
    Use for: which transit schedules are available, licence and credit
    line for a transit feed, is the agency's GTFS zip reachable.
    Keywords: transit, GTFS, static schedule, TTC, STM, OC Transpo,
    Calgary Transit, agencies, licence, attribution, bus, timetable
    data.
    Mots-clés : transport en commun, GTFS, horaire statique, TTC, STM,
    OC Transpo, Calgary Transit, organismes, licence, attribution,
    autobus, données d'horaires.
    """
    return await client.list_agencies(lang=lang)


@tool
async def transit_get_feed_info(agency: AgencyKey, lang: Lang = "en") -> FeedInfo:
    """One agency's GTFS feed: publisher, version, the dates the schedule
    covers, the number of routes and stops, and the size of each file in
    the zip.

    Read from the zip's own directory and small tables; the large
    stop_times file is not downloaded.
    Use for: how current is a transit schedule, how many routes and stops
    an agency has, what a GTFS feed contains.
    Keywords: transit, GTFS, feed info, schedule validity, feed version,
    routes count, stops count, TTC, STM, OC Transpo, Calgary Transit,
    static schedule.
    Mots-clés : transport en commun, GTFS, métadonnées du flux, validité
    de l'horaire, version du flux, nombre de lignes, nombre d'arrêts,
    TTC, STM, OC Transpo, Calgary Transit, horaire statique.
    """
    return await client.get_feed_info(agency, lang=lang)


@tool
async def transit_search_routes(
    agency: AgencyKey,
    query: str | None = None,
    route_type: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> RouteSearch:
    """Routes of an agency whose id, short name (route number), long name
    or description contain `query` (accent-insensitive); leave `query`
    empty to list them all.

    route_type is the GTFS code: 0 tram or light rail, 1 subway, 2 rail,
    3 bus, 4 ferry. STM's metro lines are not reported (its terms bar
    applications built on metro timetables). total_matches counts every
    match before limit (1-500) is applied.
    Use for: find a bus route number or name, list the LRT or subway
    lines, get the route_id for transit_get_route_summary.
    Keywords: transit, route, bus route, line number, LRT, subway,
    streetcar, GTFS routes, TTC, STM, OC Transpo, Calgary Transit.
    Mots-clés : transport en commun, ligne, ligne d'autobus, numéro de
    ligne, train léger, métro, tramway, lignes GTFS, TTC, STM, OC
    Transpo, Calgary Transit.
    """
    return await client.search_routes(agency, query, route_type=route_type, limit=limit, lang=lang)


@tool
async def transit_search_stops(
    agency: AgencyKey,
    query: str | None = None,
    near_latitude: float | None = None,
    near_longitude: float | None = None,
    radius_m: float = 500.0,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> StopSearch:
    """Stops of an agency by name, public stop code or id (accent-
    insensitive), and/or within radius_m metres of a latitude/longitude,
    nearest first; at least one of query or a point is required.

    Each stop has its id, code, coordinates, parent station and wheelchair
    boarding flag. Pass the stop_id (or the code printed at the stop) to
    transit_get_stop_departures. total_matches counts every match before
    limit (1-500) is applied.
    Use for: find a transit stop or station, stops near an address,
    accessible stops, the stop number for a departures lookup.
    Keywords: transit, stop, bus stop, station, stops near me, nearest
    stop, coordinates, wheelchair accessible, GTFS stops, TTC, STM, OC
    Transpo, Calgary Transit.
    Mots-clés : transport en commun, arrêt, arrêt d'autobus, station,
    arrêts à proximité, arrêt le plus proche, coordonnées, accessible en
    fauteuil roulant, arrêts GTFS, TTC, STM, OC Transpo, Calgary Transit.
    """
    return await client.search_stops(
        agency,
        query,
        near_latitude=near_latitude,
        near_longitude=near_longitude,
        radius_m=radius_m,
        limit=limit,
        lang=lang,
    )


@tool
async def transit_get_stop_departures(
    agency: AgencyKey,
    stop: str,
    service_date: str | None = None,
    start_time: str | None = None,
    route: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> StopDepartures:
    """Scheduled (timetable, not real-time) departures at one stop on a
    service date: route, headsign, trip and the time, soonest first. A
    station id includes its child platforms.

    stop is a stop_id or public stop code. service_date is YYYY-MM-DD in
    the agency's local calendar (default today); start_time is HH:MM
    (default now when the date is today, else midnight); route filters to
    one route number or id. Trips that began the previous service day and
    run past midnight are included and flagged. The first call for a stop
    streams the agency's stop_times file (tens of MB) and can take
    from several seconds to a minute; later calls for it are cached. limit is 1-500.
    Use for: when is the next bus at a stop, the timetable of a stop on a
    date, how often a stop is served, first and last service.
    Keywords: transit, schedule, timetable, departures, next bus, stop
    times, GTFS stop_times, service date, TTC, STM, OC Transpo, Calgary
    Transit, scheduled arrival.
    Mots-clés : transport en commun, horaire, passages prévus, prochain
    autobus, heures de passage, stop_times GTFS, date de service, TTC,
    STM, OC Transpo, Calgary Transit, heure d'arrivée prévue.
    """
    return await client.get_stop_departures(
        agency,
        stop,
        service_date=service_date,
        start_time=start_time,
        route=route,
        limit=limit,
        lang=lang,
    )


@tool
async def transit_get_route_summary(
    agency: AgencyKey,
    route: str,
    service_date: str | None = None,
    lang: Lang = "en",
) -> RouteSummary:
    """A route's service on one date: trips run, first and last departure
    and headsigns per direction, stops served (as stop ids, parent
    stations and distinct names) and the number of trips and average
    headway (minutes between buses) by hour of the day.

    route is a route number (short name) or route_id; service_date is
    YYYY-MM-DD in the agency's local calendar (default today). Counts are
    scheduled trips from the static timetable, not real-time. The first
    call for a route streams the agency's stop_times file (tens of MB)
    and can take from several seconds to a minute.
    Use for: how frequent is a bus route, hours of service, how many
    trips a route runs per day, how many stops a line has.
    Keywords: transit, route summary, frequency, headway, service hours,
    trips per day, stops served, GTFS, TTC, STM, OC Transpo, Calgary
    Transit, bus frequency.
    Mots-clés : transport en commun, résumé de ligne, fréquence,
    intervalle entre passages, heures de service, voyages par jour,
    arrêts desservis, GTFS, TTC, STM, OC Transpo, Calgary Transit.
    """
    return await client.get_route_summary(agency, route, service_date=service_date, lang=lang)
