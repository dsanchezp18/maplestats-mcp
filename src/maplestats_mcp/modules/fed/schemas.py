"""Typed response models for the Federal Reserve Board releases module.

Field names follow the release XML files as read live on 2026-11-07: SDMX-ML
1.0 compact data, each series carrying FREQ, UNIT, UNIT_MULT, CURRENCY and
SERIES_NAME attributes plus its own dimensions, and short and long descriptions
as annotations; observations carry TIME_PERIOD (always a full date, the end of
the period), OBS_VALUE and OBS_STATUS.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Release(BaseModel):
    code: str = Field(description="Release code, e.g. H15, H10, G17.")
    name: str
    description: str
    release_page: str
    data_url: str = Field(description="The release's complete data as one SDMX-ML zip file.")


class ReleaseList(BaseModel):
    releases: list[Release]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class DimensionValue(BaseModel):
    id: str = Field(description="Dimension or attribute id, e.g. INSTRUMENT, MATURITY.")
    code: str
    label: str


class SeriesInfo(BaseModel):
    series_id: str = Field(description="The Board's series name, e.g. RIFLGFCY10_N.B.")
    release: str
    description: str
    long_description: str | None = None
    group: str = Field(description="The release's data set that holds the series.")
    discontinued: bool = False
    frequency: str
    unit: str
    unit_multiplier: str | None = Field(
        default=None, description="Multiply values by this to get units, e.g. 1000000."
    )
    currency: str | None = None
    dimensions: list[DimensionValue] = Field(default_factory=list)
    first_date: str | None = None
    last_date: str | None = None
    last_value: float | None = None
    observations: int = 0


class SearchResult(BaseModel):
    query: str
    releases_searched: list[str]
    total_matches: int
    series: list[SeriesInfo]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class Code(BaseModel):
    code: str
    label: str


class Dimension(BaseModel):
    id: str
    name: str
    codes: list[Code] = Field(description="Codes the release's series use, with labels.")


class Group(BaseModel):
    id: str
    name: str
    series_count: int
    dimensions: list[Dimension]


class ReleaseStructure(BaseModel):
    code: str
    name: str
    description: str
    prepared: datetime | None = Field(default=None, description="When the file was prepared.")
    series_count: int
    frequencies: list[str]
    groups: list[Group]
    example_series: list[str]
    provenance: Provenance


class Row(BaseModel):
    date: str = Field(description="Period end date, YYYY-MM-DD (a month is its last day).")
    value: float
    series_id: str
    unit: str
    frequency: str


class SeriesData(BaseModel):
    release: str
    indicator: str | None = None
    indicator_label: str | None = None
    compare_with_canada: str | None = Field(
        default=None, description="The Canadian series to set beside this one."
    )
    series: list[SeriesInfo]
    rows: list[Row] = Field(description="One row per series and date, oldest first.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
