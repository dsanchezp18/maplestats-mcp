"""Typed responses for ISQ detailed tables."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Value = float | int | str | None


class IsqTableHit(BaseModel):
    table: str = Field(description="The table's page slug; pass it to isq_get_table.")
    title: str = Field(description="Read from the slug; isq_get_table gives the exact title.")
    lang: Literal["en", "fr"]
    url: str


class IsqSearchResult(BaseModel):
    tables: list[IsqTableHit] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class IsqTable(BaseModel):
    title: str
    url: str | None = None
    number: int | None = Field(default=None, description="ISQ table number (dynamic tables).")
    kind: Literal["dynamic", "static"]
    updated: str | None = None
    subjects: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Value]] = Field(
        default_factory=list,
        description="Dynamic tables: one dict per row, keyed by column label.",
    )
    flags: list[dict[str, str]] = Field(
        default_factory=list,
        description="Per returned row, column label -> ISQ flag (r, p, x, F, ...).",
    )
    cells: list[list[str]] = Field(
        default_factory=list, description="Static tables: rows of cell text as published."
    )
    returned_count: int
    total_rows: int
    notes: str | None = Field(default=None, description="Notes and sources, as text.")
    flag_legend: dict[str, str] = Field(default_factory=dict)
    excel_url: str | None = None
    provenance: Provenance
