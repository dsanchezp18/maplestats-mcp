"""Typed responses for CIHI's Indicator Library."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class IndicatorRef(BaseModel):
    slug: str = Field(description="Pass to the other cihi_ tools (English or French slug).")
    name: str
    url: str
    english_slug: str | None = Field(
        default=None, description="With lang='fr': the paired English indicator's slug."
    )
    note: str | None = None


class IndicatorSearchResult(BaseModel):
    indicators: list[IndicatorRef]
    total_matches: int
    note: str | None = None
    provenance: Provenance


class IndicatorDetail(BaseModel):
    slug: str = Field(
        description="The English slug (the French one when there is no English page)."
    )
    french_slug: str | None = None
    name: str
    note: str | None = None
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
    columns: list[str] = Field(description="Columns in the rows (requested, or non-empty).")
    empty_columns: list[str] = Field(
        default_factory=list,
        description="Columns left out because every returned row is blank in them.",
    )
    rows: list[dict[str, str]]
    total_rows: int
    matching_rows: int
    returned_count: int
    data_file_url: str
    note: str | None = None
    provenance: Provenance
