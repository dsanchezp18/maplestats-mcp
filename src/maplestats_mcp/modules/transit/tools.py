"""MCP tools for static GTFS transit schedules: live agency feeds (STM, OC Transpo,
Calgary, VIA Rail, GO/UP Express, BC Transit, exo, RTC, STL, STS, STQ ferries and other
Quebec networks) and Statistics Canada's national database (2025)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.transit import client, constants
from maplestats_mcp.modules.transit.schemas import (
    AgencyList,
    AgencyRef,
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
    server reads (STM Montreal buses, OC Transpo Ottawa,
    Calgary Transit, VIA Rail, GO Transit, UP Express, twelve BC Transit
    systems such as Victoria, Kelowna and Kamloops, and in Quebec exo's
    commuter trains and ten bus sectors, RTC Québec City, STL Laval, STS
    Sherbrooke, STQ ferries, Trois-Rivières, Rimouski, Rouyn-Noranda and
    Salaberry-de-Valleyfield), with each feed's URL, licence, required
    attribution line, update cadence and a live check that the zip answers.
    STL Laval's own terms bar commercial use without its written permission.

    The key of each agency is what the other transit_ tools take as
    `agency`. TransLink (Vancouver) is not offered: its terms require
    users to identify themselves to TransLink first. For some 100 further
    agencies across Canada (a 2025 snapshot) use
    transit_list_national_agencies. BC Transit zips are built
    on request by BC Transit and downloaded whole, so a first call to one of
    its systems takes 5 to 30 seconds.
    Use for: which transit schedules are available, licence and credit
    line for a transit feed, is the agency's GTFS zip reachable.
    Keywords: transit, GTFS, static schedule, STM, OC Transpo,
    Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit, exo, RTC,
    STL, STS, ferries, Quebec, agencies, licence, attribution, bus, timetable data.
    Mots-clés : transport en commun, GTFS, horaire statique, STM,
    OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit,
    exo, RTC, STL, STS, traversiers, sociétés de transport du Québec,
    organismes, licence, attribution, autobus, données d'horaires.
    """
    return await client.list_agencies(lang=lang)


@tool
async def transit_list_national_agencies(
    query: str | None = None,
    province: str | None = None,
    status: Literal["available", "overlaps_live", "excluded"] | None = None,
    lang: Lang = "en",
) -> AgencyList:
    """The transit agencies in Statistics Canada's Canadian Public Transit
    Network Database (23-26-0003, a compilation of GTFS feeds from over 100
    agencies in every province and territory, version 1.0 released
    2025-01-31): name, province, the feed's service window, validator error
    and warning counts, and the licence page and attribution line Statistics Canada
    recorded for each.

    The key to pass as `agency` to the other transit_ tools is
    'national:<id>'. status says how a feed is handled: 'available' (read
    from the national archive), 'overlaps_live' (STM, OC Transpo,
    Calgary, VIA, GO, UP Express, BC Transit systems, exo, RTC, STL,
    Trois-Rivières, Rimouski and Rouyn-Noranda already read live: use
    live_agency_key) or 'excluded' (TransLink, and feeds with no
    licence or attribution recorded). This is a 2025 snapshot compiled by
    Statistics Canada: most service windows end in 2025, so pass a service_date inside
    the window. The compilation is under the Statistics Canada Open Licence;
    each feed also carries its own agency's terms (licence_url,
    attribution). The first call reads the archive's directory (about 15
    seconds, one request per two seconds as the host asks); a first feed
    download takes a few seconds more. Filter with query (name or id),
    province (two letters, for example ON) and status.
    Use for: Canadian transit agencies beyond the live feeds (Toronto among
    them), small-town and regional transit, which agencies a national
    transit database covers, transit licence and attribution lookup.
    Keywords: transit, public transit, GTFS, national database, Statistics
    Canada, 23-26-0003, Canadian Public Transit Network Database, agencies,
    regional transit, small town bus, Toronto, licence, attribution, 2025 snapshot.
    Mots-clés : transport en commun, GTFS, base de données nationale,
    Statistique Canada, 23-26-0003, Base de données du réseau de transport
    en commun canadien, organismes, transport régional, autobus, Toronto,
    licence, attribution, instantané 2025.
    """
    return await client.list_national_agencies(
        query=query, province=province, status=status, lang=lang
    )


@tool
async def transit_get_feed_info(agency: AgencyRef, lang: Lang = "en") -> FeedInfo:
    """One agency's GTFS feed: publisher, version, the dates the schedule
    covers, the number of routes and stops, and the size of each file in
    the zip.

    Read from the zip's own directory and small tables; the large
    stop_times file is not downloaded.
    Use for: how current is a transit schedule, how many routes and stops
    an agency has, what a GTFS feed contains.
    Keywords: transit, GTFS, feed info, schedule validity, feed version,
    routes count, stops count, STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit,
    static schedule.
    Mots-clés : transport en commun, GTFS, métadonnées du flux, validité
    de l'horaire, version du flux, nombre de lignes, nombre d'arrêts,
    STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit, horaire statique.
    """
    return await client.get_feed_info(agency, lang=lang)


@tool
async def transit_search_routes(
    agency: AgencyRef,
    query: str | None = None,
    route_type: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> RouteSearch:
    """Routes of an agency whose id, short name (route number), long name
    or description contain `query` (accent-insensitive); leave `query`
    empty to list them all.

    route_type is the GTFS code: 0 tram or light rail, 1 subway, 2 rail,
    3 bus, 4 ferry (STQ's crossings). STM's metro lines are not reported (its terms bar
    applications built on metro timetables). total_matches counts every
    match before limit (1-500) is applied.
    Use for: find a bus route number or name, list the LRT or subway
    lines, get the route_id for transit_get_route_summary.
    Keywords: transit, route, bus route, line number, LRT, subway,
    streetcar, GTFS routes, STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit.
    Mots-clés : transport en commun, ligne, ligne d'autobus, numéro de
    ligne, train léger, métro, tramway, lignes GTFS, STM, OC
    Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit.
    """
    return await client.search_routes(agency, query, route_type=route_type, limit=limit, lang=lang)


@tool
async def transit_search_stops(
    agency: AgencyRef,
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
    stop, coordinates, wheelchair accessible, GTFS stops, STM, OC
    Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit.
    Mots-clés : transport en commun, arrêt, arrêt d'autobus, station,
    arrêts à proximité, arrêt le plus proche, coordonnées, accessible en
    fauteuil roulant, arrêts GTFS, STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit.
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
    agency: AgencyRef,
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
    times, GTFS stop_times, service date, STM, OC Transpo, Calgary
    Transit, VIA Rail, GO Transit, UP Express, BC Transit, scheduled arrival.
    Mots-clés : transport en commun, horaire, passages prévus, prochain
    autobus, heures de passage, stop_times GTFS, date de service,
    STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit, heure d'arrivée prévue.
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
    agency: AgencyRef,
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
    trips per day, stops served, GTFS, STM, OC Transpo, Calgary
    Transit, VIA Rail, GO Transit, UP Express, BC Transit, bus frequency.
    Mots-clés : transport en commun, résumé de ligne, fréquence,
    intervalle entre passages, heures de service, voyages par jour,
    arrêts desservis, GTFS, STM, OC Transpo, Calgary Transit, VIA Rail, GO Transit, UP Express, BC Transit.
    """
    return await client.get_route_summary(agency, route, service_date=service_date, lang=lang)
