"""Typed response models for the ONS module.

Field names follow the ONS answers read live on 2026-11-08: search items carry
`cdid`, `dataset_id`, `title`, `uri` and `release_date`; a time series page's
`/data` JSON has `description` (title, cdid, unit, releaseDate, nextRelease,
datasetId) and `months`, `quarters` and `years` lists of {date, value}.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class SeriesSummary(BaseModel):
    series_id: str = Field(description="ONS series id (CDID), e.g. D7G7.")
    dataset: str = Field(description="ONS dataset id, e.g. MM23 (consumer price inflation).")
    title: str
    release_date: str | None = None
    url: str = Field(description="The series' page on ons.gov.uk.")


class SeriesSearch(BaseModel):
    query: str
    total_matches: int
    series: list[SeriesSummary] = Field(description="Best matches first.")
    provenance: Provenance


class Observation(BaseModel):
    period: str = Field(description="2026-09 (month), 2026-Q3 (quarter) or 2026 (year).")
    value: float


class SeriesResult(BaseModel):
    series_id: str
    dataset: str
    title: str
    unit: str | None = None
    frequency: str = Field(description="monthly, quarterly or annual.")
    available_frequencies: list[str]
    release_date: str | None = None
    next_release: str | None = Field(default=None, description="As the ONS writes it.")
    observations: list[Observation] = Field(description="Oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None
    other_datasets: list[str] = Field(
        default_factory=list,
        description="Other ONS datasets that publish the same series id.",
    )
    url: str
    csv_url: str = Field(description="The whole series as CSV from ons.gov.uk.")
    citation: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class IndicatorResult(BaseModel):
    indicator: str
    indicator_label: str
    series_id: str
    dataset: str
    title: str
    unit: str | None = None
    frequency: str
    release_date: str | None = None
    next_release: str | None = None
    observations: list[Observation] = Field(description="Oldest first.")
    latest_period: str | None = None
    latest_value: float | None = None
    canada_counterpart: str = Field(
        description="Where Canada's comparable figure is in MapleStats, and how it differs."
    )
    url: str
    csv_url: str
    citation: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
