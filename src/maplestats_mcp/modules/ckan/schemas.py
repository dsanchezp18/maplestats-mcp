"""Typed responses for the shared CKAN portal family.

One superset shape serves every portal. Fields a portal does not
publish stay `None`/empty; portal-specific metadata (Ontario's access
level, Toronto's refresh rate, Alberta's subject fields, and so on)
goes in `extras`, keyed by the upstream field name, so no portal's
quirks leak into another's typed fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

# Kept in sync with constants.PORTALS by a unit test -- a Literal is what
# puts the valid portal keys into each tool's JSON schema.
PortalKey = Literal[
    "federal",
    "on",
    "bc",
    "ab",
    "qc",
    "nt",
    "yt",
    "montreal",
    "toronto",
    "regina",
]


class PortalInfo(BaseModel):
    portal: str
    name: str
    api_url: str
    content_language: str = Field(description="'bilingual', 'en', or 'fr'.")
    has_tags: bool
    has_groups: bool
    has_datastore: bool
    note: str | None = None


class PortalList(BaseModel):
    portals: list[PortalInfo]
    provenance: Provenance


class ResourceInfo(BaseModel):
    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str | None = None
    size: int | None = None
    resource_type: str | None = None
    language: list[str] = Field(default_factory=list)
    datastore_active: bool | None = Field(
        default=None,
        description="True when rows can be queried with ckan_datastore_search.",
    )
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class OrganizationRef(BaseModel):
    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    id: str
    name: str | None = None
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str = ""
    license_id: str | None = None
    license_title: str | None = None
    is_open: bool | None = None
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    num_resources: int = 0
    resource_formats: list[str] = Field(default_factory=list)
    metadata_modified: datetime | None = None
    landing_page_url: str


class PackageSearchResult(BaseModel):
    portal: str
    packages: list[PackageSummary]
    total_count: int
    returned_count: int
    start: int
    rows: int
    query: str
    provenance: Provenance


class PackageDetail(BaseModel):
    portal: str
    id: str
    name: str | None = None
    title: str
    notes: str = ""
    organization: OrganizationRef | None = None
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    is_open: bool | None = None
    keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    num_resources: int = 0
    resources: list[ResourceInfo]
    extras: dict[str, Any] = Field(
        default_factory=dict,
        description="Portal-specific metadata keyed by upstream field name.",
    )
    landing_page_url: str
    provenance: Provenance


class OrganizationSummary(BaseModel):
    id: str | None = None
    name: str
    title: str
    package_count: int = 0


class OrganizationList(BaseModel):
    portal: str
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    portal: str
    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int = 0
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class ResourceDetail(BaseModel):
    portal: str
    resource: ResourceInfo
    provenance: Provenance


class LicenseInfo(BaseModel):
    id: str
    title: str
    url: str | None = None
    status: str | None = None
    family: str | None = None
    is_okd_compliant: bool | None = None
    is_osi_compliant: bool | None = None
    od_conformance: str | None = None
    osd_conformance: str | None = None
    domain_content: bool | None = None
    domain_data: bool | None = None
    domain_software: bool | None = None


class LicenseList(BaseModel):
    portal: str
    licenses: list[LicenseInfo]
    provenance: Provenance


class TagList(BaseModel):
    portal: str
    tags: list[str]
    total_count: int
    query: str | None = None
    truncated: bool = False
    provenance: Provenance


class GroupSummary(BaseModel):
    id: str | None = None
    name: str
    title: str
    description: str | None = None
    package_count: int = 0
    landing_page_url: str | None = None


class GroupList(BaseModel):
    portal: str
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class GroupDetail(BaseModel):
    portal: str
    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int = 0
    image_url: str | None = None
    landing_page_url: str | None = None
    provenance: Provenance


class CollectionDetail(BaseModel):
    """One CKAN organization or group: CKAN gives both the same shape."""

    portal: str
    kind: Literal["organization", "group"]
    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int = 0
    image_url: str | None = None
    landing_page_url: str | None = None
    provenance: Provenance


class DatastoreField(BaseModel):
    id: str
    type: str


class DatastoreSearchResult(BaseModel):
    portal: str
    resource_id: str
    records: list[dict[str, Any]]
    fields: list[DatastoreField]
    total_count: int
    returned_count: int
    limit: int
    offset: int
    filters: dict[str, str] | None = None
    query: str | None = None
    provenance: Provenance


class FileSource(BaseModel):
    """Where a file's numbers come from and under what terms they may be reused."""

    portal: str
    resource_id: str
    resource_name: str | None = None
    source_url: str = Field(
        description="The file URL the portal lists for this resource (resolved against the "
        "portal host when it is relative); this is what was downloaded."
    )
    declared_format: str | None = Field(default=None, description="Format as the portal states it.")
    size_bytes: int | None = Field(default=None, description="Size the portal states, if any.")
    last_modified: str | None = Field(
        default=None, description="The resource's last-modified timestamp on the portal."
    )
    dataset_id: str | None = None
    dataset_title: str | None = None
    landing_page: str | None = None
    organization: str | None = None
    licence_id: str | None = None
    licence_title: str | None = None
    licence_url: str | None = None
    licence_status: Literal[
        "open", "non_commercial", "restricted", "not_stated", "unrecognised"
    ] = Field(
        description="'open' only for licences recognised as open (Open Government Licences, "
        "Creative Commons attribution, public domain); anything else carries a warning."
    )
    licence_warning: str | None = Field(
        default=None,
        description="Set whenever the licence is not clearly open: reuse conditions apply.",
    )
    citation: str = Field(description="A source line to carry with any reuse of the numbers.")


