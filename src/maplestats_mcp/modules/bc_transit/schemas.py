from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class VehiclePosition(BaseModel):
    vehicle_id: str | None
    route_id: str | None = Field(description="As in the feed and routes.txt: '55-VIC'.")
    route_short_name: str | None = Field(description="The number riders use: '55'.")
    trip_id: str | None
    trip_status: str | None = Field(description="SCHEDULED, ADDED, CANCELED, ...")
    direction_id: int | None
    start_date: str | None = Field(description="Service date of the trip, YYYYMMDD.")
    start_time: str | None = Field(description="Scheduled trip start, HH:MM:SS local.")
    latitude: float | None
    longitude: float | None
    bearing: float | None
    speed_kmh: float | None
    stop_id: str | None
    current_stop_sequence: int | None
    current_status: str | None = Field(description="STOPPED_AT, IN_TRANSIT_TO, INCOMING_AT.")
    occupancy_status: str | None = Field(
        description="EMPTY, MANY_SEATS_AVAILABLE, FEW_SEATS_AVAILABLE, STANDING_ROOM_ONLY, ..."
    )
    congestion_level: str | None
    timestamp: datetime | None


class VehiclePositions(BaseModel):
    system: str
    system_name: str
    feed_timestamp: datetime | None
    total_matches: int
    vehicles: list[VehiclePosition]
    provenance: Provenance


class StopTimePrediction(BaseModel):
    route_id: str | None
    route_short_name: str | None
    trip_id: str | None
    trip_status: str | None = Field(
        description="CANCELED means the bus will not run; its stops are listed as SKIPPED."
    )
    start_date: str | None
    stop_id: str | None
    stop_sequence: int | None
    stop_status: str | None = Field(description="SCHEDULED, SKIPPED or NO_DATA.")
    event: str = Field(description="departure, or arrival at a trip's last stop.")
    predicted_time: datetime | None
    delay_seconds: int | None = Field(description="Positive is late.")
    uncertainty_seconds: int | None = Field(
        description="As the feed gives it; mostly 0, even for running trips."
    )


class StopTimePredictions(BaseModel):
    system: str
    system_name: str
    feed_timestamp: datetime | None
    total_matches: int
    cancelled_trips: int = Field(description="Cancelled trips among the matches.")
    predictions: list[StopTimePrediction]
    provenance: Provenance


class AlertPeriod(BaseModel):
    start: datetime | None = Field(description="None when the period has no start.")
    end: datetime | None = Field(description="None when the period is open-ended.")


class ServiceAlert(BaseModel):
    alert_id: str
    header: str | None = Field(description="Often generic ('DETOUR'); read description.")
    description: str | None
    cause: str | None
    effect: str | None
    severity: str | None
    route_ids: list[str] = Field(description="As in the feed: '8-VIC'.")
    route_short_names: list[str]
    stop_ids: list[str]
    active_from: datetime | None = Field(
        description="Earliest start over active_periods; None if any period has no start."
    )
    active_until: datetime | None = Field(
        description="Latest end over active_periods; None if any period is open-ended."
    )
    active_periods: list[AlertPeriod] = Field(default_factory=list)


class ServiceAlerts(BaseModel):
    system: str
    system_name: str
    feed_timestamp: datetime | None
    total_matches: int
    alerts: list[ServiceAlert]
    provenance: Provenance
