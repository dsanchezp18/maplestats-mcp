"""Typed response models for the Government of Canada Open Data (CKAN
federal) module.

Field names and nullability verified against live responses fetched
this session (package_search, package_show, organization_list,
organization_show, resource_show, license_list against real
open.canada.ca records), not guessed from generic CKAN documentation.
Two deployment-specific quirks shape these models:

1. This portal does not use CKAN's `tags`/`tag_string` field or CKAN
   groups at all -- confirmed live: `tag_list` returns `[]`, every
   sampled package's `tags` array is `[]`, and `group_list` returns
   `[]`. Free-text subject terms live instead in a bilingual `keywords`
   field (`{"en": [...], "fr": [...]}`). No tag/group model or tool is
   defined here as a result.
2. Bilingual text is not one flat field per language (unlike, say,
   StatCan WDS's `*En`/`*Fr` pairs) -- it is a flat, English-default
   field (`title`, `notes`, resource `name`/`description`) plus an
   optional `<field>_translated` dict CKAN's multilingual extension
   attaches (`{"en": ..., "fr": ...}`). The `fr` key is occasionally
   absent from a `_translated` dict (~2% of a live 100-dataset sample);
   `en` was never absent. See client.py's `_pick_translated`/
   `_pick_translated_list` for the fallback this requires.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class ResourceInfo(BaseModel):
    """One downloadable file/resource attached to a dataset.

    `size` is frequently null even for resources that clearly have a
    file behind them (confirmed live: null on 955 of 1,135 resources in
    a 100-dataset sample) -- this portal does not backfill size for
    every resource, not a parsing gap here.
    """

    id: str
    package_id: str | None = None
    name: str
    description: str | None = None
    format: str | None = None
    url: str
    size: int | None = None
    language: list[str] = Field(default_factory=list)
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    mimetype: str | None = None
    datastore_active: bool = Field(
        default=False,
        description=(
            "Whether this resource's rows can be queried directly with "
            "ckan_datastore_search instead of only downloaded whole from `url`."
        ),
    )


class ResourceDetail(BaseModel):
    """Standalone resource result (ckan_get_resource).

    Wraps ResourceInfo with provenance rather than adding provenance to
    ResourceInfo directly, since ResourceInfo is also used nested inside
    PackageDetail.resources -- matching statcan/wds's own convention of
    only attaching provenance to a tool's top-level return type, not to
    every nested model (see wds/schemas.py's CubeDimension/Footnote).
    """

    resource: ResourceInfo
    provenance: Provenance


class OrganizationRef(BaseModel):
    """The organization block embedded in a package result.

    Unlike organization_show, this embedded form carries no
    `title_translated` -- confirmed live -- only a single `title` that
    is this portal's own "English name | French name" convention (e.g.
    "Natural Resources Canada | Ressources naturelles Canada"). Passed
    through as-is rather than split, since not every title reliably
    contains exactly one " | " separator (some organizations use the
    same string on both sides).
    """

    id: str
    name: str
    title: str


class PackageSummary(BaseModel):
    """One compact search-result row.

    Deliberately excludes the full resource list and multilingual
    detail that PackageDetail (ckan_get_dataset) carries -- a
    package_search query can match thousands of this catalogue's
    ~48,000 datasets, so results stay compact per AGENTS.md's
    agent-friendly-output principle; open the full record with
    ckan_get_dataset once a candidate is chosen.
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
    """Full dataset (package) record, including its resources."""

    id: str
    title: str
    notes: str
    organization: OrganizationRef
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    keywords: list[str] = Field(default_factory=list)
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    num_resources: int
    resources: list[ResourceInfo]
    landing_page_url: str
    provenance: Provenance


class OrganizationSummary(BaseModel):
    """One row from organization_list(all_fields=True).

    `title` here is the same combined "English | French" convention as
    OrganizationRef -- confirmed live that organization_list, unlike
    organization_show, does not attach a `title_translated` dict.
    """

    id: str
    name: str
    title: str
    package_count: int


class OrganizationList(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    provenance: Provenance


class OrganizationDetail(BaseModel):
    """Full organization record, resolved to one language.

    Unlike organization_list, organization_show DOES attach
    `title_translated` -- confirmed live -- so this model's `title`
    reflects the requested `lang` properly, rather than the combined
    "English | French" string OrganizationList/OrganizationRef carry.
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

    `is_okd_compliant`/`is_osi_compliant` are this API's actual openness
    flags on a license record -- there is no `isopen` field here (that
    field exists only on a *package*, as a separate boolean, confirmed
    live).
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


class DatastoreField(BaseModel):
    id: str
    type: str


class DatastoreSearchResult(BaseModel):
    """Row-level query against one DataStore-active resource (see
    ResourceInfo.datastore_active), as opposed to ckan_get_resource's
    metadata-only view. Not every resource supports this -- most
    resources on this portal are plain files, not DataStore tables."""

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