class FileSheet(BaseModel):
    name: str
    rows: int | None = Field(default=None, description="Row count the file declares.")
    columns: int | None = None
    header_row: int | None = Field(
        default=None, description="Guessed 1-based header row; null when none looks like one."
    )
    header_row_candidates: list[int] = Field(
        default_factory=list,
        description="1-based rows near the top that look like column names (three or more "
        "filled cells, mostly text); pass one as `header_row` if the guess is wrong.",
    )
    column_names: list[str] = Field(default_factory=list)
    preview: list[list[str]] = Field(
        default_factory=list, description="The first rows after the header, as published."
    )


class FileStructure(BaseModel):
    source: FileSource
    format: str = Field(description="Real format sniffed from the file's bytes.")
    file_bytes: int = Field(description="Bytes downloaded.")
    datastore_active: bool | None = Field(
        default=None,
        description="True when the portal also serves this resource as DataStore rows; "
        "ckan_datastore_search then reads it without the file.",
    )
    sheets: list[FileSheet]
    total_sheets: int
    truncated: bool
    provenance: Provenance


class SheetSize(BaseModel):
    name: str
    rows: int | None = None
    columns: int | None = None


class FileRows(BaseModel):
    source: FileSource
    read_via: Literal["file", "datastore"] = Field(
        description="'datastore' when the portal's DataStore answered, else the downloaded file."
    )
    format: str = Field(description="Real format sniffed from the file ('datastore' for rows).")
    sheets: list[SheetSize] = Field(
        description="Every sheet with its declared size (one 'csv' entry for a CSV)."
    )
    sheet: str | None = Field(description="The sheet read (null for DataStore rows).")
    sheet_chosen_by: Literal["request", "largest", "only", "datastore", "none"] = Field(
        description="'request': the sheet asked for. 'largest': no sheet was given and one "
        "holds at least 80% of the workbook's cells, so it was read. 'none': a workbook "
        "with several comparable sheets and no `sheet` given returns the sheet list and "
        "dimensions with no rows; pass `sheet`. 'only': a CSV or one-sheet workbook."
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
    provenance: Provenance
