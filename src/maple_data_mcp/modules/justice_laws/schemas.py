"""Typed responses for the Justice Laws Website XML service."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance

DocumentKind = Literal["act", "regulation"]


class LawSummary(BaseModel):
    id: str = Field(description="Consolidated number used by the other tools, e.g. 'A-1'.")
    kind: DocumentKind
    title: str
    official_number: str | None = None
    current_to: date | None = None
    url: str = Field(description="Human-readable table of contents on laws-lois.justice.gc.ca.")


class LawSearchResult(BaseModel):
    laws: list[LawSummary]
    total_matches: int
    returned_count: int
    query: str
    provenance: Provenance


class SectionHeading(BaseModel):
    label: str
    marginal_note: str | None = None
    heading: str | None = Field(default=None, description="Nearest preceding heading.")
    last_amended: date | None = None


class LawOutline(BaseModel):
    law: LawSummary
    long_title: str | None = None
    last_amended: date | None = None
    in_force: bool | None = None
    section_count: int
    offset: int = 0
    sections: list[SectionHeading]
    truncated: bool = False
    provenance: Provenance


class LawSection(BaseModel):
    law: LawSummary
    label: str
    marginal_note: str | None = None
    last_amended: date | None = None
    text: str
    truncated: bool = False
    url: str
    provenance: Provenance
