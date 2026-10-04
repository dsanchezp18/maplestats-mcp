from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

AgencyKey = Literal[
    "stm",
    "oc_transpo",
    "calgary",
    "via_rail",
    "go_transit",
    "up_express",
    "bct_victoria",
    "bct_kelowna",
    "bct_kamloops",
    "bct_nanaimo",
    "bct_prince_george",
    "bct_fraser_valley",
    "bct_north_okanagan",
    "bct_comox_valley",
    "bct_cowichan_valley",
    "bct_campbell_river",
    "bct_squamish",
    "bct_whistler",
    "exo_trains",
    "exo_chambly_richelieu_carignan",
    "exo_laurentides",
    "exo_la_presquile",
    "exo_sorel_varennes",
    "exo_sud_ouest",
    "exo_vallee_du_richelieu",
    "exo_lassomption",
    "exo_terrebonne_mascouche",
    "exo_sainte_julie",
    "exo_le_richelain_roussillon",
    "rtc_quebec",
    "stl_laval",
    "sts_sherbrooke",
    "stq_ferries",
    "sttr_trois_rivieres",
    "rimouski",
    "rouyn_noranda",
    "stsv_valleyfield",
]

# A live agency key (AgencyKey) or "national:<id>" from the Statistics Canada national database.
AgencyRef = Annotated[
    str,
    Field(
        description="Agency key from transit_list_agencies (for example 'stm', 'calgary', "
        "'bct_victoria'), or 'national:<id>' for an agency of the 2025 Statistics Canada national "
        "database (ids from transit_list_national_agencies)."
    ),
]


class AgencyFeed(BaseModel):
    key: str = Field(description="Value to pass as `agency` to the other transit_ tools.")
    name: str = Field(description="Agency name in the requested language.")
    name_en: str
    name_fr: str
    city: str
    province: str
    timezone: str = Field(description="IANA timezone the schedule's local times refer to.")
    feed_url: str = Field(description="The static GTFS zip this module reads.")
    source_page: str
    licence: str
    licence_url: str
    attribution: str = Field(description="Credit line to show when republishing the data.")
    update_cadence: str
    notes: str | None
    reachable: bool | None = Field(
        description="Whether the zip answered a HEAD request now; null when the host "
        "builds the zip on request and is not probed."
    )
    zip_bytes: int | None = Field(description="Size of the zip, from Content-Length.")
    last_modified: datetime | None = Field(description="Last-Modified header of the zip.")
    database: str = Field(
        default="live",
        description="'live' for a feed read from the agency's own site, 'national' for an "
        "agency inside Statistics Canada's Canadian Public Transit Network Database (key 'national:<id>').",
    )
    status: str = Field(
        default="available",
        description="'available', 'overlaps_live' (listed only: use live_agency_key) or "
        "'excluded' (see status_reason).",
    )
    status_reason: str | None = None
    live_agency_key: str | None = Field(
        default=None, description="For 'overlaps_live': the live key that serves the same agency."
    )
    service_window_start: date | None = Field(
        default=None,
        description="First service date the Statistics Canada validator found in the feed.",
    )
    service_window_end: date | None = Field(
        default=None,
        description="Last service date the Statistics Canada validator found in the feed.",
    )
    validator_errors: int | None = Field(
        default=None,
        description="ERROR notices from MobilityData's GTFS validator (Statistics Canada run).",
    )
    validator_warnings: int | None = Field(default=None, description="WARNING notices, same run.")


class AgencyList(BaseModel):
    total_matches: int
    agencies: list[AgencyFeed]
    provenance: Provenance


class FeedFile(BaseModel):
    name: str
    compressed_bytes: int
    uncompressed_bytes: int


class FeedInfo(BaseModel):
    agency: AgencyFeed
    publisher_name: str | None
    feed_version: str | None
    feed_start_date: date | None
    feed_end_date: date | None
    agency_names: list[str] = Field(description="Names in the feed's own agency.txt.")
    route_count: int
    stop_count: int
    files: list[FeedFile]
    provenance: Provenance


class RouteRecord(BaseModel):
    route_id: str
    short_name: str | None
    long_name: str | None
    route_type: int | None
    route_type_name: str | None
    description: str | None
    color: str | None


class RouteSearch(BaseModel):
    agency: str
    query: str | None
    total_matches: int
    routes: list[RouteRecord]
    provenance: Provenance


class StopRecord(BaseModel):
    stop_id: str
    stop_code: str | None
    name: str
    latitude: float | None
    longitude: float | None
    location_type: int | None = Field(
        description="0 stop/platform, 1 station, 2 entrance, 3 generic node, 4 boarding area."
    )
    parent_station: str | None
    wheelchair_boarding: int | None = Field(
        description="0 unknown, 1 accessible, 2 not accessible (GTFS wheelchair_boarding)."
    )
    distance_m: float | None = Field(description="Distance from the search point, when given.")


class StopSearch(BaseModel):
    agency: str
    query: str | None
    total_matches: int
    stops: list[StopRecord]
    provenance: Provenance


class Departure(BaseModel):
    route_id: str | None
    route_short_name: str | None
    route_long_name: str | None
    headsign: str | None
    direction_id: int | None
    trip_id: str
    stop_id: str
    stop_sequence: int | None
    arrival_time: str | None = Field(description="GTFS time HH:MM:SS as published; can pass 24:00.")
    departure_time: str = Field(description="GTFS time HH:MM:SS as published; can pass 24:00.")
    local_time: str = Field(
        description="Local clock time HH:MM:SS on the requested date (24h wrapped to 00-23)."
    )
    after_midnight_of_previous_service_day: bool = Field(
        description="True for a trip of the previous service day that runs past 24:00."
    )


class StopDepartures(BaseModel):
    agency: str
    stop: StopRecord
    stop_ids_included: list[str] = Field(
        description="The stop plus, for a station, its child platforms."
    )
    service_date: date
    from_time: str
    total_matches: int
    departures: list[Departure]
    provenance: Provenance


class DirectionSummary(BaseModel):
    direction_id: int | None
    headsigns: list[str]
    trips: int
    first_departure: str | None
    last_departure: str | None


class HourlyFrequency(BaseModel):
    direction_id: int | None
    hour: int = Field(
        description="Service-day hour of the first-stop departure; 24+ is after midnight."
    )
    trips: int
    average_headway_minutes: float | None = Field(
        description="60 divided by trips in the hour; None when there is only one trip."
    )


class RouteSummary(BaseModel):
    agency: str
    route: RouteRecord
    service_date: date
    trips_in_feed: int = Field(description="Trips of this route over the whole feed period.")
    trips_on_date: int
    distinct_stop_ids: int = Field(description="Stop ids served by the route's trips on the date.")
    distinct_stations: int = Field(
        description="Same stops with platforms merged into their parent station."
    )
    distinct_stop_names: int
    directions: list[DirectionSummary]
    hourly: list[HourlyFrequency]
    provenance: Provenance
