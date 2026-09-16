"""Typed response models for the Yukon Open Data (CKAN ckan_yt) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list, tag_list, group_list
against real open.yukon.ca records), not carried over unexamined from
the federal module. Real deployment-specific differences from
ckan_federal shape these models:

1. This portal genuinely uses CKAN tags and groups -- confirmed live:
   `tag_list` returns 914 names, `group_list` returns 17 subject
   categories, and every sampled package's `tags`/`groups` arrays are
   populated (unlike federal, where both are always empty). Tag/group
   models and tools are defined here as a result (see TagList/GroupList
   below and client.py's list_tags/list_groups).
2. There is no bilingual `_translated`/`_fra` convention anywhere on
   this deployment -- confirmed live by scanning several real package,
   organization, resource, and license records for any key containing
   "translat" or "fra"; none was found. `lang` is still accepted on
   every client function/tool, per this repo's convention, but has no
   effect on any field value here -- only on which `landing_page_url`
   chrome variant is returned (see constants.py).
3. This deployment runs on a CKAN instance with a DKAN-derived package
   schema carrying several extra fields the federal portal's package
   records do not have: `custodian` (a plain-text data steward, often
   more specific than the owning `organization`), `update_frequency`,
   `homepage_url` (frequently populated even when the CKAN-standard
   `url` field is null), and `isopen`. These are surfaced where they
   add real value rather than omitted for parity with federal's schema.
4. `license_list` here does not follow either of the federal portal's
   two bilingual conventions -- it instead carries CKAN's own openness
   taxonomy fields (`family`, `maintainer`, `domain_content`,
   `domain_data`, `domain_software`, `od_conformance`,
   `osd_conformance`) with no `is_okd_compliant`/`is_osi_compliant`
   booleans at all. `od_conformance`/`osd_conformance` are free-text
   status strings here (e.g. "approved", "not reviewed"), not booleans.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    Unlike the federal portal, `size` was populated on every sampled
    resource with a concrete file format (confirmed live: 84 of 84 PDF
    resources in a 20-dataset sample carried a non-null `size`) -- still
    modeled as optional since resources pointing at an external service
    (e.g. an ArcGIS Online layer, confirmed live) carry a null `size`.
    There is no per-resource `language` field on this deployment (only
    a package-level one, itself unused -- see schemas.py's module
    docstring), unlike ResourceInfo.language on the federal module.
    """

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str
    size: int | None = None
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_yt_get_resource).

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

    Deliberately excludes the full resource list that PackageDetail
    (ckan_yt_get_dataset) carries -- a package_search query can match
    hundreds of this catalogue's 3,841 datasets, so results stay
    compact per AGENTS.md's agent-friendly-output principle; open the
    full record with ckan_yt_get_dataset once a candidate is chosen.
    `tags`/`groups` are kept here (unlike the excluded resource list)
    because they are short, plain-string lists that are directly useful
    for deciding whether a search hit is relevant.
    """

    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    custodian: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
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
    """Full dataset (package) record, including its resources."""

    id: str
    title: str
    notes: str
    organization: OrganizationRef | None = None
    custodian: str | None = None
    update_frequency: str | None = None
    homepage_url: str | None = None
    isopen: bool
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

    `lang` has no effect on `title`/`description` here -- confirmed
    live that organization_show carries no `title_translated` on this
    deployment at all (unlike the federal portal, where it does).
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class LicenseInfo(BaseModel):
    """One entry from license_list.

    This deployment's license records carry CKAN's own openness
    taxonomy (`family`, `maintainer`, `domain_*`, `od_conformance`,
    `osd_conformance`) rather than the federal portal's
    `is_okd_compliant`/`is_osi_compliant` booleans -- confirmed live,
    see schemas.py's module docstring, point 4.
    """

    id: str
    title: str
    url: str | None = None
    status: str
    family: str | None = None
    maintainer: str | None = None
    domain_content: bool
    domain_data: bool
    domain_software: bool
    od_conformance: str | None = None
    osd_conformance: str | None = None


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance


class TagList(BaseModel):
    """Every free-text subject tag used across the catalogue.

    Confirmed live: `tag_list` (with or without `all_fields=true`)
    carries no per-tag dataset count -- only id/name/display_name/
    vocabulary_id, with `vocabulary_id` always null on this deployment.
    A tag's popularity is available via ckan_yt_search_datasets'
    `fq=tags:<name>` results, not from this listing.
    """

    tags: list[str]
    total_count: int
    provenance: Provenance


class GroupSummary(BaseModel):
    """One subject-category group from group_list(all_fields=True)."""

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    landing_page_url: str


class GroupList(BaseModel):
    """Every subject-category group this portal classifies datasets into.

    Unlike the federal portal (which has no groups at all), this
    deployment uses groups as its primary subject taxonomy (17 broad
    categories, confirmed live) -- distinct from the free-text `tags`
    vocabulary.
    """

    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance
