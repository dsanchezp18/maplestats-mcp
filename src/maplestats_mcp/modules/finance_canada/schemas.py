"""Typed responses for the Fiscal Reference Tables and The Fiscal Monitor."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Value = float | int | str | None


class FrtEdition(BaseModel):
    edition: int = Field(description="Edition year, e.g. 2025 (data to fiscal 2024-25).")
    title: str
    published: str | None = Field(default=None, description="Release date, YYYY-MM-DD.")
    page_url: str
    workbook_url: str


class FrtTableInfo(BaseModel):
    number: int = Field(description="The table number in the edition, e.g. 3.")
    title: str
    part: str | None = Field(
        default=None, description="Federal, provinces and territories, national accounts or G7."
    )
    sheet: str
    columns: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list, description="Units stated in the header.")
    row_count: int
    first_row: str | None = Field(default=None, description="First row label, e.g. '1966-67'.")
    last_row: str | None = None


class FrtTableList(BaseModel):
    editions: list[FrtEdition] = Field(default_factory=list)
    edition: int
    tables: list[FrtTableInfo] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance


class FrtTable(BaseModel):
    edition: FrtEdition
    info: FrtTableInfo
    rows: list[dict[str, Value]] = Field(
        default_factory=list,
        description="Rows keyed by column; the first column is the row label (a fiscal or "
        "calendar year, or an item). A 'section' key carries the heading a row sits under.",
    )
    notes: list[str] = Field(default_factory=list, description="Sources and footnotes.")
    provenance: Provenance


class MonitorIssue(BaseModel):
    period: str = Field(description="YYYY-MM of the issue's (last) month, e.g. '2026-07'.")
    title: str
    published: str | None = None
    url: str


class MonitorIssueList(BaseModel):
    issues: list[MonitorIssue] = Field(default_factory=list)
    provenance: Provenance


class MonitorTable(BaseModel):
    label: str = Field(description="e.g. 'Table 2 Revenues' or 'Chart 1 ...' (chart data).")
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Value]] = Field(default_factory=list)


class MonitorTables(BaseModel):
    issue: MonitorIssue
    tables: list[MonitorTable] = Field(default_factory=list)
    provenance: Provenance
