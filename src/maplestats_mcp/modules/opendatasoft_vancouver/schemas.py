"""Typed responses for the City of Vancouver's Opendatasoft deployment."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    id: str
    title: str
    description_excerpt: str
    theme: list[str] = Field(default_factory=list)
    keyword: list[str] = Field(default_factory=list)
    records_count: int = 0
    modified: datetime | None = None
    landing_page_url: str


class DatasetSearchResult(BaseModel):
    datasets: list[DatasetSummary]
    total_count: int
    returned_count: int
    limit: int
    offset: int
    query: str
    provenance: Provenance


class FieldInfo(BaseModel):
    name: str
    label: str | None = None
    type: str
    description: str | None = None


class DownloadLink(BaseModel):
    format: str
    url: str


class DatasetDetail(BaseModel):
    id: str
    title: str
    description: str
    theme: list[str] = Field(default_factory=list)
    keyword: list[str] = Field(default_factory=list)
    license_name: str | None = None
    license_url: str | None = None
    publisher: str | None = None
    update_frequency: str | None = None
    records_count: int = 0
    modified: datetime | None = None
    fields: list[FieldInfo] = Field(default_factory=list)
    landing_page_url: str
    download_urls: list[DownloadLink] = Field(default_factory=list)
    provenance: Provenance


class RecordQueryResult(BaseModel):
    dataset_id: str
    rows: list[dict[str, Any]]
    returned_count: int
    total_count: int
    limit: int
    offset: int
    select: str | None = None
    where: str | None = None
    order_by: str | None = None
    query: str | None = None
    provenance: Provenance
