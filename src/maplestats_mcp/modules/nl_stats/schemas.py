"""Typed responses for the Newfoundland and Labrador Statistics Agency module."""

from __future__ import annotations

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
    total_files: int = Field(description="Files matching topic and query, before paging.")
    truncated: bool = Field(description="True when more files follow this page.")
    offset: int = Field(default=0, description="Position of the first file shown.")
    provenance: Provenance


class SheetInfo(BaseModel):
    name: str
    rows: int
    columns: int


class FileData(BaseModel):
    url: str
    format: str
    sheets: list[SheetInfo]
    sheet: str
    header_row: int | None = Field(
        description="1-based row number guessed to hold the column names (the first row "
        "with at least three filled cells); null when none looks like a header."
    )
    header: list[str]
    rows: list[list[str]] = Field(
        description="Rows as published (text), after the header row when one was guessed."
    )
    total_rows: int = Field(description="Rows that matched `contains`, before offset and limit.")
    offset: int
    truncated: bool
    provenance: Provenance
