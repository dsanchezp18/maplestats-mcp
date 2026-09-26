"""Typed responses for Canadian Grain Commission statistics."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

WeeklyDimension = Literal["worksheet", "metric", "period", "grain", "grade", "region"]
ExportDimension = Literal["grain", "grade", "elevator", "region", "global_region", "destination"]
ExportFrequency = Literal["month", "year", "crop_year"]

UNIT = "thousand tonnes"


class CgcWeek(BaseModel):
    week: int = Field(description="CGC grain week; week 1 ends on the first Sunday of August.")
    week_ending: date | None = Field(default=None, description="The Sunday the week ends on.")


class CgcWorksheet(BaseModel):
    worksheet: str
    row_count: int
    metrics: list[str] = Field(default_factory=list)
    periods: list[str] = Field(
        default_factory=list,
        description="'Current Week' (that week alone) and/or 'Crop Year' (to date).",
    )
    grains: list[str] = Field(default_factory=list)
    regions: list[str] = Field(
        default_factory=list,
        description="Provinces, port regions or destinations, depending on the worksheet.",
    )
    grades: list[str] = Field(default_factory=list)
    grades_total: int = Field(description="Number of distinct grades; `grades` may be capped.")
    has_national_rows: bool = Field(
        default=False,
        description="True when some rows have no region: national totals (Process worksheet).",
    )


class CgcWeeklyDescription(BaseModel):
    crop_year: str = Field(description="e.g. '2026-27' (August 2026 to July 2027).")
    lang: Literal["en", "fr"]
    available_crop_years: list[str] = Field(default_factory=list)
    weeks: list[CgcWeek] = Field(default_factory=list)
    latest_week: int | None = None
    latest_week_ending: date | None = None
    row_count: int
    unit: str = UNIT
    worksheets: list[CgcWorksheet] = Field(default_factory=list)
    provenance: Provenance


class CgcWeeklyRow(BaseModel):
    week: int
    week_ending: date | None = None
    worksheet: str | None = None
    metric: str | None = None
    period: str | None = None
    grain: str | None = None
    grade: str | None = None
    region: str | None = Field(
        default=None,
        description="None on a raw row means a national total; on a summed row, not grouped.",
    )
    ktonnes: float | None = Field(
        default=None, description="Thousands of tonnes; None when the file leaves it blank."
    )
    cells: int | None = Field(
        default=None, description="Summed results only: how many published values were added."
    )
    blank_cells: int | None = Field(
        default=None, description="Summed results only: how many of those cells were blank."
    )


class CgcWeeklyResult(BaseModel):
    crop_year: str
    lang: Literal["en", "fr"]
    worksheet: str
    filters: dict[str, list[str]] = Field(default_factory=dict)
    group_by: list[WeeklyDimension] | None = None
    latest_week: int | None = None
    latest_week_ending: date | None = None
    unit: str = UNIT
    rows: list[CgcWeeklyRow] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    truncated: bool = False
    provenance: Provenance


class CgcExportsDescription(BaseModel):
    lang: Literal["en", "fr"]
    first_month: str | None = Field(default=None, description="e.g. '2013-01'.")
    latest_month: str | None = Field(default=None, description="e.g. '2026-07'.")
    row_count: int
    unit: str = UNIT
    grains: list[str] = Field(default_factory=list)
    elevators: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list, description="Port or shipping region.")
    global_regions: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    grades: list[str] = Field(default_factory=list)
    grades_total: int
    provenance: Provenance


class CgcExportRow(BaseModel):
    period: str = Field(
        description="'2026-07' by month, '2025' by calendar year, '2025-26' by crop year."
    )
    year: int | None = Field(default=None, description="Calendar year (month and year rows).")
    month: int | None = Field(default=None, description="1-12 (month rows).")
    grain: str | None = None
    grade: str | None = None
    elevator: str | None = None
    region: str | None = None
    global_region: str | None = None
    destination: str | None = None
    ktonnes: float
    cells: int | None = Field(
        default=None, description="Summed results only: how many published rows were added."
    )
    months: int | None = Field(
        default=None,
        description=(
            "Year and crop-year rows only: months the file covers in the period (under 12 "
            "at the edges of the series, e.g. the current crop year)."
        ),
    )


class CgcExportsResult(BaseModel):
    lang: Literal["en", "fr"]
    frequency: ExportFrequency
    filters: dict[str, list[str]] = Field(default_factory=dict)
    group_by: list[ExportDimension] | None = None
    latest_month: str | None = None
    unit: str = UNIT
    rows: list[CgcExportRow] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    truncated: bool = False
    total_ktonnes: float = Field(description="Sum of every matched value, before any row cap.")
    provenance: Provenance
