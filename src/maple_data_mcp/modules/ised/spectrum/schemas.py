"""Typed responses for ISED's Spectrum Management System licence site data."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class LicenceQueryResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    returned_count: int
    limit: int
    offset: int
    where: str
    exceeded_transfer_limit: bool = False
    provenance: Provenance
