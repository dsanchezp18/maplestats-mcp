"""Typed responses for the BC Stats Excel module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class FileEntry(BaseModel):
    dataset: str = Field(description="Catalogue dataset name (slug); usable with ckan_get_dataset.")
    dataset_title: str
    dataset_url: str
    title: str = Field(description="The agency's own title for the file (the resource name).")
    url: str = Field(description="Pass this to bc_stats_read_file.")
    size_bytes: int | None = None
    update_cycle: str | None = Field(
        default=None, description="Catalogue update cycle, e.g. monthly, quarterly, annually."
    )
    modified: str | None = Field(default=None, description="Resource last-modified timestamp.")
    licence: str | None = Field(default=None, description="Licence of the dataset.")
    licence_url: str | None = None
    datastore_flag: bool | None = Field(
        default=None,
        description="The catalogue's datastore_active flag for this file. It is not "
        "reliable for .xlsx files (some flagged true have no DataStore rows); try "
        "ckan_datastore_search with portal=bc if rows matter, and fall back to this reader.",
    )
    dataset_formats: list[str] = Field(
        default_factory=list,
        description="Formats of the dataset's resources, e.g. ['xlsx', 'csv', 'pdf']; "
        "a dataset with a CSV may be easier to read with ckan_datastore_search.",
    )


class FileList(BaseModel):
    files: list[FileEntry]
    total_files: int
    truncated: bool
    licence_note: str
    provenance: Provenance


class SheetInfo(BaseModel):
    name: str
    rows: int | None = Field(description="Row count the file declares for the sheet.")
    columns: int | None = None


class FileData(BaseModel):
    url: str
    sheets: list[SheetInfo]
    sheet: str
    header_row: int | None = Field(
        description="1-based row number holding the column names: the one requested, else "
        "guessed as the first row with at least three filled cells; null when none looks "
        "like a header."
    )
    header: list[str]
    rows: list[list[str]] = Field(
        description="Rows as published (text), after the header row when one was found."
    )
    total_rows: int = Field(description="Rows that matched `contains`, before offset and limit.")
    offset: int
    truncated: bool
    licence: str | None = None
    provenance: Provenance
