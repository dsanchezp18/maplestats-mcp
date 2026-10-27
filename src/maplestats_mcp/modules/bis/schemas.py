"""Typed response models for the BIS statistics module.

Field names follow the API as read live on 2026-10-26: dataflows carry
`id`, `name`, `version` and `structure` (a DSD URN); data rows are SDMX-CSV
with "ID:Label" headers and "code: label" cells.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Dataset(BaseModel):
    id: str = Field(description="Dataflow id, e.g. WS_DSR.")
    name: str = Field(description="The BIS's own name (English).")
    version: str
    description: str = Field(description="What the dataset holds, in the language asked for.")


class DatasetList(BaseModel):
    datasets: list[Dataset]
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
    name: str
    version: str
    description: str
    dimensions: list[Dimension] = Field(description="In series-key order.")
    key_template: str = Field(description="Dimension ids joined by dots, e.g. FREQ.REF_AREA.")
    example_key: str = Field(
        description="A key for Canada when the dataset has a Canada code, else all wildcards."
    )
    provenance: Provenance


class DimensionValue(BaseModel):
    id: str = Field(description="Dimension id, e.g. REF_AREA.")
    code: str
    label: str


class Observation(BaseModel):
    period: str = Field(description="SDMX period: 2026, 2026-Q1, 2026-09 or 2026-09-30.")
    value: float


class Series(BaseModel):
    key: str = Field(description="The series' full key, e.g. Q.CA.H.")
    title: str | None = None
    dimensions: list[DimensionValue]
    unit: str | None = None
    unit_multiplier: str | None = None
    observations: list[Observation] = Field(description="Periods with a value, oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None


class SeriesResult(BaseModel):
    dataset: str
    dataset_name: str
    key: str
    series: list[Series]
    csv_url: str = Field(description="The same query as SDMX-CSV, for a spreadsheet or script.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class CountrySeries(BaseModel):
    area_code: str = Field(description="BIS area code, e.g. CA, US, XM for the euro area.")
    area_name: str
    key: str
    observations: list[Observation] = Field(description="Periods with a value, oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None


class ComparisonResult(BaseModel):
    indicator: str
    indicator_label: str
    dataset: str
    countries: list[CountrySeries] = Field(description="Canada first, then the comparisons.")
    canada_rank: int | None = Field(
        default=None,
        description=(
            "Canada's rank (1 = highest value) in rank_period, the latest of Canada's "
            "periods that the most compared economies report; euro area and other "
            "aggregates are not ranked. None without comparisons."
        ),
    )
    rank_period: str | None = None
    ranked_countries: int | None = None
    csv_url: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
