from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class VehiclePosition(BaseModel):
    vehicle_id: str | None
    vehicle_label: str | None
    route_id: str | None
    trip_id: str | None
    direction_id: int | None
    latitude: float | None
    longitude: float | None
    bearing: float | None
    speed_kmh: float | None
    stop_id: str | None
    current_stop_sequence: int | None
    timestamp: datetime | None


class VehiclePositions(BaseModel):
    feed_timestamp: datetime | None
    total_matches: int
    vehicles: list[VehiclePosition]
    provenance: Provenance


class StopTimePrediction(BaseModel):
    route_id: str | None
    trip_id: str | None
    headsign: str | None
    vehicle_label: str | None
    stop_id: str | None
    stop_sequence: int | None
    event: str
    predicted_time: datetime | None
    scheduled_time: datetime | None
    delay_seconds: int | None


class StopTimePredictions(BaseModel):
    feed_timestamp: datetime | None
    total_matches: int
    predictions: list[StopTimePrediction]
    provenance: Provenance


class AlertPeriod(BaseModel):
    start: datetime | None = Field(description="None when the period has no start.")
    end: datetime | None = Field(description="None when the period is open-ended.")


class ServiceAlert(BaseModel):
    alert_id: str
    header: str | None
    description: str | None
    cause: str | None
    effect: str | None
    severity: str | None
    route_ids: list[str] = Field(description="As in the feed: zero-padded ('004', '001A').")
    stop_ids: list[str]
    active_from: datetime | None = Field(
        description="Earliest start over active_periods; None if any period has no start."
    )
    active_until: datetime | None = Field(
        description="Latest end over active_periods; None if any period is open-ended."
    )
    active_periods: list[AlertPeriod] = Field(
        default_factory=list,
        description="Every active period; a planned detour can cover separate days.",
    )


class ServiceAlerts(BaseModel):
    feed_timestamp: datetime | None
    total_matches: int
    alerts: list[ServiceAlert]
    provenance: Provenance
