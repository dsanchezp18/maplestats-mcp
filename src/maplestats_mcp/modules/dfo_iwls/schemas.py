"""Typed responses for the DFO/CHS Integrated Water Level System API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Resolution = Literal["ONE_MINUTE", "FIVE_MINUTES", "FIFTEEN_MINUTES", "SIXTY_MINUTES"]


class TimeSeriesInfo(BaseModel):
    code: str = Field(
        description="e.g. 'wlo' observed, 'wlp' predicted, 'wlp-hilo' high/low tides."
    )
    name: str


class StationSummary(BaseModel):
    code: str = Field(description="Five-digit CHS station code, e.g. '07120'.")
    id: str
    name: str
    alternative_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    operating: bool
    station_type: str | None = None
    time_series: list[TimeSeriesInfo] = Field(default_factory=list)


class StationSearchResult(BaseModel):
    stations: list[StationSummary]
    total_matches: int
    returned_count: int
    provenance: Provenance


class Datum(BaseModel):
    code: str
    offset: float | None = None


class StationDetail(BaseModel):
    station: StationSummary
    region_code: str | None = None
    is_tidal: bool | None = None
    is_tide_table_reference_port: bool | None = None
    established_year: int | None = None
    datums: list[Datum] = Field(
        default_factory=list, description="Vertical datum offsets from chart datum (metres)."
    )
    provenance: Provenance


class WaterLevelPoint(BaseModel):
    time: datetime
    value: float = Field(description="Water level in metres above chart datum.")
    qc_flag: str | None = None
    reviewed: bool | None = None


class WaterLevelSeries(BaseModel):
    station_code: str
    station_name: str
    series_code: str
    series_name: str
    start: datetime
    end: datetime
    resolution: str | None = None
    points: list[WaterLevelPoint]
    provenance: Provenance
