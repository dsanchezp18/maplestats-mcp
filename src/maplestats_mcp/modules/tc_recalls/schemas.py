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
    recalls: list[RecallRow]
    returned_count: int
    page: int
    limit: int
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
        default=None, description="Issue, safety risk, and corrective action."
    )
    affected_vehicles: list[AffectedVehicle]
    provenance: Provenance
