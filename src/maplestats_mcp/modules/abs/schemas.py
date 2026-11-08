"""Typed response models for the ABS Data API module.

Field names follow the API as read live on 2026-11-08: dataflows carry `id`,
`version`, `name` and a plain-text `description` (English only); data rows
are SDMX-CSV 1.0 with "ID: Label" headers and "code: label" cells.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    id: str = Field(description="Dataflow id, e.g. CPI or LF; pass it to the other tools.")
    version: str
    name: str
    description: str = Field(description="The ABS description, shortened.")


class DatasetSearch(BaseModel):
    query: str
    total_matches: int
    datasets: list[DatasetSummary] = Field(description="Best matches first.")
    provenance: Provenance


class Code(BaseModel):
    id: str
    name: str


class Dimension(BaseModel):
    id: str
    name: str
    position: int = Field(description="Position in the series key, from 1.")
    codes: list[Code] = Field(description="Codes that have data in this dataset.")
    total_codes: int
    truncated: bool = False


class DatasetStructure(BaseModel):
    id: str
    version: str
    name: str
    description: str
    dimensions: list[Dimension] = Field(description="In series-key order.")
    key_template: str = Field(description="Dimension ids joined by dots.")
    example_key: str = Field(
        description="A key for Australia (AUS or 50) where the dataset has it, wildcards "
        "(empty parts) elsewhere."
    )
    citation: str
    provenance: Provenance


class DimensionValue(BaseModel):
    id: str = Field(description="Dimension id, e.g. MEASURE.")
    code: str
    label: str


class SeriesInfo(BaseModel):
    key: str = Field(description="The series' full key, e.g. M13.3.1599.20.AUS.M.")
    region: str | None = Field(default=None, description="Region label, e.g. Australia.")
    frequency: str | None = None
    adjustment: str | None = Field(
        default=None, description="Original, Seasonally Adjusted or Trend."
    )
    unit: str | None = None
    base_period: str | None = None
    dimensions: list[DimensionValue]
    observation_count: int
    latest_period: str | None = None
    latest_value: float | None = None


class DataRow(BaseModel):
    series_key: str
    period: str = Field(description="SDMX period: 2026, 2026-Q3 or 2026-09.")
    value: float
    unit: str | None = None
    status: str | None = None


class DataResult(BaseModel):
    dataset: str
    dataset_name: str
    key: str
    series: list[SeriesInfo] = Field(description="One entry per series, dimensions given once.")
    rows: list[DataRow] = Field(description="One row per observation, by series then period.")
    csv_url: str = Field(description="The same query as CSV with labels, for a spreadsheet.")
    citation: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class Observation(BaseModel):
    period: str
    value: float


class IndicatorResult(BaseModel):
    indicator: str
    indicator_label: str
    dataset: str
    key: str
    unit: str | None = None
    frequency: str | None = None
    observations: list[Observation] = Field(description="Oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None
    canada_counterpart: str = Field(
        description="Where Canada's comparable figure is in MapleStats, and how it differs."
    )
    csv_url: str
    citation: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
