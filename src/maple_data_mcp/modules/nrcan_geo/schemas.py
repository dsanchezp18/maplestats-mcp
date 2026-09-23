"""Typed responses for NRCan's Geolocator and geographical names APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class Location(BaseModel):
    name: str
    province: str | None = None
    category: str | None = None
    latitude: float
    longitude: float
    bbox: list[float] | None = Field(default=None, description="[west, south, east, north]")
    source: str | None = Field(default=None, description="Backing index, e.g. 'fsa', 'nominatim'.")


class LocationResult(BaseModel):
    query: str
    locations: list[Location]
    provenance: Provenance


class PlaceName(BaseModel):
    id: str
    name: str
    feature_type: str | None = Field(default=None, description="e.g. 'CITY-City', 'LAKE-Lake'.")
    status: str | None = None
    province: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location: str | None = Field(default=None, description="Legal land description, if any.")
    map_sheets: list[str] = Field(default_factory=list)
    decision_date: str | None = None


class PlaceNameResult(BaseModel):
    names: list[PlaceName]
    returned_count: int
    provenance: Provenance
