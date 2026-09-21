"""Typed responses for The Daily's Atom feeds and full release archive."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class DailyRelease(BaseModel):
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None


class DailyReleaseList(BaseModel):
    subject: str
    releases: list[DailyRelease] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance


class DailyArchiveEntry(BaseModel):
    release_date: date
    title: str
    reference_period: str | None = None
    url: str


class DailyArchiveSearchResult(BaseModel):
    query: str
    entries: list[DailyArchiveEntry] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance
