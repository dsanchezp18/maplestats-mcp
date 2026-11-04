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
    total_in_feed: int = Field(default=0, description="Releases in the subject's feed.")
    truncated: bool = Field(default=False, description="True when the feed holds more.")
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


class DailyArticleSection(BaseModel):
    heading: str | None = Field(
        default=None, description="Section heading; null for the text before the first heading."
    )
    text: str = Field(description="The section's paragraphs and list items as plain text.")


class DailyArticleLink(BaseModel):
    text: str
    url: str


class DailyArticleTable(BaseModel):
    table_id: str = Field(description="StatCan table number, e.g. '12-10-0011-01'.")
    product_id: int = Field(description="8-digit product id for the wds_ tools, e.g. 12100011.")


class DailyArticle(BaseModel):
    url: str = Field(description="The article page that was read (www150.statcan.gc.ca).")
    article_id: str = Field(description="Article id such as 'dq261104a'.")
    title: str
    release_date: date | None = None
    archived: bool = Field(
        default=False,
        description="StatCan marks the page archived: kept for reference, not updated; a "
        "newer release of the same data usually exists.",
    )
    summary: str | None = Field(default=None, description="The page's own one-paragraph summary.")
    sections: list[DailyArticleSection] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list, description="Chart titles, in page order.")
    tables: list[DailyArticleTable] = Field(
        default_factory=list, description="StatCan tables the article text links to."
    )
    pdf_url: str | None = Field(default=None, description="The article as a PDF, when linked.")
    tables_page_url: str | None = Field(
        default=None, description="The article's 'Tables' tab: every table of the release."
    )
    related_info_url: str | None = None
    previous_release_url: str | None = None
    links: list[DailyArticleLink] = Field(
        default_factory=list,
        description="Other links in the body: products, related articles, the article's own tables.",
    )
    word_count: int
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
