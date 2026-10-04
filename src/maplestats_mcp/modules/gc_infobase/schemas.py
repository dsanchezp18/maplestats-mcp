"""Typed responses for GC InfoBase open datasets."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class InfoBaseFile(BaseModel):
    resource_id: str = Field(description="Pass to gc_infobase_query.")
    name: str
    description: str | None = Field(
        default=None,
        description="Null for most files: open.canada.ca gives them a name only.",
    )
    languages: list[str] = Field(default_factory=list)
    url: str


class InfoBaseFileList(BaseModel):
    files: list[InfoBaseFile]
    provenance: Provenance


class InfoBaseRows(BaseModel):
    resource_id: str
    name: str = Field(description="The file's name in its own language.")
    columns: list[str]
    numeric_columns: list[str] = Field(
        default_factory=list,
        description=(
            "Columns returned as numbers (null when blank); identifier and code "
            "columns such as org_id or vote_number stay text."
        ),
    )
    rows: list[dict[str, str | int | float | None]]
    total_rows: int
    matching_rows: int
    returned_count: int
    fiscal_year_column: str | None = None
    organization_column: str | None = None
    provenance: Provenance
