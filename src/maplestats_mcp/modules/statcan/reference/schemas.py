"""Typed responses for StatCan's Drupal-based catalogue searches
(Reference resources and Analysis share the same result shape)."""

from __future__ import annotations

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
