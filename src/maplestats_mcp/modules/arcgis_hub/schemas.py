"""Typed responses for the shared ArcGIS Hub portal family."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

# Kept in sync with constants.PORTALS by a unit test -- a Literal is what
# puts the valid portal keys into each tool's JSON schema.
PortalKey = Literal[
    "mb",
    "sk",
    "pe",
    "hamilton",
    "london",
    "kitchener",
    "windsor",
    "saskatoon",
    "victoria",
    "surrey",
    "ottawa",
    "halifax",
    "mississauga",
    "peel",
    "durham",
    "waterloo_region",
    "metro_vancouver",
    "york",
    "markham",
    "newmarket",
    "aurora",
    "medicine_hat",
    "grande_prairie",
    "grande_prairie_county",
    "st_albert",
    "lethbridge",
    "airdrie",
    "strathcona_county",
    "parkland_county",
    "sturgeon_county",
    "emrb",
    "alberta_geological_survey",
    "red_deer",
]


class PortalInfo(BaseModel):
    portal: str
    name: str
    domain: str
    bilingual_content: bool
    note: str | None = None


class PortalList(BaseModel):
    portals: list[PortalInfo]
    provenance: Provenance


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
    portal: str
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
    portal: str
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
    portal: str
    item_id: str
    layer_index: int
    rows: list[dict[str, Any]]
    returned_count: int
    limit: int
    offset: int
    where: str
    exceeded_transfer_limit: bool = False
    provenance: Provenance
