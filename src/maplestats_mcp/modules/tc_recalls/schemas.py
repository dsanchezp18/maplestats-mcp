"""Typed responses for Transport Canada's vehicle recall API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class RecallRow(BaseModel):
    recall_number: str
    manufacturer: str | None = None
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    recall_date: date | None = None


class RecallSearchResult(BaseModel):
    recalls: list[RecallRow] = Field(description="In recall-date order, as `order` says.")
    returned_count: int
    total_matched: int = Field(description="Recalls matching the filters, all pages.")
    has_more: bool = Field(description="True when a later page holds more recalls.")
    order: str = Field(description="'newest' (recall date, newest first) or 'oldest'.")
    page: int
    limit: int
    note: str | None = None
    provenance: Provenance


class AffectedVehicle(BaseModel):
    make: str | None = None
    model: str | None = None
    model_year: int | None = None


class RecallDetail(BaseModel):
    recall_number: str
    manufacturer_recall_number: str | None = None
    recall_date: date | None = None
    category: str | None = None
    system: str | None = None
    notification_type: str | None = None
    units_affected: int | None = None
    description: str | None = Field(
        default=None, description="Issue, safety risk, and corrective action (LF line breaks)."
    )
    affected_vehicles: list[AffectedVehicle]
    provenance: Provenance
