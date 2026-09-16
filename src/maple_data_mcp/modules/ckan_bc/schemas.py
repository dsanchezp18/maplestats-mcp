"""Typed response models for the BC Data Catalogue (CKAN BC) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list, tag_list, group_list,
group_show against real catalogue.data.gov.bc.ca records), not guessed
from generic CKAN documentation or from ckan_federal's own findings.
Several deployment-specific quirks shape these models, differing from
ckan_federal in ways confirmed live rather than assumed:

1. This portal DOES use CKAN tags and groups, unlike the federal portal
   (which uses neither) -- confirmed live: tag_list returns ~7,087
   entries and group_list returns 26 curated thematic collections, and
   real packages carry populated `tags`/`groups` arrays. See
   TagInfo/GroupSummary/GroupDetail below and client.py's tag/group
   functions.
2. This portal is English-only -- confirmed live that no sampled
   package, resource, organization, or license record carries a
   `_translated` dict or a `_fra`-suffixed field anywhere. `lang` is
   still accepted by every tool for interface consistency with
   ckan_federal, but pick_translated/pick_fra are never actually
   exercised here (see client.py).
3. An organization's `image_url` field is a bare uploaded filename
   fragment (e.g. "2018-10-26-000525.036919bc-stats-gov-wordmark.png"),
   not a usable URL -- confirmed live. `image_display_url` is the
   actual absolute URL. OrganizationDetail.image_url and
   GroupDetail.image_url below are populated from `image_display_url`,
   not the raw `image_url` field, despite the name.
4. Several resource fields (`mimetype`, `mimetype_inner`, `cache_url`,
   `url_type`) are sometimes the literal JSON string "null" rather than
   a real null -- confirmed live via resource_show. client.py's
   `_clean_str` normalizes both a real null and the literal string
   "null" to None.
5. `datastore_active` is inconsistently typed across resources on this
   portal -- confirmed live: a real JSON boolean on some resources, the
   JSON string "false" on others, for the same field on sibling
   resources of the same package. Pydantic's lax bool validation
   coerces both without extra handling, so ResourceInfo declares it as
   a plain `bool`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    `size` is frequently null even for resources that clearly have a
    file behind them (the same pattern confirmed on ckan_federal) --
    this portal does not backfill size for every resource either.
    `object_name` is this portal's BC Geographic Warehouse (BCGW) table
    identifier (e.g. "WHSE_HUMAN_CULTURAL_ECONOMIC.CEN_PROF_..."), kept
    because it is the real key needed to query the BCGW directly for
    many spatial datasets on this portal -- ckan_federal has no
    equivalent field since it isn't a spatial-data-warehouse-backed
    catalogue the same way.
    """

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str | None = None
    size: int | None = None
    resource_type: str | None = None
    resource_storage_location: str | None = None
    object_name: str | None = None
    datastore_active: bool = False
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_bc_get_resource).

    Wraps ResourceInfo with provenance rather than adding provenance to
    ResourceInfo directly, since ResourceInfo is also used nested inside
    PackageDetail.resources -- matching ckan_federal's own convention.
    """

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result."""

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row.

    Deliberately excludes the full resource list and tag/group detail
    that PackageDetail (ckan_bc_get_dataset) carries -- a package_search
    query can match any of this catalogue's ~3,357 datasets, so results
    stay compact per AGENTS.md's agent-friendly-output principle; open
    the full record with ckan_bc_get_dataset once a candidate is chosen.
    """

    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    num_resources: int
    resource_formats: list[str] = Field(default_factory=list)
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
    """One row from organization_list(all_fields=True)."""

    id: str
    name: str
    title: str
    package_count: int


class OrganizationList(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    """Full organization record.

    `website_url` (from organization_show's `url` field) is the
    organization's own external homepage -- a field ckan_federal's
    organizations do not carry, confirmed live only present here.
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    website_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class LicenseInfo(BaseModel):
    """One entry from license_list.

    No `title_fra`/`_translated` counterpart exists here -- confirmed
    live, unlike ckan_federal's license_list -- so `title`/`url` are
    used as-is with no language picking. `is_open` is this portal's own
    top-level openness flag (distinct from `is_okd_compliant`/
    `is_osi_compliant`, which come from the Open/Open Source
    Definitions specifically); ckan_federal's license_list does not
    expose an equivalent field.
    """

    id: str
    title: str
    url: str | None = None
    status: str
    is_open: bool
    is_okd_compliant: bool
    is_osi_compliant: bool


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance


class TagInfo(BaseModel):
    """One entry from tag_list(all_fields=True) or a package's `tags` array."""

    id: str
    name: str
    display_name: str


class TagList(BaseModel):
    tags: list[TagInfo]
    total_count: int
    query: str | None = None
    truncated: bool = Field(
        description="True when the full unfiltered tag vocabulary was capped at TAG_LIST_MAX."
    )
    provenance: Provenance


class GroupSummary(BaseModel):
    """One curated thematic group, with its live dataset count.

    Built from package_search's `groups` facet (see client.py), not
    group_list -- group_list(all_fields=True) requires authentication on
    this deployment (confirmed live, HTTP 403 for an anonymous request),
    while the facet path is public. Only groups with at least one
    dataset attached appear, since a facet count is computed from search
    matches.
    """

    name: str
    title: str
    dataset_count: int
    landing_page_url: str


class GroupList(BaseModel):
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class GroupDetail(BaseModel):
    """Full detail for one curated thematic group (group_show).

    Unlike group_list(all_fields=True), group_show for a single known
    group name/id is public on this deployment -- confirmed live, no
    authentication required.
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance
