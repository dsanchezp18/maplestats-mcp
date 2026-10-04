"""Typed responses for the Newfoundland and Labrador Statistics Agency module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TopicInfo(BaseModel):
    topic: str = Field(description="Topic slug, as used by nl_stats_list_files.")
    title: str
    page_url: str


class FileEntry(BaseModel):
    topic: str
    section: str | None = Field(description="Heading on the topic page, e.g. 'Quarterly Data'.")
    title: str = Field(description="The agency's own description of the table.")
    url: str = Field(description="Pass this to nl_stats_read_file.")
    format: str = Field(description="'xlsx' or 'xls'.")


class FileList(BaseModel):
    topics: list[TopicInfo]
    files: list[FileEntry]
    total_files: int
    truncated: bool
    provenance: Provenance


class SheetInfo(BaseModel):
    name: str
    rows: int
    columns: int


SheetChoice = Literal["request", "newest_month", "first"]


class FileData(BaseModel):
    url: str
    format: str
    sheets: list[SheetInfo]
    sheet: str
    sheet_chosen_by: SheetChoice = Field(
        description="'request' (the sheet argument), 'newest_month' (no sheet was asked and "
        "the sheets are named after months, so the newest was read) or 'first'."
    )
    header_row: int | None = Field(
        description="1-based row number holding the column names: the one requested, else "
        "guessed as the first row with at least three filled cells; null when none looks "
        "like a header."
    )
    header_rows: int = Field(
        description="Rows joined per column into `header` (from header_row down); 0 when "
        "no header was found."
    )
    header: list[str]
    rows: list[list[str]] = Field(
        description="Rows as published (text), after the header row when one was guessed."
    )
    total_rows: int = Field(description="Rows that matched `contains`, before offset and limit.")
    offset: int
    truncated: bool
    provenance: Provenance
