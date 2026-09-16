"""HTTP client for the Yukon Open Data (CKAN ckan_yt) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused as-is: confirmed live this session that package_show/
organization_show/resource_show 404s and package_search's
malformed-sort 400 both come back in the identical
`{"help","success","result"}`/`{"error":{"__type",...}}` shape the
federal module already verified, so no deployment-specific error
handling is needed here. What is genuinely deployment-specific,
confirmed live this session:

- `site_read` returns HTTP 400 on this deployment (unexplained, but
  reproducible) -- `package_list`/`package_search` were used for
  connectivity checks instead, per the task brief.
- Every package, organization, resource, and license record scanned
  carries no `_translated`- or `_fra`-suffixed field anywhere -- this
  portal is English-only at the CKAN-data level. `lang` is accepted on
  every function below for interface consistency with every other
  module in this repo, but the only place it has any effect is the
  `{lang}`-prefixed `landing_page_url` (the site's UI chrome is
  genuinely bilingual even though the underlying data is not -- see
  constants.py).
- `tag_list` and `group_list` are both genuinely populated here (914
  tags, 17 groups), unlike the federal portal where both are always
  empty -- see list_tags/list_groups below and schemas.py's module
  docstring.
- Packages carry several DKAN-legacy fields the federal portal's do
  not: `custodian`, `update_frequency`, `homepage_url`, `isopen`. These
  are surfaced in PackageSummary/PackageDetail where they add value
  (see schemas.py point 3).
- `license_list` records use a different openness taxonomy than the
  federal portal's `is_okd_compliant`/`is_osi_compliant` booleans --
  `family`/`maintainer`/`domain_*`/`od_conformance`/`osd_conformance`
  instead, confirmed live (see schemas.py point 4). No pick_fra() call
  is needed here since these fields are not bilingual.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_yt import constants
from maple_data_mcp.modules.ckan_yt.schemas import (
    GroupList,
    GroupSummary,
    LicenseInfo,
    LicenseList,
    OrganizationDetail,
    OrganizationList,
    OrganizationRef,
    OrganizationSummary,
    PackageDetail,
    PackageSearchResult,
    PackageSummary,
    ResourceDetail,
    ResourceInfo,
    TagList,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.ckan import CkanConfig, action, excerpt, parse_dt, to_bool
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import get_or, list_or_empty

CONFIG = CkanConfig(
    source="ckan-yt",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _tag_names(obj: dict[str, Any]) -> list[str]:
    """Flatten this deployment's embedded tag objects to plain names.

    Confirmed live: a package's `tags` array holds full objects
    (`{"id", "name", "display_name", "state", "vocabulary_id"}`), not
    bare strings -- unlike the federal portal, which never populates
    this field at all. Guards against an unsampled bare-string entry
    (an unconfirmed vocabulary/facet edge case) rather than assuming
    every entry is a dict.
    """
    return [t["name"] for t in list_or_empty(obj, "tags") if isinstance(t, dict) and t.get("name")]


def _group_names(obj: dict[str, Any]) -> list[str]:
    """Flatten this deployment's embedded group objects to plain names.

    Same shape distinction as `_tag_names`: a package's `groups` array
    holds full objects, keyed by `name` (the short slug used in
    group_show/fq filters), not `title`. Same defensive shape guard.
    """
    return [
        g["name"] for g in list_or_empty(obj, "groups") if isinstance(g, dict) and g.get("name")
    ]


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj.get("name") or obj["id"],
        description=obj.get("description") or None,
        format=obj.get("format") or None,
        url=obj["url"],
        size=obj.get("size"),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype") or None,
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any], lang: str) -> PackageSummary:
    org = obj.get("organization") or {}
    notes = obj.get("notes") or ""
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    return PackageSummary(
        id=obj["id"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        custodian=obj.get("custodian") or None,
        notes_excerpt=excerpt(notes, constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        tags=_tag_names(obj),
        groups=_group_names(obj),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resource_formats=formats,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
    )


def _package_detail_from_json(obj: dict[str, Any], lang: str, *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    return PackageDetail(
        id=obj["id"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(org) if (org := obj.get("organization")) else None,
        custodian=obj.get("custodian") or None,
        update_frequency=obj.get("update_frequency") or None,
        homepage_url=obj.get("homepage_url") or None,
        isopen=to_bool(obj.get("isopen")),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        tags=_tag_names(obj),
        groups=_group_names(obj),
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_yt.PackageDetail",
        ),
    )


async def search_datasets(
    query: str = "",
    *,
    fq: str | None = None,
    rows: int = constants.SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: str = "en",
) -> PackageSearchResult:
    """Full-text/filtered dataset search over `package_search`.

    An empty `query` is a deliberate match-all, not an error -- confirmed
    live that `package_search?rows=0` with no `q` returns the full
    3,841-dataset count. `fq` can filter by tag (`tags:mining`), group
    (`groups:economics-and-industry`), organization
    (`organization:geomatics-yukon`), or format (`res_format:CSV`),
    confirmed live.
    """
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    cache_key = f"ckan-yt:package_search:{query}:{fq}:{rows}:{start}:{sort}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_search", params=params)

    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)

    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "count", len(raw_results))
    packages = [_package_summary_from_json(obj, lang) for obj in raw_results]
    return PackageSearchResult(
        packages=packages,
        total_count=total_count,
        returned_count=len(packages),
        start=start,
        rows=rows,
        query=query,
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_yt.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-yt:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, lang, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`.

    `lang` has no effect here -- confirmed live that organization_list
    carries no bilingual field of any kind on this deployment (see
    schemas.py's module docstring, point 2).
    """
    cache_key = "ckan-yt:organization_list:all_fields"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "organization_list", params={"all_fields": "true"})

    orgs_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_ORGANIZATION_LIST_SECONDS, fetch
    )
    organizations = [
        OrganizationSummary(
            id=o["id"],
            name=o["name"],
            title=o.get("title") or o["name"],
            package_count=get_or(o, "package_count", 0),
        )
        for o in orgs_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_yt.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-yt:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false so this stays compact --
        # full dataset listing for an org goes through
        # search_datasets(fq="organization:<name>") instead, same as
        # the federal module.
        return await action(
            CONFIG,
            "organization_show",
            params={"id": organization_id, "include_datasets": "false"},
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ORGANIZATION_SECONDS, fetch)
    return OrganizationDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj.get("title") or obj["name"],
        description=obj.get("description") or None,
        package_count=get_or(obj, "package_count", 0),
        image_url=obj.get("image_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL.format(lang=lang)}{obj['name']}",
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_yt.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-yt:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_yt.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under.

    `lang` has no effect -- confirmed live that license_list records
    here carry no `_fra`-suffixed field at all, unlike the federal
    portal's `title_fra`/`url_fra` (see schemas.py, point 4).
    """
    cache_key = "ckan-yt:license_list"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "license_list")

    licenses_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_LICENSE_LIST_SECONDS, fetch
    )
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=lic["title"],
            url=lic.get("url") or None,
            status=lic.get("status", "unknown"),
            family=lic.get("family") or None,
            maintainer=lic.get("maintainer") or None,
            domain_content=to_bool(lic.get("domain_content")),
            domain_data=to_bool(lic.get("domain_data")),
            domain_software=to_bool(lic.get("domain_software")),
            od_conformance=lic.get("od_conformance") or None,
            osd_conformance=lic.get("osd_conformance") or None,
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_yt.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    """List every free-text subject tag used across the catalogue.

    Confirmed live: this portal's `tag_list` returns 914 names -- the
    federal portal's equivalent call always returns `[]`, which is why
    ckan_federal has no tag tool at all (see schemas.py's TagList
    docstring for why counts aren't included).
    """
    cache_key = "ckan-yt:tag_list"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    return TagList(
        tags=tags_raw,
        total_count=len(tags_raw),
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_yt.TagList",
            freshness="tag vocabulary changes infrequently; cached 24h",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List every subject-category group via `group_list(all_fields=True)`.

    Confirmed live: this portal defines 17 broad subject groups
    (agriculture, economics-and-industry, ...) -- the federal portal
    has none at all (see schemas.py's GroupList docstring). `lang` has
    no effect on `title`/`description` here -- confirmed live that
    group_list carries no bilingual field on this deployment.
    """
    cache_key = "ckan-yt:group_list:all_fields"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "group_list", params={"all_fields": "true"})

    groups_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_GROUP_LIST_SECONDS, fetch
    )
    groups = [
        GroupSummary(
            id=g["id"],
            name=g["name"],
            title=g.get("title") or g["name"],
            description=g.get("description") or None,
            package_count=get_or(g, "package_count", 0),
            landing_page_url=f"{constants.GROUP_LANDING_URL.format(lang=lang)}{g['name']}",
        )
        for g in groups_raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="ckan-yt",
            url=f"{constants.BASE_URL}group_list",
            cached=was_cached,
            schema_name="ckan_yt.GroupList",
            freshness="group taxonomy changes infrequently; cached 24h",
        ),
    )
