"""Typed response models for the ILOSTAT module.

Field names follow the ILO's SDMX API as read live on 2026-11-08: dataflows
carry `id`, `name` and an HTML `description` (English or French, by
Accept-Language) and a LAST_UPDATE annotation; data rows are SDMX-CSV 2.0
with "ID: Label" headers and "code: label" cells, plus SOURCE (the national
survey) and note columns.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    id: str = Field(
        description="Dataflow id, e.g. DF_UNE_DEAP_SEX_AGE_RT; pass it to the other tools."
    )
    name: str
    description: str = Field(description="The ILO's description, as plain text, shortened.")
    last_updated: str | None = Field(default=None, description="When the ILO last updated it.")
    modelled: bool = Field(
        default=False,
        description="ILO modelled estimates (filled gaps, aggregates and projections), not "
        "national survey figures.",
    )


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
    name: str
    description: str
    last_updated: str | None = None
    modelled: bool = False
    dimensions: list[Dimension] = Field(description="In series-key order.")
    key_template: str = Field(description="Dimension ids joined by dots.")
    example_key: str = Field(
        description="A key for Canada when the dataset has CAN, wildcards (empty parts) elsewhere."
    )
    citation: str
    csv_url: str = Field(description="Canada's latest values as CSV with labels.")
    provenance: Provenance


class DimensionValue(BaseModel):
    id: str = Field(description="Dimension id, e.g. REF_AREA.")
    code: str
    label: str


class SeriesInfo(BaseModel):
    key: str = Field(
        description="The series' full key, e.g. CAN.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15."
    )
    ref_area: str | None = Field(default=None, description="Country (ISO 3) or X aggregate code.")
    ref_area_name: str | None = None
    frequency: str | None = Field(default=None, description="Annual, Quarterly or Monthly.")
    unit: str | None = None
    unit_multiplier: str | None = None
    source: str | None = Field(
        default=None, description="The national source, e.g. LFS - Labour Force Survey."
    )
    dimensions: list[DimensionValue]
    observation_count: int
    latest_period: str | None = None
    latest_value: float | None = None


class DataRow(BaseModel):
    series_key: str
    ref_area: str | None = None
    period: str = Field(description="SDMX period: 2026, 2026-Q1 or 2026-M09.")
    value: float
    unit: str | None = None
    frequency: str | None = None
    status: str | None = Field(
        default=None, description="Observation status, e.g. Break in series."
    )


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
    status: str | None = None


class CountrySeries(BaseModel):
    area_code: str = Field(description="ISO 3 country code, or an ILO X aggregate (X01 World).")
    area_name: str
    key: str
    unit: str | None = None
    source: str | None = Field(default=None, description="The national survey or ILO model.")
    observations: list[Observation] = Field(description="Periods with a value, oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None


class ComparisonResult(BaseModel):
    indicator: str
    indicator_label: str
    dataset: str
    dataset_name: str
    frequency: str
    sex: str
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
