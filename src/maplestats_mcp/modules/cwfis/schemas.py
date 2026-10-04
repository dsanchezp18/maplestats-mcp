"""Typed responses for CWFIS. Field meanings confirmed against live payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Hotspot(BaseModel):
    """One satellite fire detection (VIIRS, MODIS or SLSTR) with CFFDRS values."""

    latitude: float
    longitude: float
    reported_at: datetime | None = None
    agency: str | None = Field(default=None, description="Province/territory or US state code.")
    source: str | None = None
    sensor: str | None = None
    satellite: str | None = None
    frp_mw: float | None = Field(
        default=None, description="Fire radiative power; null for old MODIS."
    )
    fwi: float | None = None
    ffmc: float | None = None
    isi: float | None = None
    bui: float | None = None
    fuel_type: str | None = Field(default=None, description="Canadian FBP fuel type, e.g. 'C2'.")
    head_fire_intensity: float | None = Field(default=None, description="`hfi`, kW/m.")
    estimated_area: float | None = Field(default=None, description="`estarea`, as published.")


class HotspotResult(BaseModel):
    hotspots: list[Hotspot]
    returned_count: int
    total_matched: int
    without_frp: int | None = Field(
        default=None,
        description="With sort_by='frp': matching detections with no FRP, listed after the ranked ones.",
    )
    layer: str
    provenance: Provenance


class Perimeter(BaseModel):
    """A current-season fire perimeter estimated from clustered hotspots (M3)."""

    hotspot_count: int | None = None
    first_detected: datetime | None = None
    last_detected: datetime | None = None
    area: float | None = Field(default=None, description="`area` as published (hectares).")
    geometry: dict[str, Any] | None = None


class PerimeterResult(BaseModel):
    perimeters: list[Perimeter]
    returned_count: int
    total_matched: int
    has_more: bool = False
    note: str | None = None
    provenance: Provenance


class WeatherStation(BaseModel):
    """A fire-weather station with its latest daily noon observation and FWI system values."""

    name: str
    wmo: int | None = None
    aes: str | None = None
    province: str | None = Field(default=None, description="Standard code (SK, NL), or a US state.")
    agency: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    observed_at: datetime | None = None
    temperature_c: float | None = None
    relative_humidity: float | None = Field(
        default=None, description="Percent; a 0 can be a placeholder for missing."
    )
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm: float | None = None
    ffmc: float | None = None
    dmc: float | None = None
    dc: float | None = None
    isi: float | None = None
    bui: float | None = None
    fwi: float | None = None
    dsr: float | None = None
    distance_km: float | None = None


class StationResult(BaseModel):
    stations: list[WeatherStation]
    returned_count: int
    total_matched: int
    note: str | None = None
    provenance: Provenance


class ForecastDay(BaseModel):
    station_id: str | None = None
    station_name: str
    valid_at: datetime
    elevation_m: float | None = None
    temperature_c: float | None = None
    relative_humidity: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm: float | None = None
    ffmc: float | None = None
    dmc: float | None = None
    dc: float | None = None
    isi: float | None = None
    bui: float | None = None
    fwi: float | None = None
    dsr: float | None = None


class ForecastResult(BaseModel):
    forecasts: list[ForecastDay]
    returned_count: int
    total_matched: int
    provenance: Provenance


class FireDanger(BaseModel):
    latitude: float
    longitude: float
    gridcode: int
    danger_class: str
    provenance: Provenance


class LargeFire(BaseModel):
    """One National Fire Database (NFDB) point record, fires of 200 ha or more."""

    nfdb_id: str
    fire_id: str | None = None
    name: str | None = None
    agency: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    year: int | None = None
    reported_date: date | None = None
    out_date: date | None = None
    size_ha: float | None = None
    cause_code: str | None = None
    cause: str | None = None
    fire_type: str | None = None
    response: str | None = None
    national_park: str | None = None


class LargeFireResult(BaseModel):
    fires: list[LargeFire]
    returned_count: int
    total_matched: int
    limit: int
    offset: int
    provenance: Provenance


class ReportSection(BaseModel):
    heading: str
    text: str


class SituationStats(BaseModel):
    """Numeric national totals; published for 1998-2023 reports, null from 2024."""

    uncontrolled: int | None = None
    controlled: int | None = None
    modified_response: int | None = None
    fires_to_date: int | None = None
    fires_10yr_avg: int | None = None
    fires_pct_of_normal: float | None = None
    prescribed_fires: int | None = None
    area_to_date_ha: int | None = None
    area_10yr_avg_ha: int | None = None
    area_pct_of_normal: float | None = None
    prescribed_area_ha: int | None = None
    us_fires: int | None = None
    us_area: int | None = Field(default=None, description="`area_us`, unit not documented.")


class SituationReportSummary(BaseModel):
    report_date: date
    report_type: str
    stats: SituationStats


class SituationReportList(BaseModel):
    reports: list[SituationReportSummary]
    returned_count: int
    total_matched: int
    offset: int
    provenance: Provenance


class SituationReport(BaseModel):
    report_date: date
    report_type: str
    stats: SituationStats
    sections: list[ReportSection]
    language: str
    provenance: Provenance
