"""Typed response models for CMHC's "Data Tables" document catalogue."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TableSummary(BaseModel):
    category: str
    slug: str
    title: str
    path: str = Field(description="Full site path, e.g. /professionals/.../<category>/<slug>.")


class TableList(BaseModel):
    category: str
    tables: list[TableSummary]
    total_count: int
    provenance: Provenance


class GeographyOption(BaseModel):
    id: str = Field(description="Sitecore item GUID, e.g. '{9EE6E91C-...}'.")
    name: str


class EditionOption(BaseModel):
    id: str = Field(description="Sitecore item GUID, e.g. '{43CC6A09-...}'.")
    label: str = Field(description="Human-readable edition, e.g. 'October 2023'.")


class TableDetail(BaseModel):
    category: str
    slug: str
    title: str
    description: str
    data_source: str = Field(
        description="Sitecore item path for this table - pass to get_download_url as-is."
    )
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
    geography_id: str
    edition_id: str
    provenance: Provenance
