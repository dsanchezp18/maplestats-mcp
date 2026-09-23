"""Typed responses for the Canadian Socrata (SODA) portal family."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance

# Kept in sync with constants.PORTALS by a unit test.
PortalKey = Literal["ns", "nb", "calgary", "edmonton", "winnipeg"]


class PortalInfo(BaseModel):
    portal: str
    name: str
    domain: str
    bilingual_content: bool


class PortalList(BaseModel):
    portals: list[PortalInfo]
    provenance: Provenance


class ColumnInfo(BaseModel):
    name: str
    field_name: str
    data_type: str
    description: str | None = None


class DatasetSummary(BaseModel):
    id: str
    name: str
    description_excerpt: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    dataset_type: str
    updated_at: datetime | None = None
    download_count: int = 0
    permalink: str
    landing_page_url: str


class DatasetSearchResult(BaseModel):
    portal: str
    datasets: list[DatasetSummary]
    total_count: int
    returned_count: int
    limit: int
    offset: int
    query: str
    provenance: Provenance


class DatasetDetail(BaseModel):
    portal: str
    id: str
    name: str
    description: str
    category: str | None = None
    attribution: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    columns: list[ColumnInfo]
    created_at: datetime | None = None
    rows_updated_at: datetime | None = None
    publication_date: datetime | None = None
    download_count: int = 0
    view_count: int = 0
    landing_page_url: str
    csv_download_url: str
    query_url: str
    provenance: Provenance


class RowQueryResult(BaseModel):
    portal: str
    dataset_id: str
    rows: list[dict[str, Any]]
    returned_count: int
    limit: int
    offset: int
    select: str | None = None
    where: str | None = None
    order: str | None = None
    q: str | None = None
    provenance: Provenance


class CategoryCount(BaseModel):
    category: str
    dataset_count: int


class CategoryList(BaseModel):
    portal: str
    categories: list[CategoryCount]
    provenance: Provenance


class TagCount(BaseModel):
    tag: str
    dataset_count: int


class TagList(BaseModel):
    portal: str
    tags: list[TagCount]
    provenance: Provenance
