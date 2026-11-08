"""Typed response models for the European Central Bank Data Portal module.

Field names follow the API as read live on 2026-11-07: SDMX 2.1 structures as
SDMX-ML (dataflows with English names, data structures, code lists, content
constraints), data as `format=csvdata` with a KEY column, one column per
dimension, TIME_PERIOD, OBS_VALUE, OBS_STATUS and series attributes (TITLE,
TITLE_COMPL, UNIT, UNIT_MULT).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Dataset(BaseModel):
    id: str = Field(description="Dataflow id, e.g. EXR, FM, HICP, BSI.")
    name: str = Field(description="The ECB's own name (English).")
    description: str | None = Field(
        default=None, description="What the dataset holds, in the language asked for."
    )


class DatasetList(BaseModel):
    datasets: list[Dataset]
    total: int
    provenance: Provenance


class Code(BaseModel):
    id: str
    name: str


class Dimension(BaseModel):
    id: str
    name: str
    position: int = Field(description="Position in the series key, from 1.")
    codes: list[Code] = Field(description="Codes the ECB marks as allowed in this dataset.")
    total_codes: int
    truncated: bool = False


class DatasetStructure(BaseModel):
    id: str
    name: str
    description: str | None = None
    dimensions: list[Dimension] = Field(description="In series-key order.")
    key_template: str = Field(description="Dimension ids joined by dots, e.g. FREQ.CURRENCY.")
    example_key: str | None = Field(
        default=None, description="A preset key from this dataset, when one exists."
    )
    provenance: Provenance


class SeriesInfo(BaseModel):
    key: str = Field(description="Series key without the dataset, e.g. D.CAD.EUR.SP00.A.")
    title: str | None = None
    title_long: str | None = None
    frequency: str | None = None
    unit: str | None = None
    unit_multiplier: str | None = None
    first_period: str | None = None
    last_period: str | None = None
    last_value: float | None = None
    observations: int = 0


class SeriesList(BaseModel):
    dataset: str
    key: str
    query: str | None = None
    total_matches: int
    series: list[SeriesInfo]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class Row(BaseModel):
    date: str = Field(description="SDMX period: 2026, 2026-Q3, 2026-10 or 2026-11-05.")
    value: float
    series_id: str = Field(description="Dataset and key, e.g. EXR.D.CAD.EUR.SP00.A.")
    unit: str | None = None
    frequency: str | None = None


class SeriesData(BaseModel):
    dataset: str
    key: str
    indicator: str | None = None
    indicator_label: str | None = None
    compare_with_canada: str | None = Field(
        default=None, description="The Canadian series to set beside this one."
    )
    series: list[SeriesInfo]
    rows: list[Row] = Field(description="One row per series and period, oldest first.")
    csv_url: str = Field(description="The same query as CSV, for a spreadsheet or script.")
    portal_url: str = Field(description="The dataset on the ECB Data Portal.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
