"""Typed responses for the federal election results module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

TableName = Literal[
    "turnout",
    "seats",
    "votes_by_party",
    "vote_share_by_party",
    "district_results",
    "candidates",
    "returning_officers",
]


class ElectionInfo(BaseModel):
    election: int = Field(description="General election number, e.g. 45 for April 28, 2025.")
    date: str = Field(description="Polling day, YYYY-MM-DD.")
    page: str = Field(description="Elections Canada page listing this election's data tables.")


class TableInfo(BaseModel):
    table: str = Field(description="Table name to pass to elections_results_get_table.")
    number: int = Field(description="Table number on elections.ca (the same in every election).")
    description: str


class ElectionList(BaseModel):
    elections: list[ElectionInfo]
    tables: list[TableInfo]
    not_covered: list[str]
    provenance: Provenance


class ElectionTable(BaseModel):
    election: int
    date: str
    table: str
    description: str
    file_url: str
    columns: list[str] = Field(description="Column names exactly as Elections Canada publishes.")
    rows: list[dict[str, str]] = Field(
        description="Rows as published (values are text; bilingual headers and names)."
    )
    total_rows: int = Field(description="Rows that matched the filters, before offset and limit.")
    offset: int
    truncated: bool
    provenance: Provenance
