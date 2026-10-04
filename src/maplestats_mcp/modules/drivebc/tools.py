"""MCP tools for DriveBC road events (BC provincial highways, Open511 API)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.drivebc import client, constants
from maplestats_mcp.modules.drivebc.schemas import (
    AreaList,
    EventDetail,
    EventSearch,
    EventSummary,
)

Lang = Literal["en", "fr"]
EventType = Literal[
    "CONSTRUCTION", "INCIDENT", "ROAD_CONDITION", "WEATHER_CONDITION", "SPECIAL_EVENT"
]
Severity = Literal["MINOR", "MODERATE", "MAJOR", "UNKNOWN"]
GroupBy = Literal["event_type", "severity", "area", "road", "subtype"]


@tool
async def drivebc_search_events(
    event_type: EventType | None = None,
    severity: Severity | None = None,
    subtype: str | None = None,
    area: str | None = None,
    road: str | None = None,
    bbox: list[float] | None = None,
    query: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> EventSearch:
    """Active road events on British Columbia's provincial highways from
    DriveBC (Open511): construction and maintenance, incidents (crashes,
    hazards, fires) and road conditions, each with severity, road, direction,
    lane state (for example CLOSED), schedule, district and location.

    Filters combine: event_type, severity (MAJOR for closures and big
    delays), subtype (ROAD_MAINTENANCE, HAZARD, FIRE, ...), area (district
    name or id such as 'Lower Mainland' or 'drivebc.ca/1'), road
    ('Highway 1', 'hwy 99' or '5'; numbers match exactly), bbox
    [min_lon, min_lat, max_lon, max_lat] and query (text in the
    description). MAJOR events come first, then the most recently updated.
    Municipal streets are not covered; text is English only.
    Use for: is a BC highway closed, current road work on the Coquihalla or
    Highway 1, incidents near a place, travel conditions in a district.
    Keywords: DriveBC, road closures, highway conditions, construction,
    incidents, British Columbia, Open511, traffic events, road work,
    Coquihalla, travel advisory.
    Mots-clés : DriveBC, fermetures de routes, état des routes, travaux
    routiers, incidents, Colombie-Britannique, Open511, circulation,
    entraves, autoroute, avis aux voyageurs.
    """
    del lang
    return await client.search_events(
        event_type=event_type,
        severity=severity,
        subtype=subtype,
        area=area,
        road=road,
        bbox=bbox,
        query=query,
        limit=limit,
    )


@tool
async def drivebc_get_event(event_id: str, lang: Lang = "en") -> EventDetail:
    """One active DriveBC road event in full, with its GeoJSON geometry
    (the point or the closed stretch of highway as a line) and the
    linear reference in km.

    event_id is the id from drivebc_search_events, with or without the
    'drivebc.ca/' prefix (for example 'drivebc.ca/RIDE-102765'). An event
    that has ended is no longer listed and gives a not-found error.
    Use for: the exact extent of a closure, map a road event, full text and
    schedule of one incident.
    Keywords: DriveBC, road event, closure extent, geometry, GeoJSON,
    incident detail, British Columbia highway, Open511, schedule.
    Mots-clés : DriveBC, événement routier, étendue de la fermeture,
    géométrie, GeoJSON, détail d'incident, route de la Colombie-Britannique,
    Open511, horaire.
    """
    del lang
    return await client.get_event(event_id)


@tool
async def drivebc_summarize_events(
    group_by: GroupBy = "area",
    event_type: EventType | None = None,
    severity: Severity | None = None,
    area: str | None = None,
    road: str | None = None,
    lang: Lang = "en",
) -> EventSummary:
    """Counts of active DriveBC road events grouped by district (area),
    event type, severity, road or subtype, with the number of MAJOR events
    in each group, after optional filters.

    Use for: which BC districts have the most road work, how many major
    incidents are open now, which highways have the most events.
    Keywords: DriveBC, road events count, closures by district, highway
    incidents summary, British Columbia, Open511, construction count,
    major events.
    Mots-clés : DriveBC, nombre d'événements routiers, fermetures par
    district, sommaire des incidents, Colombie-Britannique, Open511,
    nombre de chantiers, événements majeurs.
    """
    del lang
    return await client.summarize_events(
        group_by, event_type=event_type, severity=severity, area=area, road=road
    )


@tool
async def drivebc_list_areas(lang: Lang = "en") -> AreaList:
    """The 11 BC Ministry of Transportation and Transit districts DriveBC
    uses as Open511 areas (id, name, GeoNames link), with the number of
    active road events in each now.

    Pass an area id or name as `area` to drivebc_search_events or
    drivebc_summarize_events.
    Use for: the district names and ids for a DriveBC filter, which
    district a region belongs to, a quick count of events per district.
    Keywords: DriveBC, districts, areas, Lower Mainland, Vancouver Island,
    Okanagan, British Columbia, Open511, highway districts.
    Mots-clés : DriveBC, districts, zones, Lower Mainland, île de
    Vancouver, Okanagan, Colombie-Britannique, Open511, districts routiers.
    """
    del lang
    return await client.list_areas()
