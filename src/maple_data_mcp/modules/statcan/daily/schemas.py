"""Typed responses for The Daily's Atom feeds."""

from __future__ import annotations

from datetime import datetime

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
