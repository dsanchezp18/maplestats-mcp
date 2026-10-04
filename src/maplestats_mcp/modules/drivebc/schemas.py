from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class EventRoad(BaseModel):
    name: str | None
    from_point: str | None = Field(description="Where the event starts on the road ('from').")
    to_point: str | None = Field(description="Where it ends ('to'), when given.")
    direction: str | None = Field(description="BOTH, N, S, E, W, ... as published.")
    state: str | None = Field(description="Lane state, e.g. ALL_LANES_OPEN, SOME_LANES_CLOSED.")


class EventArea(BaseModel):
    area_id: str = Field(description="Open511 area id, e.g. 'drivebc.ca/1'.")
    name: str


class RoadEvent(BaseModel):
    event_id: str = Field(description="Open511 id, e.g. 'drivebc.ca/RIDE-102765'.")
    headline: str | None
    event_type: str
    subtypes: list[str]
    severity: str | None
    status: str | None
    description: str | None
    roads: list[EventRoad]
    areas: list[EventArea]
    created: datetime | None
    updated: datetime | None
    schedule: list[str] = Field(
        description="ISO 8601 intervals as published; an open end ('2026-09-24T18:02/') "
        "means no end time is set."
    )
    geometry_type: str | None = Field(description="Point or LineString.")
    latitude: float | None = Field(description="First point of the event's geometry.")
    longitude: float | None
    url: str


class EventSearch(BaseModel):
    total_active: int = Field(description="Active events in DriveBC's list before filtering.")
    total_matches: int
    events: list[RoadEvent]
    provenance: Provenance


class EventDetail(BaseModel):
    event: RoadEvent
    geometry: dict[str, Any] = Field(description="GeoJSON geometry (lon, lat order).")
    linear_reference_km: float | None
    provenance: Provenance


class EventCount(BaseModel):
    value: str
    events: int
    major: int = Field(description="Events of severity MAJOR in the group.")


class EventSummary(BaseModel):
    group_by: str
    total_matches: int
    groups: list[EventCount]
    provenance: Provenance


class Area(BaseModel):
    area_id: str
    name: str
    geonames_url: str | None
    active_events: int


class AreaList(BaseModel):
    areas: list[Area]
    provenance: Provenance
