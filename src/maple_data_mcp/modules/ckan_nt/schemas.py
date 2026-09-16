"""Typed response models for the Northwest Territories Open Data (CKAN NT)
module.

Field names and nullability verified against live responses fetched this
session (package_search, package_show, organization_list,
organization_show, group_list, group_show, tag_list, resource_show,
license_list against real opendata.gov.nt.ca records), not guessed from
generic CKAN documentation or carried over unverified from
modules/ckan_federal/. Deployment-specific quirks that shape these
models, confirmed live:

1. This portal genuinely uses CKAN tags and groups -- the opposite of
   the federal portal. `tag_list` returned 151 real tag names and
   `group_list` returned 15 real topic groups, each with a description
   and package_count (e.g. "Home and Community", 82 datasets); sampled
   packages' `tags`/`groups` arrays are populated, not empty. TagList
   and GroupList/GroupSummary are defined here as a direct result --
   there is no equivalent in ckan_federal's schemas.py to reuse.
2. There is no bilingual multilingual-extension data anywhere on this
   deployment -- no package, resource, organization, or license record
   in any sample carried a `<field>_translated` dict or `_fra`-suffixed
   field, and no French-language path exists (`/fr/dataset/<id>` and
   `/dataset/fr/<id>` both 404, confirmed live). Every text field below
   is therefore a single flat value, unlike ckan_federal's
   `pick_translated`/`pick_fra`-mediated fields; `lang` is still accepted
   on every tool (see tools.py) but never changes a returned value here.
3. `organization_show`'s `image_url` is a bare uploaded filename (e.g.
   "2022-12-17-221301.774223StatsBureau.png"), not a usable URL --
   confirmed live. The full, clickable URL is in the separate
   `image_display_url` field instead. OrganizationDetail.image_url below
   is populated from `image_display_url`, not `image_url`, to avoid
   handing an agent a dead link (see client.py).
4. Resources here carry no `language` field at all (confirmed live
   across every sampled resource) -- unlike ckan_federal's resources,
   which always carry `language: list[str]`. ResourceInfo below omits
   that field rather than defaulting it to a fabricated empty list that
   would misleadingly imply the field was checked and found empty.
5. `package_show`/`package_search` results also carry several
   deployment-specific descriptive fields with no ckan_federal
   equivalent -- `topic` (a single free-text category, distinct from the
   structured `groups` list), `update_frequency`, `source`, and
   `geographic_range` -- confirmed live and populated on real packages
   often enough to be worth surfacing on PackageDetail. They are left
   out of PackageSummary to keep search results compact, matching
   ckan_federal's PackageSummary/PackageDetail split.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    `size` is frequently null even for resources that clearly have a
    file behind them (confirmed live on several sampled resources) --
    this portal does not backfill size for every resource, not a
    parsing gap here. See the module docstring (point 4) for why there
    is no `language` field, unlike ckan_federal.ResourceInfo.
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
    """Standalone resource result (ckan_nt_get_resource).

    Wraps ResourceInfo with provenance rather than adding provenance to
    ResourceInfo directly, since ResourceInfo is also used nested inside
    PackageDetail.resources -- matching ckan_federal.schemas's own
    convention.
    """

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result.

    Unlike ckan_federal's OrganizationRef, `title` here is a single
    plain-English string (e.g. "Bureau of Statistics"), not a combined
    "English | French" convention -- this portal has no French content
    to combine (see module docstring, point 2).
    """

    id: str
    name: str
    title: str


class GroupRef(BaseModel):
    """The topic-group block embedded in a package result.

    Unlike ckan_federal (which has no group concept at all -- confirmed
    empty there), this portal's packages carry a populated `groups`
    array; each element identifies one of the 15 real topic groups
    (see GroupSummary/ckan_nt_list_groups for the full roster).
    """

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row.

    Deliberately excludes the full resource list, tag/group detail, and
    the NT-specific descriptive fields (topic, update_frequency, source,
    geographic_range) that PackageDetail (ckan_nt_get_dataset) carries --
    matching ckan_federal's PackageSummary/PackageDetail compactness
    split (AGENTS.md's agent-friendly-output principle). `topic` is the
    one exception: it is a single short string cheap enough to keep in
    the summary row and useful for scanning results without opening the
    full record.
    """

    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    notes_excerpt: str
    topic: str | None = None
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
    """Full dataset (package) record, including its resources, tags, and
    groups."""

    id: str
    title: str
    notes: str
    organization: OrganizationRef | None = None
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    is_open: bool
    tags: list[str] = Field(default_factory=list)
    groups: list[GroupRef] = Field(default_factory=list)
    topic: str | None = None
    update_frequency: str | None = None
    source: str | None = None
    geographic_range: str | None = None
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

    `image_url` is populated from the upstream `image_display_url`
    field, not the upstream `image_url` field -- see module docstring,
    point 3.
    """

    id: str
    name: str
    title: str
    description: str | None = None
    package_count: int
    image_url: str | None = None
    landing_page_url: str
    provenance: Provenance


class GroupSummary(BaseModel):
    """One row from group_list(all_fields=True).

    Unlike ckan_federal (which has no group concept), this portal's 15
    groups are real, populated topic categories (confirmed live) --
    each with a genuine description and package_count, not an empty
    placeholder.
    """

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


class TagList(BaseModel):
    """The full tag vocabulary from tag_list (151 live tags, confirmed).

    Kept as plain names (not full tag objects) since tag_list's
    `all_fields=true` form adds only `id`/`vocabulary_id` beyond the
    name -- no package_count or description the way groups have --
    and a plain name is what ckan_nt_search_datasets' `fq="tags:<name>"`
    filter actually needs.
    """

    tags: list[str]
    total_count: int
    provenance: Provenance


class LicenseInfo(BaseModel):
    """One entry from license_list.

    `is_okd_compliant`/`is_osi_compliant` are this API's actual openness
    flags on a license record, matching ckan_federal's LicenseInfo shape
    exactly -- confirmed live these field names carry over unchanged.
    Unlike ckan_federal's license_list, no entry here carries a
    `title_fra`/`url_fra` pair (see module docstring, point 2), so
    `lang` has no effect on this tool.
    """

    id: str
    title: str
    url: str | None = None
    status: str
    is_okd_compliant: bool
    is_osi_compliant: bool


class LicenseList(BaseModel):
    licenses: list[LicenseInfo]
    provenance: Provenance
