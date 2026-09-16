"""Typed response models for the City of Montreal open-data (CKAN
Montreal) module.

Field names and nullability verified against live responses fetched this
session (package_search, package_show, organization_list,
organization_show, resource_show, tag_list, group_list, license_list
against real donnees.montreal.ca records), not guessed from generic CKAN
documentation. Deployment-specific quirks that shape these models,
distinct from ckan_federal's:

1. No bilingual extension at all. Every sampled package carries a flat
   `language: "FR"` field and no `<field>_translated` dict anywhere
   (confirmed live: 50-package sample all `"FR"`, and `fq=language:EN`
   returns 0 of 404 total). `title`/`notes`/resource `name`/`description`
   are plain strings, not picked between languages -- there is no
   `pick_translated` call anywhere in client.py as a result.
2. Tags and groups are real here (unlike federal, which uses neither):
   `tag_list` returns 1,174 distinct names and `group_list` returns 12
   real groups with French descriptions and non-trivial `package_count`.
   `PackageDetail`/`PackageSummary` carry `tags`/`groups` as plain
   `list[str]` (names only) for compactness; full group detail (title,
   description, package_count) is available via
   `ckan_montreal_list_groups`.
3. Resources here carry no `language` field at all (confirmed live across
   a 50-package resource sample) -- `ResourceInfo` omits it entirely
   rather than defaulting it to `[]` the way federal's does, since the
   field genuinely does not exist on this deployment's resources.
4. An organization's `image_url` is a bare uploaded filename, not a
   usable URL (confirmed live) -- `image_display_url` is the actual
   CDN-resolved link. `OrganizationDetail.image_url` below is sourced
   from `image_display_url`, not the raw `image_url` field, despite the
   name match with ckan_federal's field of the same name.
5. `license_list` here uses CKAN's newer license-register shape
   (`family`, `maintainer`, `domain_content`/`domain_data`/
   `domain_software`, `od_conformance`/`osd_conformance`) -- confirmed
   live -- not federal's `is_okd_compliant`/`is_osi_compliant`/`status`
   flags. `LicenseInfo` below matches this deployment's actual fields.
6. `name` (the URL slug) and `id` (the UUID) are NOT always identical
   here (confirmed live, e.g. name="rsqa-indice-qualite-air" with a
   distinct UUID `id`) -- unlike federal, where they were confirmed
   equal. Both models below carry `id` and `name` as distinct fields
   rather than assuming one implies the other.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    `size` is frequently null for resources without an uploaded file
    (e.g. a "WEB" format resource that just links to an external
    interactive map, confirmed live) -- this portal does not backfill
    size for every resource, not a parsing gap here.
    """

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    resource_type: str | None = None
    url: str
    size: int | None = None
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_montreal_get_resource).

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
    (ckan_montreal_get_dataset) carries -- results stay compact per
    AGENTS.md's agent-friendly-output principle; open the full record
    with ckan_montreal_get_dataset once a candidate is chosen.
    """

    id: str
    name: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    is_open: bool
    num_resources: int
    resource_formats: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    update_frequency: str | None = None
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
    name: str
    title: str
    notes: str
    organization: OrganizationRef | None = None
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    is_open: bool
    tags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    update_frequency: str | None = None
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    num_resources: int
    resources: list[ResourceInfo]
    landing_page_url: str
    provenance: Provenance


class OrganizationSummary(BaseModel):
    """One row from organization_list(all_fields=True). Only 6 total,
    confirmed live -- this is a small municipal roster, not federal's
    ~350 departments/agencies."""

    id: str
    name: str
    title: str
    description_excerpt: str | None = None
    package_count: int


class OrganizationList(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    """Full organization record."""

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class TagList(BaseModel):
    """All distinct tag names in use (`tag_list`), 1,174 confirmed live.

    Plain names only -- `tag_list`'s default (non-`vocabulary_id`) call
    returns bare strings, not objects with ids/counts, confirmed live.
    """

    tags: list[str]
    total_count: int
    provenance: Provenance


class GroupSummary(BaseModel):
    """One row from group_list(all_fields=True), 12 confirmed live --
    real subject-area groupings with French titles/descriptions and
    non-trivial package_count, unlike federal, which has none."""

    id: str
    name: str
    title: str
    description_excerpt: str | None = None
    package_count: int


class GroupList(BaseModel):
    groups: list[GroupSummary]
    total_count: int
    provenance: Provenance


class LicenseInfo(BaseModel):
    """One entry from license_list.

    Uses this deployment's actual license-register fields (confirmed
    live) -- `is_okd_compliant`/`is_osi_compliant`/`status` from
    ckan_federal's LicenseInfo do NOT exist here; `od_conformance`/
    `osd_conformance` (free-text conformance strings, not booleans) and
    `domain_content`/`domain_data`/`domain_software` do.
    """

    id: str
    title: str
    url: str | None = None
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
