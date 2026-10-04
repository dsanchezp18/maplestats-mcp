"""Typed responses for the NWT Bureau of Statistics module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TopicInfo(BaseModel):
    topic: str = Field(description="Topic slug, as used by nwt_stats_list_files.")
    title: str
    page_url: str


class FileEntry(BaseModel):
    topic: str
    section: str | None = Field(
        description="Heading above the link on the agency's page (survey, release date, "
        "quarter or community), when there is one."
    )
    title: str = Field(description="The agency's own name for the table.")
    context: str | None = Field(
        default=None,
        description="The agency's text around the link when it adds to the title, e.g. "
        "'NWT Income (4 Excel Tables)'.",
    )
    url: str = Field(description="Pass this to nwt_stats_read_file.")
    format: str = Field(description="'xlsx' or 'xls'.")
    page_url: str = Field(description="The agency page that links the file.")


class FileList(BaseModel):
    topics: list[TopicInfo] = Field(
        description="Every topic, so a later call can name one; empty files with no topic."
    )
    files: list[FileEntry]
    total_files: int
    truncated: bool
    licence: str
    provenance: Provenance


class SheetSize(BaseModel):
    name: str
    rows: int | None = None
    columns: int | None = None


class FileRows(BaseModel):
    url: str
    format: str = Field(description="Real format read from the file's bytes.")
    sheets: list[SheetSize] = Field(description="Every sheet with its declared size.")
    sheet: str | None = Field(
        description="The sheet read; null when the workbook has several sheets of similar "
        "size and none was named (no rows are read then: pick one from `sheets`)."
    )
    sheet_chosen_by: Literal["request", "largest", "only", "none"]
    header_row: int | None = Field(
        description="1-based row used as column names (guessed unless header_row was given)."
    )
    header_row_candidates: list[int] = Field(
        description="Other rows near the top that look like column names, to pass as header_row."
    )
    all_columns: list[str]
    columns: list[str] = Field(description="Selected columns, in order.")
    rows: list[dict[str, str]] = Field(description="Rows as published, every value as text.")
    total_rows: int = Field(description="Rows that matched the filters, before offset and limit.")
    offset: int
    truncated: bool
    licence: str
    provenance: Provenance
