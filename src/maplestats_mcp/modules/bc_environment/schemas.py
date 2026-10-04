"""Typed responses for the BC Ministry of Environment monitoring files.

Field meanings were checked against the live files on 2026-10-03 (see
constants.py for the layouts, time zones and missing-value codes).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

WellSeriesKind = Literal["daily", "hourly", "all"]
HydroParameter = Literal["discharge", "stage"]
SurveySeason = Literal["current", "archive"]


class AirStation(BaseModel):
    ems_id: str = Field(description="Environmental Monitoring System id; names the station file.")
    name: str
    city: str | None = None
    category: str | None = Field(
        default=None, description="Network grouping: OPERATIONAL, METRO VANCOUVER, BC HYDRO."
    )
    owner: str | None = Field(
        default=None, description="ENV (province), MVRD (Metro Vancouver), INDUSTRY, ..."
    )
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    parameters: list[str] = Field(
        default_factory=list, description="Parameters with a unit in the current-hour file."
    )
    units: dict[str, str] = Field(default_factory=dict)
    latest_hour_pst: str | None = Field(
        default=None, description="Latest reported hour, Pacific Standard Time (UTC-8)."
    )
    page_url: str | None = None


class AirStationList(BaseModel):
    total_matched: int
    stations: list[AirStation]
    provenance: Provenance


class AirReading(BaseModel):
    time_pst: str = Field(description="Hour as published, Pacific Standard Time (UTC-8) all year.")
    time_utc: str = Field(description="The same hour in UTC (time_pst + 8 h).")
    station: str
    ems_id: str
    parameter: str = Field(
        description="Parameter code; a suffix _24 or _8 marks a 24- or 8-hour rolling mean."
    )
    value: float | None = Field(
        default=None,
        description="Reported value (rounded) when published, else the raw value; null when "
        "the hour is missing or carries a missing-value code (-999, -6999, ...).",
    )
    raw_value: float | None = Field(
        default=None, description="Unrounded instrument value (parameter files only)."
    )
    unit: str | None = None
    instrument: str | None = None
    missing_code: str | None = Field(
        default=None, description="The published missing-value code, when the cell held one."
    )


class AirSeries(BaseModel):
    parameter: str | None = None
    station: str | None = None
    total_matched: int
    truncated: bool
    readings: list[AirReading] = Field(description="Newest first.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class AqhiArea(BaseModel):
    area: str
    area_id: str = Field(description="Area id used in the history file name, e.g. AQHI-KAMLOOPS.")
    latitude: float | None = None
    longitude: float | None = None
    time_local: str | None = Field(default=None, description="Pacific local time (PST or PDT).")
    time_pst: str | None = None
    aqhi: str | None = Field(default=None, description="Current AQHI, 1 to 10 or '10+'.")
    risk: str | None = None
    forecast_today: str | None = None
    forecast_tonight: str | None = None
    forecast_tomorrow: str | None = None
    forecast_tomorrow_night: str | None = None
    page_url: str | None = None


class AqhiHour(BaseModel):
    time_pst: str
    time_local: str | None = None
    station: str | None = None
    aqhi: float | None = None
    aqhi_rounded: str | None = None


class AqhiResult(BaseModel):
    areas: list[AqhiArea]
    history: list[AqhiHour] = Field(default_factory=list, description="Newest first.")
    provenance: Provenance


class SnowStation(BaseModel):
    station_id: str = Field(description="Station id such as 1A01P (the P marks automated).")
    name: str
    elevation_m: float | None = None
    status: str | None = None
    operator: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class SnowStationList(BaseModel):
    total_matched: int
    stations: list[SnowStation]
    provenance: Provenance


class SnowReading(BaseModel):
    time_utc: str
    station_id: str
    station_name: str | None = None
    variable: str
    value: float | None = None
    unit: str | None = None
    grade: str | None = Field(default=None, description="Data grade (SnowAll files only).")


class SnowSeries(BaseModel):
    variable: str | None = None
    file: str
    total_matched: int
    truncated: bool
    readings: list[SnowReading] = Field(description="Newest first.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class SnowSurvey(BaseModel):
    course: str
    number: str
    elevation_m: float | None = None
    survey_date: str = Field(description="YYYY-MM-DD.")
    snow_depth_cm: float | None = None
    water_equivalent_mm: float | None = None
    density_pct: float | None = None
    survey_code: str | None = None
    snow_line_m: float | None = None
    survey_period: str | None = Field(default=None, description="Target date, e.g. 01-Apr.")


class SnowSurveyList(BaseModel):
    season: SurveySeason
    total_matched: int
    truncated: bool
    surveys: list[SnowSurvey] = Field(description="Newest first.")
    provenance: Provenance


class Well(BaseModel):
    well_id: str = Field(description="Observation well id, e.g. OW002.")
    status: str | None = Field(default=None, description="Active or Inactive.")
    region: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    well_tag_number: int | None = None
    aquifer_id: int | None = None
    aquifer_material: str | None = None
    finished_depth_ft: float | None = None
    ground_elevation_ft: float | None = None
    has_data_files: bool
    data_updated: str | None = Field(default=None, description="Last change of the data file.")
    details_url: str | None = None


class WellList(BaseModel):
    total_matched: int
    wells: list[Well]
    provenance: Provenance


class WellLevel(BaseModel):
    time: str = Field(description="As published; fixed UTC-7 for hourly series, a date for daily.")
    depth_to_water_m: float | None = Field(description="Metres below ground surface.")
    approval: str | None = Field(default=None, description="Approved, Validated, Working, ...")


class WellSeries(BaseModel):
    well_id: str
    series: WellSeriesKind
    total_matched: int
    truncated: bool
    levels: list[WellLevel] = Field(description="Newest first.")
    provenance: Provenance


class HydroStation(BaseModel):
    station_id: str
    name: str
    status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    parameters: list[str]
    latest_utc: str | None = None


class HydroStationList(BaseModel):
    total_matched: int
    stations: list[HydroStation]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class HydroReading(BaseModel):
    time_utc: str
    value: float | None = None
    unit: str | None = None
    grade: str | None = None


class HydroSeries(BaseModel):
    station_id: str
    station_name: str | None = None
    parameter: HydroParameter
    files: list[str]
    total_matched: int
    truncated: bool
    readings: list[HydroReading] = Field(description="Newest first.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
