"""Typed responses for Alberta Wildfire status. Field meanings confirmed
against live payloads (see the package docstring)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Dataset = Literal["current", "previous_5_years"]
FireGroupBy = Literal["status", "cause", "size_class", "forest_area", "fire_type", "fire_year"]
DateBasis = Literal["assessed", "status_changed"]
FireSort = Literal["latest", "largest"]
PerimeterState = Literal["active", "extinguished"]


class Fire(BaseModel):
    """One fire location (a point) from Alberta Wildfire's fire layer."""

    fire_number: str | None = Field(
        default=None, description="Fire label with year, e.g. 'CWF-001-2026'."
    )
    fire_year: int | None = None
    fire_type: str | None = Field(
        default=None,
        description="'Wildfire' (started in the Forest Protection Area) or 'Mutual Aid'.",
    )
    status: str | None = Field(
        default=None,
        description=(
            "Out of Control, Being Held, Under Control, Extinguished, Turned Over, "
            "Assistance Started or Assistance Ended."
        ),
    )
    status_changed: datetime | None = Field(
        default=None,
        description=(
            "When the status last changed, in UTC (the source gives Alberta local "
            "time with no zone; converted)."
        ),
    )
    assessed_at: datetime | None = Field(
        default=None,
        description="Initial assessment (wildfire) or assistance (mutual aid) time, UTC.",
    )
    area_ha: float | None = Field(default=None, description="Area estimate in hectares.")
    size_class: str | None = Field(
        default=None, description="A to 0.1 ha, B to 4, C to 40, D to 200, E over 200 ha."
    )
    cause: str | None = Field(
        default=None,
        description="General cause (Human, Lightning, ...); null for mutual-aid fires.",
    )
    forest_area: str | None = Field(default=None, description="Responsible forest area.")
    carryover: bool | None = Field(
        default=None, description="True for a fire carried over from an earlier year."
    )
    complex_number: str | None = None
    complex_name: str | None = None
    incident_type: str | None = None
    response_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = Field(
        default=None, description="Distance from the requested point, when one was given."
    )


class FireList(BaseModel):
    dataset: Dataset
    where: str
    total_matches: int
    returned_count: int
    offset: int
    fires: list[Fire]
    provenance: Provenance


class FireGroup(BaseModel):
    key: str | int | None = Field(description="The group value (null = not recorded).")
    fires: int
    total_area_ha: float | None
    largest_fire_ha: float | None


class FireSummary(BaseModel):
    dataset: Dataset
    group_by: FireGroupBy
    where: str
    total_fires: int
    total_area_ha: float
    groups: list[FireGroup]
    provenance: Provenance


class Perimeter(BaseModel):
    """A mapped fire perimeter (polygon) with the fire's attributes."""

    fire_number: str | None = None
    fire_type: str | None = None
    status: str | None = None
    status_changed: datetime | None = None
    area_ha: float | None = Field(default=None, description="Area estimate of the fire.")
    mapped_area_ha: float | None = Field(
        default=None, description="Area of the mapped polygon(s), `SumAreaHa`."
    )
    size_class: str | None = None
    cause: str | None = None
    forest_area: str | None = None
    captured_at: datetime | None = Field(default=None, description="When mapped, UTC.")
    data_source: str | None = Field(default=None, description="e.g. GPS, Aerial imagery, Hybrid.")
    source_keys: str | None = Field(default=None, description="e.g. Ground, Rotary Wing.")
    creation_method: str | None = None
    last_updated: datetime | None = Field(default=None, description="GIS record update, UTC.")
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON (WGS84), simplified to about 50 m, if requested."
    )


class PerimeterList(BaseModel):
    state: PerimeterState
    where: str
    total_matches: int
    returned_count: int
    offset: int
    perimeters: list[Perimeter]
    note: str | None = None
    provenance: Provenance


class Headline(BaseModel):
    """The dashboard's five headline figures (wildfires only, current year)."""

    active_wildfires: int | None
    active_area_ha: float | None
    year_to_date_wildfires: int | None
    year_to_date_area_ha: float | None
    new_wildfires_24h: int | None


class SameDayComparison(BaseModel):
    """Season totals as at the same calendar date in one year."""

    year: int
    day: date | None
    wildfires_that_day: int | None
    wildfires_to_date: int | None
    area_burned_to_date_ha: float | None
    area_burned_that_day_ha: float | None = Field(
        default=None, description="Can be slightly negative when an area estimate is revised."
    )
    five_year_avg_wildfires: float | None
    ten_year_avg_wildfires: float | None
    twentyfive_year_avg_wildfires: float | None
    five_year_avg_area_ha: float | None
    ten_year_avg_area_ha: float | None
    twentyfive_year_avg_area_ha: float | None


class SeasonStatistics(BaseModel):
    headline: Headline
    same_day_comparison: list[SameDayComparison]
    comparison_date: date | None
    provenance: Provenance


class DangerAtPoint(BaseModel):
    latitude: float
    longitude: float
    danger_class: str | None = Field(
        description="Low, Moderate, High, Very High or Extreme; null outside the rated area."
    )
    meaning: str | None
    rating_timestamp: datetime | None = Field(
        default=None,
        description=(
            "The polygon's `Last_Updated` stamp, UTC. Seen up to five hours later than the "
            "query time, so it is not a reliable freshness measure; provenance.as_of is "
            "the layer's own last data edit."
        ),
    )
    note: str | None = None
    provenance: Provenance


class DangerCount(BaseModel):
    danger_class: str
    polygons: int


class DangerSummary(BaseModel):
    bbox: list[float] | None
    most_severe_class: str | None
    classes: list[DangerCount]
    total_polygons: int
    rating_timestamp: datetime | None = Field(
        description="Latest `Last_Updated` stamp, UTC; may be later than the query time."
    )
    note: str
    provenance: Provenance


class FireControlOrder(BaseModel):
    """A fire ban, restriction, advisory or closure (or an OHV restriction)."""

    alert_type: str
    name: str | None
    jurisdictions: str | None
    start_date: date | None = Field(
        default=None, description="Start (or OHV effective) date; there is no end date."
    )
    expiry_date: date | None = Field(default=None, description="OHV restrictions only.")
    contact_number: str | None = None
    order_number: str | None = None
    website: str | None = None
    polygons: int = Field(description="How many map polygons carry this same entry.")


class FireControlOrderList(BaseModel):
    where: str
    returned_count: int
    counts_by_type: dict[str, int]
    orders: list[FireControlOrder]
    note: str | None = None
    provenance: Provenance
