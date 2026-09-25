"""Typed responses for GC InfoBase open datasets."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class InfoBaseFile(BaseModel):
    resource_id: str = Field(description="Pass to gc_infobase_query.")
    name: str
    description: str | None = None
    languages: list[str] = Field(default_factory=list)
    url: str


class InfoBaseFileList(BaseModel):
    files: list[InfoBaseFile]
    provenance: Provenance


class InfoBaseRows(BaseModel):
    resource_id: str
    name: str
    columns: list[str]
    rows: list[dict[str, str]]
    total_rows: int
    matching_rows: int
    returned_count: int
    fiscal_year_column: str | None = None
    organization_column: str | None = None
    provenance: Provenance
