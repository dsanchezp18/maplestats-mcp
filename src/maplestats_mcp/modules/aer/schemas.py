from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class WellLicenceDailyReport(BaseModel):
    day: str
    report_date: date | None
    expected_date: date | None = Field(
        default=None, description="The most recent date with this weekday, in Alberta time."
    )
    note: str | None = Field(
        default=None,
        description="Set when the file still holds an older week's list than expected_date.",
    )
    raw_text: str
    provenance: Provenance


class WellLicenceArchiveLink(BaseModel):
    year: int
    month: int | None
    url: str
    exists: bool
    size_bytes: int | None
    note: str | None = None
    provenance: Provenance


class ProductionVolumesLink(BaseModel):
    product: str
    url: str
    exists: bool
    size_bytes: int | None
    last_modified: str | None
    provenance: Provenance


class St98Edition(BaseModel):
    edition: int = Field(description="Edition year, e.g. 2026 (history to 2025, forecast 2026+).")
    workbook_url: str = Field(description="The executive-summary data workbook (.xlsx).")
    report_url: str | None = Field(
        default=None, description="The edition's report or executive summary (PDF)."
    )


class St98Series(BaseModel):
    series: str = Field(
        description="Column label built from the workbook headers, with its unit, e.g. "
        "'Crude oil (petajoules)' or 'Number of wells drilled - Bitumen'."
    )
    unit: str | None = Field(default=None, description="Unit stated in the header, if any.")


class St98TableInfo(BaseModel):
    table: str = Field(description="Id to pass to aer_st98_get_table, e.g. 'figure_8'.")
    title: str = Field(
        description="The figure caption in the edition's report, or the table title."
    )
    heading: str = Field(description="The block's own heading in the workbook, e.g. 'Figure 8'.")
    sheet: str
    series: list[St98Series] = Field(default_factory=list)
    rows: int = Field(description="Rows in the block (years, months or items).")
    first_year: int | None = None
    last_year: int | None = None
    has_forecast: bool = Field(
        description="True when some rows are the edition year or later: AER's forecast."
    )


class St98TableList(BaseModel):
    editions: list[St98Edition] = Field(default_factory=list)
    edition: int
    forecast_from: int = Field(description="First forecast year of this edition (= the edition).")
    tables: list[St98TableInfo] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance


class St98Observation(BaseModel):
    series: str = Field(description="Column label with its unit (see St98Series).")
    category: str | None = Field(
        default=None,
        description="Row label when the row is an item, not a period, e.g. 'Proved "
        "Developed Producing (PDP)', 'Total', or 'Duvernay Formation - 2P Producing & "
        "Undeveloped Reserves'.",
    )
    year: int | None = Field(default=None, description="Calendar year of the row, if it is one.")
    period: str | None = Field(default=None, description="YYYY-MM for monthly rows.")
    row_label: str = Field(description="The row label as published, e.g. '2014c', 'Pre-1972'.")
    value: float | None
    unit: str | None = None
    marker: str | None = Field(
        default=None,
        description="Footnote letter glued to the value ('a', 'b') or the marker printed "
        "instead of one ('*' included elsewhere, '**' not available, '-' none); see notes.",
    )
    forecast: bool | None = Field(
        default=None,
        description="True for the edition year and later (AER's forecast), false for history, "
        "null for rows that are not a year.",
    )
    estimated: bool = Field(
        default=False, description="The notes say this year's values are estimated."
    )
    edition: int


class St98Table(BaseModel):
    edition: St98Edition
    table: str
    title: str
    heading: str
    forecast_from: int
    series: list[St98Series] = Field(default_factory=list)
    observations: list[St98Observation] = Field(default_factory=list)
    total_observations: int = Field(description="Observations matching the filters.")
    notes: list[str] = Field(
        default_factory=list, description="Sources and footnotes, as published."
    )
    provenance: Provenance
