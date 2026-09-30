"""Typed responses for the Yukon Bureau of Statistics module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TableEntry(BaseModel):
    dataset: str = Field(description="Dataset name on open.yukon.ca.")
    dataset_title: str
    title: str = Field(description="The table's title.")
    url: str = Field(description="Pass this to yukon_stats_query_table.")
    modified: datetime | None = None


class TableList(BaseModel):
    tables: list[TableEntry]
    total_tables: int
    truncated: bool
    licence: str
    provenance: Provenance


class TableRows(BaseModel):
    url: str
    columns: list[str] = Field(description="Selected columns, in order.")
    all_columns: list[str] = Field(description="Every column the file has (footnotes dropped).")
    rows: list[dict[str, str]]
    total_rows: int = Field(description="Rows that matched the filters, before offset and limit.")
    offset: int
    truncated: bool
    licence: str
    provenance: Provenance
