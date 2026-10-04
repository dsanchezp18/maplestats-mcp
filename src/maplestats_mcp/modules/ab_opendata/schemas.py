"""Typed responses for the Open Alberta file reader."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class ResourceEntry(BaseModel):
    id: str
    name: str = Field(description="The publisher's title for the file.")
    format: str | None = Field(default=None, description="Format as the portal states it.")
    size_bytes: int | None = None
    modified: str | None = Field(default=None, description="Resource last-modified timestamp.")
    url: str = Field(description="Pass this to ab_opendata_describe_resource or _read_resource.")
    readable: bool = Field(
        description="True for an .xlsx, .xls or .csv file hosted on open.alberta.ca. Links to "
        "other sites, maps, PDFs and services are listed but not read by this module."
    )
    description: str | None = None


class OrganizationCount(BaseModel):
    name: str = Field(description="Organization slug; pass it as `organization`.")
    title: str
    datasets: int = Field(description="Datasets matching the current search.")


class DatasetEntry(BaseModel):
    name: str = Field(description="Dataset slug; usable with ab_opendata_get_dataset.")
    title: str
    dataset_url: str
    organization: str | None = Field(default=None, description="Organization slug.")
    organization_title: str | None = None
    licence_id: str | None = None
    licence: str | None = None
    licence_url: str | None = None
    ogl_alberta: bool = Field(
        description="True when the dataset is under the Open Government Licence - Alberta."
    )
    licence_note: str | None = Field(
        default=None,
        description="Set only when the dataset is NOT under the Open Government Licence - "
        "Alberta: other terms apply.",
    )
    date_modified: str | None = Field(
        default=None, description="Date the publisher last modified the dataset."
    )
    update_frequency: str | None = None
    time_coverage_from: str | None = None
    time_coverage_to: str | None = None
    topics: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None, description="Start of the dataset description.")
    resources: list[ResourceEntry] = Field(
        description="Readable files first (Excel and CSV); `other_formats` names the rest."
    )
    other_formats: list[str] = Field(
        default_factory=list, description="Formats of resources this module does not read."
    )


class DatasetList(BaseModel):
    datasets: list[DatasetEntry]
    total_datasets: int
    offset: int
    truncated: bool
    organizations: list[OrganizationCount] = Field(
        description="Organizations among all matches, to narrow with `organization`; empty "
        "when `sort` is modified or title or `offset` is above 0 (the portal fails on counts plus sort or start)."
    )
    licence_note: str
    provenance: Provenance


class OrganizationList(BaseModel):
    organizations: list[OrganizationCount]
    total_datasets: int
    licence_note: str
    provenance: Provenance


class DatasetDetail(BaseModel):
    dataset: DatasetEntry
    licence_note: str
    provenance: Provenance


class SheetInfo(BaseModel):
    name: str
    rows: int | None = Field(default=None, description="Row count the file declares.")
    columns: int | None = Field(
        default=None,
        description="Columns holding data at the top of the sheet (one per column_names "
        "entry); trailing empty columns the file declares are not counted.",
    )
    header_row: int | None = Field(
        default=None, description="Guessed 1-based header row; null when none looks like one."
    )
    column_names: list[str] = Field(default_factory=list)
    preview: list[list[str]] = Field(
        default_factory=list, description="The first rows after the header, as published."
    )


class ResourceStructure(BaseModel):
    url: str
    format: str
    resource_name: str | None = None
    dataset: str
    dataset_title: str
    sheets: list[SheetInfo]
    total_sheets: int
    truncated: bool
    licence: str | None = None
    ogl_alberta: bool
    attribution: str | None = None
    licence_note: str | None = None
    provenance: Provenance


class ResourceRows(BaseModel):
    url: str
    format: str
    resource_name: str | None = None
    dataset: str
    dataset_title: str
    sheets: list[str] = Field(description="Every sheet name (one entry, 'csv', for a CSV).")
    sheet: str | None = Field(
        description="The sheet read; null when the workbook has several comparable sheets "
        "and none was requested (no rows are read: pass one of `sheets` as `sheet`)."
    )
    sheet_chosen_by: Literal["request", "largest", "only", "none"] = Field(
        default="only",
        description="How the sheet was picked: requested, the dominant largest sheet, the "
        "only sheet, or none (choose one).",
    )
    header_row: int | None = Field(
        description="1-based row holding the column names: the one requested, else guessed; "
        "null when none looks like a header (columns are then column_1, column_2...)."
    )
    all_columns: list[str]
    columns: list[str] = Field(description="The columns returned.")
    rows: list[dict[str, str]] = Field(
        description="Rows as published (text), keyed by column name."
    )
    total_rows: int = Field(description="Rows that matched, before offset and limit.")
    offset: int
    truncated: bool
    licence: str | None = None
    ogl_alberta: bool
    attribution: str | None = Field(
        default=None,
        description="Statement to carry with any reuse; null when the dataset is not under "
        "the Open Government Licence - Alberta.",
    )
    licence_note: str | None = None
    provenance: Provenance
