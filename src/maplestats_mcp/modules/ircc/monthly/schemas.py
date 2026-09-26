"""Typed responses for IRCC's monthly open data tables."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Period = Literal["month", "quarter", "year"]


class IrccTable(BaseModel):
    table_id: str = Field(description="File stem, e.g. 'ODP-PR-PT_IMMCAT'; pass to the query tool.")
    title: str
    dataset: str
    dataset_id: str
    archived: bool = Field(description="The dataset is marked ARCHIVED and no longer updated.")
    csv_url: str


class IrccTableCatalogue(BaseModel):
    tables: list[IrccTable] = Field(default_factory=list)
    returned_count: int
    total_tables: int
    provenance: Provenance


class IrccDimension(BaseModel):
    key: str = Field(description="Filter and group_by key, e.g. 'province_territory'.")
    column: str = Field(description="The file's English column, e.g. 'EN_PROVINCE_TERRITORY'.")
    column_fr: str | None = None
    value_count: int
    values: list[str] = Field(
        default_factory=list, description="Distinct values in `lang`, capped."
    )


class IrccTableDescription(BaseModel):
    table_id: str
    title: str
    dataset: str
    periods: list[Period] = Field(
        default_factory=list, description="Time grains the table supports; empty if it has none."
    )
    first_period: str | None = None
    last_period: str | None = None
    row_count: int
    suppressed_cells: int
    dimensions: list[IrccDimension] = Field(default_factory=list)
    value_column: str
    note: str
    provenance: Provenance


class IrccRow(BaseModel):
    period: str | None = Field(
        default=None, description="'YYYY-MM', 'YYYY-Qn' or 'YYYY'; None when the table has no time."
    )
    dimensions: dict[str, str] = Field(default_factory=dict)
    value: int | None = Field(
        default=None, description="Rounded count; None when every cell summed was suppressed."
    )
    cells: int = Field(description="Number of file rows summed into this row (1 when ungrouped).")
    suppressed_cells: int = Field(
        description="Cells shown as '--' (1 to 4), counted as 0 in value."
    )


class IrccQueryResult(BaseModel):
    table_id: str
    title: str
    rows: list[IrccRow] = Field(default_factory=list)
    returned_count: int
    total_matched: int = Field(description="Result rows before `limit`.")
    matched_cells: int = Field(description="File rows that passed the filters.")
    applied_filters: dict[str, str] = Field(
        default_factory=dict, description="File column -> English value actually matched."
    )
    group_by: list[str] = Field(default_factory=list)
    period: Period | None = None
    value_column: str
    note: str
    provenance: Provenance
