"""Typed response models for the City of Toronto Open Data (CKAN
Toronto) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list, tag_list against real
ckan0.cf.opendata.inter.prod-toronto.ca records), not guessed from
generic CKAN documentation or carried over unverified from the federal
module. Several deployment-specific quirks shape these models,
differing from both generic CKAN docs and ckan_federal's own confirmed
behavior:

1. This portal DOES use CKAN tags (unlike the federal portal): tag_list
   returns 909 populated tag names live, and sampled packages carry
   real `tags` arrays (each a dict with `name`/`display_name`/`id`/
   `vocabulary_id` -- flattened to plain tag-name strings here, since
   `id`/`vocabulary_id` carry no useful information for every tag
   observed). group_list, however, returns `[]` live and every sampled
   package's `groups` array is empty -- this portal does not use CKAN
   groups. No group model or tool is defined here as a result.
2. This portal is English-only in its actual CKAN data -- confirmed
   live: no `_translated` or `_fra`-suffixed field appears on any of 50
   sampled packages, resources, or the single organization record.
   `lang` is still accepted on every tool per this repo's convention,
   but it has no effect (see client.py).
3. `package_search`/`package_show` results carry several
   municipal-specific fields the federal portal's deployment does not
   have: a curated `excerpt` (short public-facing summary, distinct
   from `notes`), `dataset_category` (Document/Map/Table/Website),
   `topics` (a list of subject-area tags, e.g. ["Transportation",
   "Public safety"]), `refresh_rate` (update cadence in plain
   language), `is_retired`, `civic_issues`, and `limitations` (known
   caveats a publisher wrote about the data). These are real discovery
   value for an agent choosing a dataset and are exposed here rather
   than dropped to match the federal shape.
4. `formats` is already provided at the package level (the set of
   resource formats, pre-aggregated) -- unlike the federal portal,
   where this module has to compute it by iterating `resources`.
5. Resources here carry no `description` or `language` field at all
   (confirmed live across 342 sampled resources: neither key appears on
   any resource, not even as null/empty) -- ResourceInfo omits both
   rather than modelling fields that never exist on this deployment.
   Resources do carry `datastore_active` (whether the file is also
   queryable through CKAN's datastore API) and, when true, a
   `record_count` -- both are exposed here since they tell an agent
   whether a resource is a flat-file download or a queryable table.
6. `license_list` here is the CKAN stock/default license register
   (`domain_content`/`domain_data`/`domain_software`/`is_generic` as
   JSON *strings* `"True"`/`"False"`, plus `od_conformance`/
   `osd_conformance` status strings) -- structurally different from the
   federal portal's customized `is_okd_compliant`/`is_osi_compliant`
   booleans and `title_fra`/`url_fra` bilingual fields. LicenseInfo
   below models Toronto's actual shape, not federal's.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    No `description`/`language` fields -- confirmed live these never
    appear on a Toronto resource (see module docstring, point 5).
    `record_count` is only meaningful when `datastore_active` is true.
    """

    id: str
    package_id: str | None = None
    name: str
    format: str | None = None
    url: str
    size: int | None = None
    datastore_active: bool = False
    record_count: int | None = None
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_toronto_get_resource).

    Wraps ResourceInfo with provenance rather than adding provenance to
    ResourceInfo directly, matching ckan_federal's own convention (see
    that module's schemas.py for the rationale).
    """

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result.

    Only one organization exists on this portal (city-of-toronto,
    confirmed live) -- this model still exists for parity with
    ckan_federal's shape and because a package result embeds it
    regardless.
    """

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row.

    `excerpt` is this portal's own curated summary field, used as-is
    (with a defensive length cap) rather than truncated from `notes`
    the way ckan_federal's `notes_excerpt` is -- see constants.py's
    EXCERPT_MAX_LENGTH and module docstring point 3.
    """

    id: str
    title: str
    organization_name: str | None = None
    organization_title: str | None = None
    excerpt: str
    dataset_category: str | None = None
    license_id: str | None = None
    license_title: str | None = None
    is_retired: bool = False
    num_resources: int
    formats: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    refresh_rate: str | None = None
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
    excerpt: str
    organization: OrganizationRef
    license_id: str | None = None
    license_title: str | None = None
    dataset_category: str | None = None
    is_retired: bool = False
    information_url: str | None = None
    limitations: str | None = None
    civic_issues: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    refresh_rate: str | None = None
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
    """Result of ckan_toronto_list_organizations.

    Confirmed live: this portal publishes through exactly one
    organization (city-of-toronto) -- so this list will always have
    `total_count == 1`. The tool still exists for interface parity with
    ckan_federal and because a future portal restructuring could add
    more; see tools.py for how this is documented to an agent.
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
    """One entry from license_list.

    Models Toronto's actual (stock CKAN) license shape -- see module
    docstring point 6 for why this differs from ckan_federal's
    LicenseInfo. The upstream API sends `domain_content`/`domain_data`/
    `domain_software`/`is_generic` as the JSON strings "True"/"False"
    rather than booleans (confirmed live); client.py coerces these to
    real booleans before constructing this model.
    """

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
    """Result of ckan_toronto_list_tags.

    Confirmed live: tag_list (without all_fields) returns a plain list
    of tag-name strings, which is what an agent actually needs to
    filter package_search with `fq=tags:<name>` -- the all_fields form
    adds only `id`/`vocabulary_id`, neither useful here (every sampled
    tag has `vocabulary_id: null`).
    """

    tags: list[str]
    total_count: int
    provenance: Provenance
