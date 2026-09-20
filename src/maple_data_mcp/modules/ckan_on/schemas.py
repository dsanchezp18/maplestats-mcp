"""Typed responses for the Ontario Data Catalogue CKAN API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str
    size: int | None = None
    datastore_active: bool | None = None
    resource_type: str | None = None
    data_last_updated: datetime | None = None
    data_range_start: datetime | None = None
    data_range_end: datetime | None = None
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    is_open: bool
    tags: list[str] = Field(default_factory=list)
    num_resources: int
    resource_formats: list[str] = Field(default_factory=list)
    metadata_modified: datetime | None = None
    landing_page_url: str


class PackageSearchResult(BaseModel):
    packages: list[PackageSummary]
    total_count: int
    returned_count: int
    start: int
    rows: int
    query: str
    provenance: Provenance


class PackageDetail(BaseModel):
    id: str
    title: str
    notes: str
    organization: OrganizationRef | None = None
    author: str | None = None
    maintainer: str | None = None
    maintainer_email: str | None = None
    access_level: str | None = None
    current_as_of: datetime | None = None
    geographic_coverage: str | None = None
    geographic_granularity: str | None = None
    update_frequency: str | None = None
    is_open: bool
    keywords: list[str] = Field(default_factory=list)
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    num_resources: int
    resources: list[ResourceInfo]
    landing_page_url: str
    provenance: Provenance


class OrganizationSummary(BaseModel):
    id: str
    name: str
    title: str
    package_count: int


class OrganizationList(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class LicenseInfo(BaseModel):
    id: str
    title: str
    url: str | None = None
    status: str
    family: str | None = None
    maintainer: str | None = None
    domain_content: bool = False
    domain_data: bool = False
    domain_software: bool = False
    od_conformance: str | bool | None = None
    osd_conformance: str | bool | None = None
    is_generic: bool | None = None
    is_okd_compliant: bool | None = None
    is_osi_compliant: bool | None = None


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance


class TagList(BaseModel):
    tags: list[str]
    total_count: int
    truncated: bool = False
    provenance: Provenance


class GroupSummary(BaseModel):
    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    landing_page_url: str


class GroupList(BaseModel):
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class DatastoreField(BaseModel):
    id: str
    type: str


class DatastoreSearchResult(BaseModel):
    """Row-level query against one DataStore-active resource (see
    ResourceInfo.datastore_active), as opposed to ckan_on_get_resource's
    metadata-only view. Not every resource on this portal supports this
    -- most are plain files, not DataStore tables."""

    resource_id: str
    records: list[dict[str, object]]
    fields: list[DatastoreField] = Field(default_factory=list)
    total_count: int
    returned_count: int
    limit: int
    offset: int
    filters: dict[str, str] | None = None
    query: str | None = None
    provenance: Provenance
