"""Typed response models for the Eurostat module.

Shaped on live responses from 2026-11-07: the table of contents (TSV),
SDMX 2.1 dataflow structures (XML) and JSON-stat 2.0 data.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetHit(BaseModel):
    code: str = Field(description="Dataset or table code, e.g. namq_10_gdp or teina225.")
    title: str
    type: str = Field(description="'dataset' (full database) or 'table' (a short curated table).")
    theme: str = Field(description="The folders above it in Eurostat's database tree.")
    last_update: str | None = Field(default=None, description="Last data update, YYYY-MM-DD.")
    data_start: str | None = None
    data_end: str | None = Field(
        default=None, description="Latest period with data; an old one means discontinued."
    )
    values: int | None = Field(default=None, description="Number of values in the dataset.")


class DatasetSearch(BaseModel):
    query: str
    total_matches: int
    datasets: list[DatasetHit]
    provenance: Provenance


class Code(BaseModel):
    id: str
    label: str


class Dimension(BaseModel):
    id: str = Field(description="Dimension id as the data call takes it, e.g. geo, unit.")
    label: str
    position: int = Field(description="Position in the dataset, from 1.")
    codes: list[Code] = Field(description="Codes that have data in this dataset.")
    total_codes: int
    truncated: bool = False


class FlagLabel(BaseModel):
    flag: str = Field(description="Eurostat status flag, e.g. p, e, b, or a combination (bep).")
    label: str


class DatasetStructure(BaseModel):
    code: str
    title: str
    last_update: str | None = None
    data_start: str | None = None
    data_end: str | None = None
    dimensions: list[Dimension] = Field(description="Every dimension but time, in order.")
    example_filters: dict[str, list[str]] = Field(
        description="A filter naming one code per dimension, for eurostat_get_data."
    )
    flags: list[FlagLabel] = Field(description="The status flags Eurostat uses, decoded.")
    databrowser_url: str
    provenance: Provenance


class Row(BaseModel):
    geo: str | None = Field(default=None, description="Eurostat geo code, e.g. EU27_2020, DE.")
    geo_label: str | None = None
    time: str = Field(description="Period: 2026, 2026-Q2, 2026-10 or 2026-10-31.")
    unit: str | None = None
    unit_label: str | None = None
    value: float | None = Field(description="Null when withheld (flag c) or not available.")
    flag: str | None = Field(default=None, description="Status flag, e.g. p, e, b; null if none.")
    flag_label: str | None = None
    dimensions: dict[str, str] = Field(
        default_factory=dict,
        description="Codes of the other dimensions that vary in this result.",
    )


class DataResult(BaseModel):
    dataset: str
    title: str
    updated: str | None = Field(default=None, description="When Eurostat last updated the data.")
    fixed: dict[str, Code] = Field(
        description="Dimensions with one code in this result (code and label), left out of rows."
    )
    varying: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Labels of the codes in rows' dimensions, by dimension.",
    )
    rows: list[Row] = Field(description="One per observation, by series then period.")
    total_rows: int
    flags: list[FlagLabel] = Field(default_factory=list, description="Flags used in rows.")
    missing_geo: list[str] = Field(
        default_factory=list, description="Geo codes asked for that came back with no values."
    )
    databrowser_url: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class Observation(BaseModel):
    time: str
    value: float | None
    flag: str | None = None
    flag_label: str | None = None


class GeoSeries(BaseModel):
    geo: str
    geo_label: str
    observations: list[Observation] = Field(description="Oldest first.")
    latest_time: str | None = None
    latest_value: float | None = None
    latest_flag: str | None = None


class Comparison(BaseModel):
    indicator: str
    indicator_label: str
    dataset: str
    filters: dict[str, str] = Field(description="The fixed codes, to reuse in eurostat_get_data.")
    series: list[GeoSeries] = Field(description="In the order asked for.")
    canada_counterpart: str = Field(
        description="Where Canada's comparable figure is in MapleStats, and how it differs."
    )
    missing_geo: list[str] = Field(default_factory=list)
    databrowser_url: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
