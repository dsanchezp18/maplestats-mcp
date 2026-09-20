"""Typed responses for the City of Grande Prairie's ArcGIS Hub deployment."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ItemSummary(BaseModel):
    id: str
    title: str
    description_excerpt: str
    item_type: str
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    owner: str | None = None
    modified_at: datetime | None = None
    num_views: int = 0
    landing_page_url: str


class DatasetSearchResult(BaseModel):
    items: list[ItemSummary]
    total_count: int
    returned_count: int
    limit: int
    offset: int
    query: str
    provenance: Provenance


class DownloadLink(BaseModel):
    format: str
    url: str


class ItemDetail(BaseModel):
    id: str
    title: str
    description: str
    item_type: str
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    owner: str | None = None
    license_info: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    num_views: int = 0
    extent: dict[str, Any] | None = None
    spatial_reference_wkid: str | None = None
    service_url: str | None = None
    landing_page_url: str
    download_urls: list[DownloadLink] = Field(default_factory=list)
    provenance: Provenance


class FeatureQueryResult(BaseModel):
    item_id: str
    layer_index: int
    rows: list[dict[str, Any]]
    returned_count: int
    limit: int
    offset: int
    where: str
    exceeded_transfer_limit: bool = False
    provenance: Provenance
