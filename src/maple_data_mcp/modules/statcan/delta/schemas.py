"""Typed responses for StatCan's Delta File archive."""

from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class DeltaFileLink(BaseModel):
    date: str
    url: str
    exists: bool
    size_bytes: int | None = None
    provenance: Provenance
