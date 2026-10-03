"""Typed responses for The Daily's Atom feeds and full release archive."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


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
    scheduled: bool = Field(
        description="True when the release date is today (Toronto) or later: not yet published."
    )
    url: str | None = Field(
        default=None,
        description="Daily article URL; null for an upcoming release, which has no article yet.",
    )


class DailyArchiveSearchResult(BaseModel):
    query: str
    entries: list[DailyArchiveEntry] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class ReleaseCalendarEntry(BaseModel):
    release_date: date
    kind: str = Field(description="'key_indicator' (Daily release) or 'product' (catalogue).")
    title: str
    reference_period: str | None = Field(
        default=None, description="Reference period of an indicator release, e.g. 'August 2026'."
    )
    catalogue_number: str | None = Field(
        default=None, description="Product id such as '62-013-X2026004' (products only)."
    )
    scheduled: bool = Field(
        description="True when the release date is today or later (not yet published)."
    )
    url: str | None = Field(
        default=None,
        description="Daily article or catalogue page; empty until a release is published.",
    )


class ReleaseCalendarResult(BaseModel):
    query: str
    kind: str
    upcoming_only: bool
    entries: list[ReleaseCalendarEntry] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    today: date = Field(description="Today in Toronto, the reference date for 'upcoming'.")
    latest_scheduled_date: date | None = Field(
        default=None, description="Last date in the schedule file, i.e. how far ahead it reaches."
    )
    provenance: Provenance
