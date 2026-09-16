"""Typed response models for the Quebec Open Data (CKAN QC) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list, tag_list, and
group_list against real donneesquebec.ca records), not guessed from
generic CKAN documentation or carried over unchecked from ckan_federal.
Several deployment-specific quirks shape these models, all different
from ckan_federal's:

1. No bilingual-extension infrastructure exists on this portal at all
   -- confirmed live across every sampled record: no `_translated`
   dict, no `_fra`-suffixed field, anywhere. `title`/`notes`/etc. are
   plain flat strings. `language` is itself a flat, single string field
   on each package (not the list-valued field ckan_federal's
   ResourceInfo carries), and a live facet check found only two values
   across the whole catalogue: "FR" (1,601 of 1,610 datasets) and
   "FR_EN" (9) -- "FR_EN" describes the dataset's own content, not a
   second set of translated metadata fields for it. `lang` is accepted
   throughout for interface consistency but is a documented no-op; see
   client.py.
2. This portal DOES use CKAN tags and groups, unlike ckan_federal --
   confirmed live: 4,402 free-text tags and 12 curated thematic groups
   are actually populated on real packages. PackageSummary/PackageDetail
   carry `tags`/`groups` as a result, and this module defines
   ckan_qc_list_tags/ckan_qc_list_groups tools ckan_federal has no
   equivalent of.
3. `organization_list(all_fields=true)` and `organization_show` return
   the SAME rich shape here (both carry `description` and
   `image_display_url`) -- confirmed live. This is unlike ckan_federal,
   where organization_list is a thinner id/name/title/package_count row
   and only organization_show carries the fuller record. OrganizationSummary
   here is correspondingly richer than ckan_federal's.
4. An organization/group's real, clickable logo URL is the
   `image_display_url` field, not `image_url` -- confirmed live:
   `image_url` is the bare uploaded filename (e.g.
   "2020-11-11-154709.431257AMD.png"), while `image_display_url` is the
   full served URL. This module's `image_url` model field is sourced
   from the JSON's `image_display_url`, not its `image_url`, to avoid
   silently handing an agent a broken relative path.
5. `update_frequency` values are English keywords ("daily", "continuous",
   "hourly", ...) even though the rest of the portal's content is
   French -- confirmed live across a live sample. Passed through as-is
   rather than translated, since this is the field's real, verified
   value on this deployment, not a rendering artifact.
6. Resources here carry no `language` field at all (confirmed live: it
   is absent from every sampled resource_show/package resource object,
   unlike ckan_federal's ResourceInfo.language) but do carry a
   portal-specific `resource_type` (e.g. "donnees", "cartes") and a
   `datastore_active` flag -- both included here, and both absent from
   ckan_federal's ResourceInfo.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    `size` is frequently null even for a resource that clearly has a
    file behind it (confirmed live, the same pattern ckan_federal
    documented for its own portal) -- this deployment does not
    backfill size for every resource either.
    """

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str
    size: int | None = None
    resource_type: str | None = None
    datastore_active: bool = False
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_qc_get_resource).

    Wraps ResourceInfo with provenance rather than adding provenance to
    ResourceInfo directly, since ResourceInfo is also used nested inside
    PackageDetail.resources -- matching ckan_federal's own convention.
    """

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result.

    Unlike ckan_federal's OrganizationRef, `title` here is a plain
    French title with no combined "English | French" convention -- this
    portal has no such convention (see module docstring point 1).
    """

    id: str
    name: str
    title: str


class GroupRef(BaseModel):
    """One thematic group a package belongs to, as embedded in a
    package record. See ckan_qc_list_groups for the full curated list
    (12 groups live) with descriptions and dataset counts."""

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row.

    Deliberately excludes the full resource list and group descriptions
    that PackageDetail (ckan_qc_get_dataset) carries, matching
    ckan_federal's compactness rationale. Includes `tags`/`group_names`
    (absent from ckan_federal's equivalent model) because this portal's
    tags and groups are real, populated discovery signals -- confirmed
    live that only ~5% of sampled packages carry no tags/groups at all.
    """

    id: str
    name: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    license_id: str | None = None
    license_title: str | None = None
    num_resources: int
    resource_formats: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    group_names: list[str] = Field(default_factory=list)
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
    """Full dataset (package) record, including its resources.

    `has_spatial_data`/`methodology`/`temporal_coverage`/`update_frequency`
    have no ckan_federal equivalent -- confirmed live as genuinely
    populated, portal-specific metadata fields on this deployment
    (`spatial_data` is a flat "Oui"/"Non" string server-side, normalized
    to a bool here; see client.py).
    """

    id: str
    name: str
    title: str
    notes: str
    organization: OrganizationRef
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    groups: list[GroupRef] = Field(default_factory=list)
    language: str | None = None
    update_frequency: str | None = None
    has_spatial_data: bool | None = None
    methodology: str | None = None
    temporal_coverage: str | None = None
    is_open: bool = False
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    num_resources: int
    resources: list[ResourceInfo]
    landing_page_url: str
    provenance: Provenance


class OrganizationSummary(BaseModel):
    """One row from organization_list(all_fields=true).

    Richer than ckan_federal's OrganizationSummary -- confirmed live
    that, unlike the federal deployment, organization_list here already
    returns the same `description`/`image_display_url` fields
    organization_show does (see module docstring point 3), so there is
    no reason to omit them from the list row.
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None


class OrganizationList(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    """Full organization record.

    `lang` has no effect here (see module docstring point 1) -- title
    and description are always this portal's single French text.
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

    Confirmed live that this deployment's license records differ from
    ckan_federal's: there is no `is_osi_compliant` field (this
    deployment's analogous flag is spelled `is_ost_compliant`), and
    both compliance flags are entirely absent -- not `false` -- on some
    licenses (e.g. "CC0-1.0"), so both stay `bool | None` rather than
    being coerced to `False` the way ckan_federal's `bool(...)` does.
    """

    id: str
    title: str
    url: str | None = None
    status: str
    family: str | None = None
    is_okd_compliant: bool | None = None
    is_ost_compliant: bool | None = None


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance


class GroupInfo(BaseModel):
    """One thematic group from group_list(all_fields=true).

    Confirmed live: this portal's 12 groups are a small, curated,
    essentially static set of subject categories (e.g. "Transport",
    "Santé") -- a real, populated discovery axis ckan_federal has no
    equivalent of.
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    landing_page_url: str


class GroupList(BaseModel):
    groups: list[GroupInfo]
    total_count: int
    provenance: Provenance


class TagList(BaseModel):
    """Result of ckan_qc_list_tags.

    `query` echoes back the substring filter that was actually applied
    (None when the call was unfiltered), so a caller can tell an empty
    filtered result apart from an unfiltered, capped one --
    `truncated` is true only in the latter case (see client.py's
    TAGS_LIST_MAX handling).
    """

    tags: list[str]
    total_count: int
    query: str | None = None
    truncated: bool = False
    provenance: Provenance
