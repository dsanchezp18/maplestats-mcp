"""Typed response models for the US Bureau of Labor Statistics module.

Field names follow the Public Data API v2 as read live on 2026-11-07:
`Results.series[]` with `seriesID` and `data[]` rows of `year`, `period`
(M01-M13, Q01-Q05, S01-S03, A01), `periodName`, `value` (a string, "-" when
the BLS has no value), `latest` and `footnotes[]` (`code`, `text`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Release(BaseModel):
    name: str = Field(description="The BLS news release that publishes the series.")
    schedule_url: str = Field(description="That release's schedule of upcoming dates.")


class Observation(BaseModel):
    year: int
    period: str = Field(description="BLS period code: M01-M12, M13 (annual average), Q01-Q04.")
    period_name: str
    date: str = Field(description="ISO-style period: 2026-10, 2026-Q3, 2026-S1 or 2026.")
    value: float | None = Field(description="None where the BLS shows '-' (no value).")
    preliminary: bool = Field(description="True when footnoted P (preliminary) or I (initial).")
    footnotes: list[str] = Field(default_factory=list)
    change_from_previous: float | None = Field(
        default=None,
        description="value minus the previous period's value, computed by MapleStats.",
    )
    pct_change_from_year_ago: float | None = Field(
        default=None,
        description=(
            "Per cent change from the same period a year earlier, computed by MapleStats "
            "(for the CPI, the 12-month inflation rate)."
        ),
    )


class Series(BaseModel):
    series_id: str
    title: str | None = Field(
        default=None,
        description="From this module's list of known series; None for other ids.",
    )
    survey: str = Field(description="Two-letter survey prefix, e.g. CE, LN, CU.")
    seasonal_adjustment: str | None = Field(
        default=None, description="'seasonally adjusted', 'not seasonally adjusted' or None."
    )
    units: str | None = None
    frequency: str | None = Field(
        default=None, description="monthly, quarterly, semiannual, annual."
    )
    release: Release | None = None
    observations: list[Observation] = Field(description="Oldest first.")
    latest_date: str | None = None
    latest_value: float | None = None


class SeriesResult(BaseModel):
    series: list[Series]
    start_year: int
    end_year: int
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class IndicatorResult(BaseModel):
    indicator: str
    label: str
    seasonally_adjusted: bool
    series: Series
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class SeriesMatch(BaseModel):
    series_id: str
    title: str | None = None
    survey: str
    seasonal_adjustment: str | None = None
    units: str | None = None
    popular: bool = Field(default=False, description="Listed among the BLS's popular series.")


class SearchResult(BaseModel):
    query: str
    survey: str | None = None
    matches: list[SeriesMatch]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class Survey(BaseModel):
    code: str = Field(description="Two-letter prefix that starts the survey's series ids.")
    name: str = Field(description="The BLS's own survey name (English).")


class SurveyList(BaseModel):
    surveys: list[Survey]
    provenance: Provenance
