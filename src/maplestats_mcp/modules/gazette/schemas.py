"""Typed responses for the Canada Gazette."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Issue(BaseModel):
    part: int
    date: date
    title: str
    url: str


class IssueList(BaseModel):
    issues: list[Issue]
    total_in_feed: int = Field(
        default=0, description="Issues in the RSS feed, before `limit` is applied."
    )
    provenance: Provenance


class Notice(BaseModel):
    title: str
    section: str | None = None
    organization: str | None = None
    act: str | None = None
    url: str = Field(description="Pass to gazette_get_notice.")


class IssueNotices(BaseModel):
    part: int
    date: date
    url: str
    notices: list[Notice]
    provenance: Provenance


class NoticeText(BaseModel):
    url: str
    title: str | None = None
    text: str
    truncated: bool = False
    provenance: Provenance
