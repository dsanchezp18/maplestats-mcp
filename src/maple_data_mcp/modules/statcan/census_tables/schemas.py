"""Typed responses for census data tables."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class CensusTable(BaseModel):
    release: str
    pid: str = Field(description="StatCan product id, for statcan_census_tables_get_downloads.")
    catalogue_number: str
    title: str = Field(description="Full title, including the geography levels covered.")
    theme: str | None = None
    has_ivt: bool
    page_url: str


class CensusTableSearch(BaseModel):
    release: str
    query: str
    tables: list[CensusTable]
    total_matched: int
    total_tables: int
    provenance: Provenance


class Download(BaseModel):
    format: str = Field(description="csv, sdmx or ivt (Beyond 20/20).")
    url: str
    size_bytes: int | None = None
    available: bool


class CensusTableDownloads(BaseModel):
    release: str
    pid: str
    downloads: list[Download]
    ivt_only: bool = Field(description="True when the table exists only as Beyond 20/20 IVT.")
    ivt_note: str | None = Field(
        default=None,
        description="How to read the IVT when there is no open-format copy.",
    )
    provenance: Provenance
