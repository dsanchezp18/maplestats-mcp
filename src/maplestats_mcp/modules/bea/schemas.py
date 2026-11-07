"""Typed response models for the US Bureau of Economic Analysis module.

Field names follow the BEA API user guide (April 2026): every answer is
`BEAAPI.Results`; data rows carry `TimePeriod`, `DataValue` (a string with
thousands commas), `CL_UNIT`, `UNIT_MULT` and `NoteRef`, plus dataset-specific
dimensions (NIPA `SeriesCode`, `LineNumber`, `LineDescription`, `METRIC_NAME`;
Regional `Code`, `GeoFips`, `GeoName`; ITA `Indicator`, `AreaOrCountry`,
`Frequency`, `TimeSeriesId`, `TimeSeriesDescription`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Dataset(BaseModel):
    name: str
    description: str


class DatasetList(BaseModel):
    datasets: list[Dataset]
    provenance: Provenance


class ParameterValue(BaseModel):
    key: str = Field(description="The value to pass as the parameter.")
    description: str


class ParameterValueList(BaseModel):
    dataset: str
    parameter: str
    filters: dict[str, str] = Field(default_factory=dict)
    values: list[ParameterValue]
    total_values: int
    truncated: bool = False
    provenance: Provenance


class Row(BaseModel):
    series: str | None = Field(
        default=None, description="NIPA SeriesCode, Regional Code or ITA TimeSeriesId."
    )
    description: str | None = Field(
        default=None, description="NIPA LineDescription or ITA TimeSeriesDescription."
    )
    line_number: str | None = None
    geo_fips: str | None = None
    geo_name: str | None = None
    indicator: str | None = None
    area_or_country: str | None = None
    frequency: str | None = Field(
        default=None, description="A, Q or M; for ITA also QSA (adjusted) or QNSA (not)."
    )
    period: str = Field(description="BEA TimePeriod: 2026, 2026Q2 or 2026M09.")
    date: str = Field(description="2026, 2026-Q2 or 2026-09.")
    value: float | None = Field(description="None where BEA shows (NA), (D) or a blank.")
    value_text: str = Field(description="DataValue as BEA sent it.")
    unit: str | None = Field(default=None, description="CL_UNIT, e.g. USD, Percent, Level.")
    unit_multiplier: int | None = Field(
        default=None, description="UNIT_MULT: power of ten, 6 = millions, 9 = billions."
    )
    metric: str | None = Field(default=None, description="NIPA METRIC_NAME, e.g. Current Dollars.")
    notes: list[str] = Field(default_factory=list, description="Text of the row's NoteRefs.")


class DataResult(BaseModel):
    dataset: str
    query: dict[str, str] = Field(description="The parameters sent, without the UserID.")
    title: str | None = Field(default=None, description="Table title or statistic name.")
    rows: list[Row]
    total_rows: int
    truncated: bool = False
    notes: list[str] = Field(default_factory=list, description="Table notes, then MapleStats'.")
    production_time: datetime | None = Field(
        default=None, description="When BEA produced the result (Regional's UTCProductionTime)."
    )
    release_schedule_url: str
    provenance: Provenance
