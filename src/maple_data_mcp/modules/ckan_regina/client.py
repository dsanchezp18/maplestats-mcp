"""HTTP client for the City of Regina Open Data (CKAN Regina) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused here the same way every other ckan_<portal> module does. What
is deployment-specific, confirmed live this session:

- `package_show`/`organization_show`/`resource_show`/`group_show`
  return HTTP 404 with a standard CKAN JSON error envelope
  (`{"error": {"__type": "Not Found Error", "message": "Not found"},
  "success": false}`) for an unknown id -- shared/ckan.py's
  `_error_detail` already handles this shape.
- `tag_list`/`group_list(all_fields=true)` are both public with no
  authentication needed (unlike ckan_bc, where group_list needs auth
  and a package_search facet has to be used instead) -- confirmed
  live, both return HTTP 200.
- Exactly one organization exists (city-of-regina, 1,379 packages) --
  confirmed live via organization_list(all_fields=true), the same
  single-organization shape as ckan_toronto.
- `license_list` returns real JSON booleans for its domain_*/is_generic
  fields (confirmed live), unlike ckan_toronto's string-typed
  "True"/"False" -- `to_bool()` is still applied uniformly since it is
  a no-op on an already-real boolean.
- This deployment has no curated `excerpt` field -- `notes` is
  truncated client-side for PackageSummary, the same pattern as
  ckan_federal/ckan_bc.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_regina import constants
from maple_data_mcp.modules.ckan_regina.schemas import (
    GroupDetail,
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
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _tag_names(tags: list[dict[str, Any]]) -> list[str]:
    return [t["name"] for t in tags if t.get("name")]


def _group_names(groups: list[dict[str, Any]]) -> list[str]:
    return [g["name"] for g in groups if g.get("name")]


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj.get("name") or obj["id"],
        description=obj.get("description") or None,
        format=obj.get("format") or None,
        url=obj.get("url") or None,
        size=obj.get("size"),
        datastore_active=to_bool(obj.get("datastore_active")),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype"),
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any]) -> PackageSummary:
    org = obj.get("organization") or {}
    return PackageSummary(
        id=obj["id"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=excerpt(obj.get("notes") or "", constants.NOTES_EXCERPT_MAX_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        tags=_tag_names(list_or_empty(obj, "tags")),
        groups=_group_names(list_or_empty(obj, "groups")),
        num_resources=get_or(obj, "num_resources", len(list_or_empty(obj, "resources"))),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['name']}",
    )


def _package_detail_from_json(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    return PackageDetail(
        id=obj["id"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(obj["organization"]),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        tags=_tag_names(list_or_empty(obj, "tags")),
        groups=_group_names(list_or_empty(obj, "groups")),
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_regina.PackageDetail",
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
    """Full-text/filtered dataset search over `package_search`; ``lang`` is accepted for consistency."""
    del lang
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    cache_key = f"ckan-regina:package_search:{query}:{fq}:{rows}:{start}:{sort}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_search", params=params)

    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)

    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "count", len(raw_results))
    packages = [_package_summary_from_json(obj) for obj in raw_results]
    return PackageSearchResult(
        packages=packages,
        total_count=total_count,
        returned_count=len(packages),
        start=start,
        rows=rows,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_regina.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    """``dataset_id`` accepts either the package's UUID or its slug name; ``lang`` is a documented no-op."""
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-regina:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List the publishing organization(s); ``lang`` is a documented no-op.

    Confirmed live this portal has exactly one organization
    (city-of-regina).
    """
    del lang
    cache_key = "ckan-regina:organization_list:all_fields"

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
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_regina.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
            coverage="this portal publishes through a single organization (city-of-regina)",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    del lang
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-regina:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
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
        image_url=obj.get("image_display_url") or obj.get("image_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_regina.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    del lang
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-regina:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_regina.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    del lang
    cache_key = "ckan-regina:license_list"

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
            domain_content=to_bool(lic.get("domain_content")),
            domain_data=to_bool(lic.get("domain_data")),
            domain_software=to_bool(lic.get("domain_software")),
            is_generic=to_bool(lic.get("is_generic")),
            od_conformance=lic.get("od_conformance") or None,
            osd_conformance=lic.get("osd_conformance") or None,
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_regina.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    del lang
    cache_key = "ckan-regina:tag_list"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    return TagList(
        tags=list(tags_raw),
        total_count=len(tags_raw),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_regina.TagList",
            freshness="tag vocabulary changes infrequently; cached 24h",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List this portal's curated thematic groups; ``lang`` is a documented no-op.

    Built directly from `group_list(all_fields=true)`, which is public
    on this deployment -- unlike ckan_bc, no package_search facet
    workaround is needed (see module docstring).
    """
    del lang
    cache_key = "ckan-regina:group_list:all_fields"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "group_list", params={"all_fields": "true"})

    groups_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_GROUP_LIST_SECONDS, fetch
    )
    groups = [
        GroupSummary(
            name=g["name"],
            title=g.get("title") or g["name"],
            package_count=get_or(g, "package_count", 0),
            landing_page_url=f"{constants.GROUP_LANDING_URL}{g['name']}",
        )
        for g in groups_raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}group_list?all_fields=true",
            cached=was_cached,
            schema_name="ckan_regina.GroupList",
            freshness="group roster changes infrequently; cached 24h",
        ),
    )


async def get_group(group_id: str, lang: str = "en") -> GroupDetail:
    del lang
    if not group_id.strip():
        raise InvalidInput("group_id must not be empty.")
    cache_key = f"ckan-regina:group_show:{group_id}"

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG, "group_show", params={"id": group_id, "include_datasets": "false"}
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_GROUP_SECONDS, fetch)
    return GroupDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj.get("title") or obj["name"],
        description=obj.get("description") or None,
        package_count=get_or(obj, "package_count", 0),
        image_url=obj.get("image_display_url") or obj.get("image_url") or None,
        landing_page_url=f"{constants.GROUP_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}group_show?id={group_id}",
            cached=was_cached,
            schema_name="ckan_regina.GroupDetail",
        ),
    )
