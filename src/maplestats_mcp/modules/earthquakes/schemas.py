"""Typed responses for the Earthquakes Canada event service."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Earthquake(BaseModel):
    event_id: str
    time: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    depth_km: float | None = None
    magnitude: float | None = None
    magnitude_type: str | None = None
    location: str | None = Field(default=None, description="Region name, e.g. '23 km W of X'.")


class EarthquakeSearchResult(BaseModel):
    earthquakes: list[Earthquake] = Field(description="Most recent first.")
    total_matches: int
    returned_count: int
    provenance: Provenance
