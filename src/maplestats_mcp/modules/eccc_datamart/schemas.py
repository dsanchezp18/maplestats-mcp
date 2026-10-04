"""Typed responses for the ECCC Data Catalogue file tree."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

EntryKind = Literal["folder", "table", "documentation", "archive", "other"]


class CatalogueEntry(BaseModel):
    name: str
    path: str = Field(description="Full path; pass it to eccc_datamart_browse or _read_file.")
    kind: EntryKind = Field(
        description="folder; table (CSV, TSV, TXT, XLSX, XLS this module reads); "
        "documentation (read-me, data dictionary, metadata XML); archive (ZIP and similar, "
        "not opened); other (PDF, Word, images, NetCDF and the rest, not opened)."
    )
    title: str | None = Field(
        default=None, description="The catalogue's display name, when it gives one."
    )
    size: str | None = Field(
        default=None, description="Size as the catalogue lists it, rounded (e.g. '36 MiB')."
    )
    size_bytes: int | None = Field(
        default=None, description="Approximate size in bytes from the rounded listing."
    )
    modified: str | None = None
    readable: bool = Field(description="True for a table file at or under the 40 MB reading cap.")
    file_url: str | None = Field(default=None, description="Direct download link (files).")


class FolderListing(BaseModel):
    path: str
    parent: str | None = None
    title: str | None = None
    catalogue_id: str | None = Field(
        default=None, description="open.canada.ca dataset id, when the folder is a dataset."
    )
    catalogue_url: str | None = None
    browse_url: str = Field(description="The folder in the catalogue's web page.")
    folders: int
    files: int
    entries: list[CatalogueEntry]
    total_entries: int
    offset: int
    truncated: bool
    attribution: str
    provenance: Provenance


class SearchHit(BaseModel):
    path: str
    title: str = Field(description="Display name in the requested language, else the name.")
    other_title: str | None = Field(default=None, description="The other language's title.")
    topic: str = Field(description="Top folder, e.g. substances, air, water.")
    depth: int
    score: float
    browse_url: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]
    total_hits: int
    indexed_folders: int
    index_depth: int = Field(description="Folder levels indexed under the root.")
    skipped_folders: list[str] = Field(
        default_factory=list, description="Folders whose listing failed while indexing."
    )
    provenance: Provenance


class SheetInfo(BaseModel):
    name: str
    rows: int | None = Field(default=None, description="Row count the file declares.")
    columns: int | None = None
    header_row: int | None = Field(default=None, description="Guessed 1-based header row.")
    column_names: list[str] = Field(default_factory=list)
    preview: list[list[str]] = Field(default_factory=list)


class DocumentationFile(BaseModel):
    name: str
    path: str
    size: str | None = None
    file_url: str
    excerpt: str | None = Field(
        default=None, description="Start of the text, for small CSV or TXT read-me files."
    )


class FileStructure(BaseModel):
    path: str
    file_url: str
    format: str
    size: str | None = None
    modified: str | None = None
    folder_title: str | None = None
    catalogue_url: str | None = None
    sheets: list[SheetInfo]
    total_sheets: int
    truncated: bool
    documentation: list[DocumentationFile] = Field(
        description="Read-me, data dictionary and metadata files in the same folder."
    )
    attribution: str
    provenance: Provenance


class FileRows(BaseModel):
    path: str
    file_url: str
    format: str
    sheets: list[str] = Field(description="Every sheet name (one entry, 'csv', for a CSV).")
    sheet: str | None = Field(
        description="The sheet read; null when a workbook has several sheets of similar "
        "size and none was requested (no rows are read then: pass `sheet`)."
    )
    sheet_chosen_by: Literal["request", "largest", "only", "none"]
    header_row: int | None
    all_columns: list[str]
    columns: list[str] = Field(description="The columns returned.")
    rows: list[dict[str, str]] = Field(description="Rows as published (text).")
    total_rows: int = Field(description="Rows that matched, before offset and limit.")
    offset: int
    truncated: bool
    attribution: str
    provenance: Provenance


class NpriRecord(BaseModel):
    year: int
    npri_id: str
    company: str
    facility: str
    city: str | None = None
    province: str | None = Field(default=None, description="Two-letter code.")
    latitude: float | None = None
    longitude: float | None = None
    naics: str | None = Field(default=None, description="NAICS 6-digit code.")
    naics_name: str | None = None
    cas_number: str | None = Field(
        default=None, description="CAS number, or an NPRI code such as 'NA - M09'."
    )
    substance: str
    units: str = Field(description="tonnes, kg, grams or g TEQ (dioxins and furans).")
    air: float | None = Field(default=None, description="Air emissions, total.")
    water: float | None = Field(default=None, description="Water releases, total.")
    land: float | None = Field(default=None, description="Land releases, total.")
    road_dust: float | None = Field(default=None, description="Road dust emissions.")
    total_releases: float | None = Field(
        default=None, description="Total releases including road dust."
    )
    on_site_disposal: float | None = None
    off_site_disposal: float | None = None
    treatment_transfers: float | None = None
    recycling_transfers: float | None = None
    grand_total: float | None = Field(
        default=None, description="Releases, disposals and transfers for recycling, total."
    )


class NpriResult(BaseModel):
    year: int
    available_years: list[int]
    file_path: str
    file_url: str
    records: list[NpriRecord]
    total_records: int
    facilities: int = Field(description="Distinct facilities among all matching records.")
    offset: int
    truncated: bool
    notes: list[str]
    attribution: str
    provenance: Provenance


class GhgrpRecord(BaseModel):
    ghgrp_id: str
    year: int
    facility: str
    city: str | None = None
    province: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    npri_id: str | None = Field(default=None, description="Null when the file has 0 (none).")
    naics: str | None = None
    naics_name: str | None = None
    company: str | None = Field(default=None, description="Reporting company legal name.")
    company_trade_name: str | None = None
    co2_tonnes: float | None = None
    ch4_co2e: float | None = Field(default=None, description="Methane, tonnes CO2e.")
    n2o_co2e: float | None = Field(default=None, description="Nitrous oxide, tonnes CO2e.")
    hfc_co2e: float | None = None
    pfc_co2e: float | None = None
    sf6_co2e: float | None = None
    total_co2e: float | None = Field(
        default=None, description="Total emissions, tonnes CO2e, excluding biomass CO2."
    )
    co2_biomass_tonnes: float | None = Field(
        default=None, description="CO2 from biomass combustion (reported from 2022)."
    )


class GhgrpResult(BaseModel):
    years: list[int] = Field(description="Reference years present in the file.")
    file_path: str
    file_url: str
    file_modified: str | None = None
    records: list[GhgrpRecord]
    total_records: int
    facilities: int
    total_co2e_sum: float = Field(description="Sum of total_co2e over all matching records.")
    offset: int
    truncated: bool
    notes: list[str]
    attribution: str
    provenance: Provenance
