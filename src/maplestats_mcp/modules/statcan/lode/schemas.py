"""Typed responses for StatCan LODE tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Scalar = str | int | float | bool | None


class LodeRelease(BaseModel):
    date: str | None = Field(default=None, description="Release date, ISO 8601.")
    version: str | None = Field(default=None, description="E.g. 'Version 2.0'.")
    label: str = Field(description="The line as StatCan prints it.")


class LodeDatabase(BaseModel):
    key: str = Field(description="Pass as `database` to the other statcan_lode_ tools.")
    catalogue_number: str
    title: str
    group: str = Field(description="open_database, accessibility or address_register.")
    description: str
    releases: list[LodeRelease] = Field(description="Newest first, as listed on StatCan's page.")
    latest_release: str | None = Field(
        default=None, description="Newest release date (ISO 8601) found for this database."
    )
    formats: list[str] = Field(
        description="Download formats as last verified; statcan_lode_list_files is live."
    )
    licence: str
    licence_url: str
    page_url: str
    queryable: bool = Field(
        description="True when statcan_lode_query can read it from a downloaded ZIP."
    )


class LodeDatabaseList(BaseModel):
    databases: list[LodeDatabase]
    landing_url: str
    provenance: Provenance


class LodeFile(BaseModel):
    label: str = Field(description="Link text on StatCan's page.")
    url: str = Field(description="Direct ZIP download.")
    filename: str
    format: str = Field(description="geojson, gpkg, parquet or zip (contents decide).")
    size_bytes: int | None = Field(default=None, description="Archive size from a HEAD request.")
    last_modified: str | None = None
    provinces: list[str] = Field(
        description="Province or territory codes this file covers (per-province files)."
    )
    queryable: bool = Field(description="Whether statcan_lode_query can read this file.")
    note: str | None = None


class LodeFileList(BaseModel):
    database: str
    title: str
    page_url: str
    release_date: str | None = None
    date_modified: str | None = None
    licence: str
    licence_url: str
    files: list[LodeFile]
    max_download_bytes: int = Field(
        description="Largest archive statcan_lode_query will download in one call."
    )
    provenance: Provenance


class ZipEntry(BaseModel):
    name: str
    size_bytes: int


class LodeZipListing(BaseModel):
    url: str
    archive_bytes: int
    entries: list[ZipEntry]
    provenance: Provenance


class LodeField(BaseModel):
    name: str
    type: str | None = None
    description: str | None = None
    example: Scalar = None


class LodeLayer(BaseModel):
    name: str
    geometry_type: str | None = None
    crs: str | None = None
    feature_count: int | None = None


class LodeDescription(BaseModel):
    database: str
    title: str
    file_url: str
    data_member: str | None = Field(description="The file inside the ZIP that holds the records.")
    format: str | None = None
    members: list[ZipEntry]
    layers: list[LodeLayer]
    fields: list[LodeField]
    field_sources: list[str] = Field(
        description="Where the field list came from: dictionary file, data sample, "
        "GeoPackage schema or the product page."
    )
    notes: list[str]
    provenance: Provenance


class LodeQueryResult(BaseModel):
    database: str
    file_url: str
    data_member: str
    format: str
    layer: str | None = None
    crs: str | None = None
    filters: dict[str, str]
    total_matched: int
    total_is_lower_bound: bool = Field(
        description="True when the scan stopped at its row cap before reading every row."
    )
    returned: int
    truncated: bool
    columns: list[str]
    records: list[dict[str, Scalar]] = Field(
        description="Attributes as published plus longitude/latitude (WGS 84; the centre of "
        "the bounding box for lines and polygons) and geometry_type where known."
    )
    downloaded: bool = Field(description="True when this call downloaded the archive.")
    archive_bytes: int
    notes: list[str]
    provenance: Provenance


class LodeMemberPreview(BaseModel):
    url: str
    member: str
    member_bytes: int
    columns: list[str]
    rows: list[dict[str, str | None]]
    rows_returned: int
    match: dict[str, str]
    compressed_bytes_read: int
    scan_complete: bool = Field(
        description="True when the whole member was read; False when the scan cap stopped it."
    )
    notes: list[str]
    provenance: Provenance
