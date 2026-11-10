"""Typed responses for StatCan's Drupal-based catalogue searches
(Reference resources and Analysis share the same result shape) and for the
publications they list (statcan_reference_get_publication, _get_section_text)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class ReferenceDocument(BaseModel):
    title: str
    url: str
    catalogue_number: str | None = None
    category: str | None = None
    description: str | None = None
    release_date: str | None = None


class ReferenceSearchResult(BaseModel):
    catalogue: str
    query: str
    documents: list[ReferenceDocument] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class PublicationEdition(BaseModel):
    title: str
    url: str = Field(description="The edition's main page (HTML) or its PDF.")
    release_date: date | None = None
    catalogue_number: str | None = Field(
        default=None, description="The edition's own number, e.g. '71-543-G2025001'."
    )
    issue: str | None = Field(default=None, description="Issue number, e.g. '2025001'.")
    format: Literal["html", "pdf"]
    archived: bool = False


class PublicationSection(BaseModel):
    id: str = Field(
        description=(
            "Pass as `section` to statcan_reference_get_section_text: an anchor on the "
            "main page ('a3'), another page of the edition ('chap-10'), or an anchor on "
            "that page ('chap-10#a2')."
        )
    )
    title: str
    level: int = Field(description="1 for a top-level section or page, 2 below it, ...")
    url: str


class Publication(BaseModel):
    catalogue_number: str | None = None
    title: str
    product_type: str | None = Field(
        default=None, description="e.g. 'Surveys and statistical programs – Documentation'."
    )
    description: str | None = None
    edition_title: str | None = None
    issue: str | None = None
    release_date: date | None = None
    archived: bool = False
    format: Literal["html", "pdf"]
    url: str = Field(description="The edition's main page, or its PDF when it has no HTML.")
    pdf_url: str | None = None
    sections: list[PublicationSection] = Field(default_factory=list)
    editions: list[PublicationEdition] = Field(default_factory=list)
    editions_total: int = 0
    provenance: Provenance


class SectionText(BaseModel):
    id: str
    title: str
    url: str = Field(description="The section's own page and anchor: cite it.")
    text: str = Field(description="Plain text; headings as '#' lines, tables as 'a | b' rows.")
    start_char: int = 0
    next_start_char: int | None = Field(
        default=None,
        description="Where the text stopped when cut: pass as start_char to read on.",
    )
    total_chars: int
    score: float | None = Field(default=None, description="Query match score, best first.")


class PublicationText(BaseModel):
    catalogue_number: str | None = None
    title: str
    issue: str | None = None
    release_date: date | None = None
    archived: bool = False
    edition_url: str
    pdf_url: str | None = None
    query: str | None = None
    sections: list[SectionText] = Field(default_factory=list)
    subsections: list[PublicationSection] = Field(
        default_factory=list,
        description="Sections and pages inside the one returned, to read next.",
    )
    pages_read: int = 0
    provenance: Provenance
