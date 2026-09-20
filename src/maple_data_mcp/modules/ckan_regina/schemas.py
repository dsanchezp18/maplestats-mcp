"""Typed response models for the City of Regina Open Data (CKAN Regina) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list, tag_list, group_list,
group_show against real openregina.ca records). Deployment-specific
quirks, differing from both ckan_toronto and ckan_bc in ways confirmed
live rather than assumed:

1. This portal DOES use CKAN tags and groups (confirmed live: tag_list
   returns a populated vocabulary and group_list returns curated
   topics such as "City Administration" and "Maps", each with a real
   `package_count`), like ckan_bc but unlike ckan_toronto.
2. Unlike ckan_bc, `group_list(all_fields=true)` is public on this
   deployment -- confirmed live, HTTP 200 with no authentication --
   so GroupSummary/GroupDetail below are built directly from
   group_list/group_show, not from a package_search facet workaround.
3. Exactly one organization exists (city-of-regina, 1,379 packages,
   confirmed live) -- the same single-organization shape as
   ckan_toronto, not ckan_bc's ~164-organization roster -- so
   OrganizationSummary/OrganizationList mirror ckan_toronto's simple
   shape rather than ckan_bc's facet-based one.
4. This portal has no curated `excerpt` field (unlike ckan_toronto) --
   confirmed live across sampled packages -- so PackageSummary
   truncates the raw `notes` field client-side instead, the same
   pattern ckan_federal/ckan_bc use.
5. This portal is English-only -- confirmed live that no sampled
   package, resource, organization, or license record carries a
   `_translated` dict or a `_fra`-suffixed field. `lang` is still
   accepted by every tool for interface consistency, but has no
   effect here (see client.py).
6. `license_list` returns real JSON booleans for
   `domain_content`/`domain_data`/`domain_software`/`is_generic`
   (confirmed live, unlike ckan_toronto's string-typed "True"/"False")
   -- `to_bool()` is still used for uniformity with every other CKAN
   module, and is a no-op on an already-real boolean.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset."""

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str | None = None
    size: int | None = None
    datastore_active: bool = False
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_regina_get_resource)."""

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result."""

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row."""

    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    num_resources: int
    metadata_modified: datetime | None = None
    landing_page_url: str


class PackageSearchResult(BaseModel):
    packages: list[PackageSummary]
    total_count: int = Field(
        description="Total matches across the whole catalogue, not just this page."
    )
    returned_count: int
    start: int
    rows: int
    query: str
    provenance: Provenance


class PackageDetail(BaseModel):
    """Full dataset (package) record, including its resources, tags, and groups."""

    id: str
    title: str
    notes: str
    organization: OrganizationRef
    license_id: str | None = None
    license_title: str | None = None
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
    """Result of ckan_regina_list_organizations.

    Confirmed live: this portal publishes through exactly one
    organization (city-of-regina) -- so this list will always have
    `total_count == 1`, the same shape as ckan_toronto.
    """

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
    """One entry from license_list."""

    id: str
    title: str
    url: str | None = None
    status: str
    family: str | None = None
    domain_content: bool
    domain_data: bool
    domain_software: bool
    is_generic: bool
    od_conformance: str | None = None
    osd_conformance: str | None = None


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance


class TagList(BaseModel):
    """Result of ckan_regina_list_tags.

    Plain tag-name strings, matching ckan_toronto's choice: every
    sampled tag's `vocabulary_id` is null, so the `all_fields` form's
    extra `id`/`vocabulary_id` carry no useful information here.
    """

    tags: list[str]
    total_count: int
    provenance: Provenance


class GroupSummary(BaseModel):
    """One curated thematic group, with its live dataset count.

    Built directly from `group_list(all_fields=true)` -- unlike
    ckan_bc, this call is public on this deployment (see module
    docstring point 2), so no package_search facet workaround is
    needed.
    """

    name: str
    title: str
    package_count: int
    landing_page_url: str


class GroupList(BaseModel):
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class GroupDetail(BaseModel):
    """Full detail for one curated thematic group (group_show)."""

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class DatastoreField(BaseModel):
    id: str
    type: str


class DatastoreSearchResult(BaseModel):
    """Row-level query against one DataStore-active resource (see
    ResourceInfo.datastore_active), as opposed to ckan_regina_get_resource's
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
