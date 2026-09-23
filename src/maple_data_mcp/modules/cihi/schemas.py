"""Typed responses for CIHI's Indicator Library."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class IndicatorRef(BaseModel):
    slug: str = Field(description="Pass to the other cihi_ tools.")
    name: str
    url: str


class IndicatorSearchResult(BaseModel):
    indicators: list[IndicatorRef]
    total_matches: int
    provenance: Provenance


class IndicatorDetail(BaseModel):
    slug: str
    name: str
    description: str | None = None
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="Data updated, data availability, update frequency, topics.",
    )
    page_url: str
    data_file_url: str | None = None
    provenance: Provenance


class IndicatorData(BaseModel):
    slug: str
    table: str
    tables: list[str] = Field(description="Every data table in the workbook.")
    columns: list[str]
    rows: list[dict[str, str]]
    total_rows: int
    matching_rows: int
    returned_count: int
    data_file_url: str
    provenance: Provenance
