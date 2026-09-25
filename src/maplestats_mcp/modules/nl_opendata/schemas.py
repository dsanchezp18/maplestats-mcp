"""Typed responses for Open Data Newfoundland and Labrador."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    """One row from a tabular, spatial, or tag-filtered listing page."""

    id: str
    title: str
    dataset_type: str | None = None
    released_date: date | None = None
    modified_date: date | None = None
    publisher: str | None = None
    creator: str | None = None
    landing_page_url: str


class DatasetSearchResult(BaseModel):
    datasets: list[DatasetSummary]
    total_count: int = Field(
        description="Number of matching records before the local offset/limit page."
    )
    returned_count: int
    limit: int
    offset: int
    query: str
    dataset_type: str
    provenance: Provenance


class DatasetFile(BaseModel):
    """One file listed on a dataset detail page.

    The catalogue exposes a human-readable size and, in parentheses, a byte
    count. ``size_bytes`` is null when the portal does not provide that count.
    """

    id: str
    title: str
    revision: int | None = None
    format: str | None = None
    revision_date: date | None = None
    size_display: str | None = None
    size_bytes: int | None = None
    download_url: str


class DatasetDetail(BaseModel):
    id: str
    title: str
    dataset_type: str | None = None
    creator: str | None = None
    contact_email: str | None = None
    geographic_coverage: str | None = None
    contributor: str | None = None
    publisher: str | None = None
    temporal_coverage: str | None = None
    released_date: date | None = None
    modified_date: date | None = None
    rights: str | None = None
    topics: list[str] = Field(default_factory=list)
    files: list[DatasetFile] = Field(default_factory=list)
    landing_page_url: str
    licence_url: str
    provenance: Provenance


class TagSummary(BaseModel):
    id: str
    name: str
    landing_page_url: str


class TagList(BaseModel):
    tags: list[TagSummary]
    total_count: int
    provenance: Provenance
