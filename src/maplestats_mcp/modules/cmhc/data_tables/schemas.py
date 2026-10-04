"""Typed response models for CMHC's "Data Tables" document catalogue."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TableSummary(BaseModel):
    category: str
    slug: str = Field(description="Pass to cmhc_dt_get_table (English or French slug).")
    title: str
    path: str = Field(description="Full site path, e.g. /professionals/.../<category>/<slug>.")
    english_slug: str | None = Field(
        default=None, description="With lang='fr': the paired English table's slug."
    )
    note: str | None = None


class TableList(BaseModel):
    category: str
    tables: list[TableSummary]
    total_count: int
    note: str | None = None
    provenance: Provenance


class GeographyOption(BaseModel):
    id: str = Field(description="Sitecore item GUID, e.g. '{9EE6E91C-...}'.")
    name: str


class EditionOption(BaseModel):
    id: str = Field(description="Sitecore item GUID, e.g. '{43CC6A09-...}'.")
    label: str = Field(description="Human-readable edition, e.g. 'October 2023'.")


class TableDetail(BaseModel):
    category: str
    slug: str = Field(description="The English slug.")
    french_slug: str | None = None
    title: str
    description: str
    data_source: str | None = Field(
        default=None,
        description="Sitecore item path of an edition table (null for a single-file table).",
    )
    document_id: str | None = Field(
        default=None,
        description="Set for a single-file table (no geography or edition options).",
    )
    author: str | None = None
    document_type: str | None = None
    date_published: str | None = None
    geographies: list[GeographyOption]
    editions: list[EditionOption]
    default_download_url: str | None = Field(
        default=None, description="The currently-published (most recent) edition's download link."
    )
    provenance: Provenance


class DownloadLink(BaseModel):
    document_url: str
    file_name: str | None = None
    author: str | None = None
    document_type: str | None = None
    date_published: str | None = None
    geography_id: str | None = Field(default=None, description="Null for a single-file table.")
    edition_id: str | None = Field(default=None, description="Null for a single-file table.")
    provenance: Provenance
