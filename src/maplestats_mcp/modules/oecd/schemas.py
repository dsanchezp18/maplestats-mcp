"""Typed response models for the OECD Data Explorer module.

Field names follow the API as read live on 2026-11-07: dataflows carry
`id`, `agencyID`, `version`, `name` and an HTML `description`; content
constraints give the codes with data, `validFrom` (last update) and an
`obs_count` annotation; data rows are SDMX-CSV 2.0 with "ID: Label"
headers and "code: label" cells.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    id: str = Field(description="Dataflow id, e.g. DSD_EO@DF_EO; pass it to the other tools.")
    agency: str = Field(description="Owning OECD directorate, e.g. OECD.ECO.MAD.")
    version: str
    name: str = Field(description="The OECD's own name (English only upstream).")
    description: str = Field(description="The OECD's description, as plain text, shortened.")
    archived: bool = Field(
        default=False,
        description="An archived dataflow: listed, but its data are not served by this module.",
    )
    explorer_url: str = Field(description="The dataset in the OECD Data Explorer.")


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
    agency: str
    version: str
    name: str
    description: str
    last_updated: str | None = Field(default=None, description="When the data last changed.")
    observation_count: int | None = None
    first_period: str | None = None
    last_period: str | None = None
    dimensions: list[Dimension] = Field(description="In series-key order.")
    key_template: str = Field(description="Dimension ids joined by dots.")
    example_key: str = Field(
        description="A key for Canada when the dataset has CAN, wildcards (empty parts) elsewhere."
    )
    citation: str = Field(description="How the OECD terms ask the data to be cited.")
    explorer_url: str
    provenance: Provenance


class DimensionValue(BaseModel):
    id: str = Field(description="Dimension id, e.g. REF_AREA.")
    code: str
    label: str


class SeriesInfo(BaseModel):
    key: str = Field(description="The series' full key, e.g. CAN.GDPV_ANNPCT.A.")
    ref_area: str | None = Field(default=None, description="Country or aggregate code (ISO 3).")
    ref_area_name: str | None = None
    frequency: str | None = Field(default=None, description="Annual, Quarterly, Monthly...")
    unit: str | None = None
    unit_multiplier: str | None = None
    base_period: str | None = None
    dimensions: list[DimensionValue]
    observation_count: int
    latest_period: str | None = None
    latest_value: float | None = None


class DataRow(BaseModel):
    series_key: str
    ref_area: str | None = None
    period: str = Field(description="SDMX period: 2026, 2026-Q1 or 2026-09.")
    value: float
    unit: str | None = None
    frequency: str | None = None
    status: str | None = Field(default=None, description="Observation status, e.g. Normal value.")


class DataResult(BaseModel):
    dataset: str
    agency: str
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


class CountrySeries(BaseModel):
    area_code: str = Field(description="OECD area code, e.g. CAN, USA, OECD.")
    area_name: str
    key: str
    unit: str | None = None
    observations: list[Observation] = Field(description="Periods with a value, oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None


class ComparisonResult(BaseModel):
    indicator: str
    indicator_label: str
    dataset: str
    dataset_name: str
    countries: list[CountrySeries] = Field(description="Canada first, then the comparisons.")
    canada_rank: int | None = Field(
        default=None,
        description=(
            "Canada's rank (1 = highest value) in rank_period, the latest of Canada's periods "
            "that the most compared countries report; aggregates are not ranked."
        ),
    )
    rank_period: str | None = None
    ranked_countries: int | None = None
    csv_url: str
    citation: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
