"""Typed responses for the Canadian Trademarks Database (CIPO) search API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TrademarkRecord(BaseModel):
    id: str
    application_number: str
    mark_name: str
    mark_type: str | None = None
    status_code: int | None = None
    status_description: str | None = None
    nice_classes: list[int] = Field(default_factory=list)
    international_registration_numbers: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)


class TrademarkSearchResult(BaseModel):
    records: list[TrademarkRecord] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    search_field: str
    criteria: str
    provenance: Provenance
