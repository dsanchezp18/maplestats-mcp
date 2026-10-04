"""Typed response models for the MSC GeoMet coverage tools.

Shapes confirmed live on 2026-10-03 (see client.py's module docstring):
`/collections/{id}?f=json` carries the axes in `extent` (`temporal`,
`scenario`, `percentile`, `season`, `P20Y-Avg`/`P30Y-Avg`), the variables
come from `/collections/{id}/schema?f=json`, and data comes from
`/collections/{id}/coverage?f=json` as CoverageJSON.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CoverageVariable(BaseModel):
    name: str = Field(description="Variable id to pass in `variables`, e.g. 'AirTemp' or 'tas'.")
    title: str | None = None
    unit: str | None = None


class TimeRange(BaseModel):
    start: str
    end: str
    resolution: str | None = Field(
        default=None, description="ISO 8601 step: P1Y (one value per year) or P1M (per month)."
    )


class CoverageCollection(BaseModel):
    id: str
    title: str
    family: str = Field(description="Dataset family: candcsu6, cmip5, dcs, indices, spei-1, ...")
    timeframe: str | None = Field(default=None, description="historical or projected.")
    frequency: str | None = Field(default=None, description="annual, seasonal or monthly.")
    variables: list[CoverageVariable] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    percentiles: list[float] = Field(default_factory=list)
    seasons: list[str] = Field(default_factory=list)
    averaging_periods: list[str] = Field(
        default_factory=list,
        description="20- or 30-year windows (e.g. '2071-2100') for the P20Y-Avg/P30Y-Avg sets.",
    )
    time_range: TimeRange | None = None


class CoverageCollectionList(BaseModel):
    collections: list[CoverageCollection]
    total_count: int = Field(description="Collections matching the filters, before `limit`.")
    provenance: Provenance


class CoverageDescription(CoverageCollection):
    description: str
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north] in decimal degrees."
    )
    grid_resolution: list[float] | None = Field(
        default=None,
        description="[x, y] cell size: degrees, or metres for CanGRD's polar stereographic grid.",
    )
    crs: str | None = Field(default=None, description="CRS of the grid cells in a response.")
    canonical_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class CoverageRow(BaseModel):
    """One value: one grid cell, one time step, one variable and one selection."""

    time: str | None = Field(
        default=None,
        description="Year (YYYY) or month (YYYY-MM); for a 20/30-year average, "
        "the first year of the window.",
    )
    value: float
    unit: str | None = None
    variable: str
    scenario: str | None = None
    percentile: float | None = None
    season: str | None = None
    averaging_period: str | None = None
    lat: float = Field(description="Grid cell centre latitude.")
    lon: float = Field(description="Grid cell centre longitude.")


class CoverageData(BaseModel):
    collection_id: str
    rows: list[CoverageRow]
    total_rows: int = Field(description="Non-missing values found before the `max_rows` cap.")
    truncated: bool
    missing_values_skipped: int = Field(
        description="Grid values the source returned as null (ocean, outside the data mask)."
    )
    requests_made: int
    point_distance_km: float | None = Field(
        default=None,
        description="For a point request: distance from the point to the chosen cell centre.",
    )
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
