"""Typed responses for PBO publications."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

PublicationType = Literal["RP", "NT", "LEG", "ES", "OA", "LIBARC"]
Value = float | int | str | bool | None


class PboPublicationSummary(BaseModel):
    id: str = Field(description="PBO publication id, e.g. 'LEG-2526-012-S'.")
    type: str
    type_label: str
    title: str
    abstract: str | None = None
    release_date: str | None = None
    url: str | None = Field(default=None, description="The publication's page on pbo-dpb.ca.")
    pdf_url: str | None = None


class PboSearchResult(BaseModel):
    publications: list[PboPublicationSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    page: int
    last_page: int
    provenance: Provenance


class PboTable(BaseModel):
    reference: str | None = Field(default=None, description="e.g. 'Table 1'.")
    label: str | None = None
    kind: Literal["table", "html", "kvlist"]
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Value]] = Field(
        default_factory=list, description="table and kvlist slices: rows keyed by column label."
    )
    cells: list[list[str]] = Field(
        default_factory=list, description="html slices: rows of cell text as published."
    )
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PboPublication(BaseModel):
    publication: PboPublicationSummary
    has_structured_content: bool = Field(
        description="False for older publications, which are PDF only."
    )
    tables: list[PboTable] = Field(default_factory=list)
    text: str | None = Field(default=None, description="The markdown text, capped.")
    text_truncated: bool = False
    provenance: Provenance
