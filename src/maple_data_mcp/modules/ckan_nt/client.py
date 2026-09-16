"""HTTP client for the Northwest Territories Open Data (CKAN NT) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused here since it is CKAN's own core behavior, not something this
deployment customizes. What is deployment-specific, confirmed live this
session:

- `package_show`/`organization_show`/`group_show`/`resource_show` return
  HTTP 404 with `{"success": false, "error": {"__type": "Not Found
  Error", ...}}` for an unknown id -- mapped to NotFound by
  shared/ckan.py, the same shape as the federal portal.
- `package_search` returns HTTP 400 with
  `{"error": {"__type": "Search Query Error", ...}}` for a malformed
  `sort` value (e.g. an unknown sort field) -- mapped to InvalidInput,
  again matching the federal portal's shape exactly.
- This portal is English-only: no package, resource, organization, or
  license record in any live sample carried a `_translated` dict or a
  `_fra`-suffixed field, and `/fr/...`-prefixed paths 404. There is
  therefore nothing for shared/ckan.py's `pick_translated`/
  `pick_translated_list`/`pick_fra` to do here, and they are
  deliberately not imported -- every text field below is read straight
  off the flat upstream field. `lang` is still threaded through every
  client function (see tools.py) for interface consistency, but it has
  no effect on any returned value.
- `tag_list` and `group_list` both return real, populated results here
  (151 tags, 15 groups) -- the opposite of the federal portal, where
  both are confirmed empty. `group_list`/`tag_list` support
  `all_fields=true`, returning full objects (id/name/title/description/
  package_count for groups; id/name/vocabulary_id for tags) rather than
  the plain name strings CKAN's Action API docs show as the default
  shape.
- `organization_show`'s `image_url` field is a bare uploaded filename,
  not a usable URL (confirmed live) -- the clickable, absolute URL is in
  the separate `image_display_url` field. `_organization_detail_from_json`
  reads `image_display_url`, not `image_url`, for OrganizationDetail.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_nt import constants
from maple_data_mcp.modules.ckan_nt.schemas import (
    GroupList,
    GroupRef,
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
    source="ckan-nt",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj["name"],
        description=obj.get("description") or None,
        format=obj.get("format") or None,
        url=obj["url"],
        size=obj.get("size"),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype"),
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _group_ref_from_json(obj: dict[str, Any]) -> GroupRef:
    return GroupRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any]) -> PackageSummary:
    org = obj.get("organization") or {}
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    return PackageSummary(
        id=obj["id"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=excerpt(obj.get("notes") or "", constants.NOTES_EXCERPT_LENGTH),
        topic=obj.get("topic") or None,
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resource_formats=formats,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
    )


def _package_detail_from_json(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    tags = [t["name"] for t in list_or_empty(obj, "tags")]
    groups = [_group_ref_from_json(g) for g in list_or_empty(obj, "groups")]
    return PackageDetail(
        id=obj["id"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(org) if (org := obj.get("organization")) else None,
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        is_open=to_bool(obj.get("isopen")),
        tags=tags,
        groups=groups,
        topic=obj.get("topic") or None,
        update_frequency=obj.get("update_frequency") or None,
        source=obj.get("source") or None,
        geographic_range=obj.get("geographic_range") or None,
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_nt.PackageDetail",
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
    live that `package_search` with no `q` (or `q=""`) and only `fq` set
    returns the same total count (341) as `package_list`'s own length.
    `lang` is accepted for interface consistency but has no effect (see
    the module docstring).
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

    cache_key = f"ckan-nt:package_search:{query}:{fq}:{rows}:{start}:{sort}"

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
            source="ckan-nt",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_nt.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-nt:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`."""
    cache_key = "ckan-nt:organization_list:all_fields"

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
            source="ckan-nt",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_nt.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-nt:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false so this stays compact -- full
        # dataset listing for an org goes through
        # search_datasets(fq="organization:<name>") instead, matching
        # ckan_federal's convention.
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
        # image_display_url, not image_url -- see module docstring.
        image_url=obj.get("image_display_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_nt.OrganizationDetail",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List every topic group via `group_list(all_fields=True)`.

    Confirmed live: this portal's 15 groups are real, populated topic
    categories (e.g. "Home and Community", 82 datasets), unlike the
    federal portal, which has none -- see module/schemas docstrings.
    """
    cache_key = "ckan-nt:group_list:all_fields"

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
            landing_page_url=f"{constants.GROUP_LANDING_URL}{g['name']}",
        )
        for g in groups_raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}group_list",
            cached=was_cached,
            schema_name="ckan_nt.GroupList",
            freshness="topic-group roster changes infrequently; cached 24h",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    """List the full tag vocabulary via `tag_list` (151 live tags, confirmed).

    Confirmed live: this portal's tags are real and populated, unlike
    the federal portal, which has none -- see module/schemas docstrings.
    """
    cache_key = "ckan-nt:tag_list"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    return TagList(
        tags=list(tags_raw),
        total_count=len(tags_raw),
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_nt.TagList",
            freshness="tag vocabulary changes infrequently; cached 24h",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-nt:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_nt.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under.

    Confirmed live: no license record here carries a `title_fra`/`url_fra`
    pair the way the federal portal's do, so `lang` has no effect.
    """
    cache_key = "ckan-nt:license_list"

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
            is_okd_compliant=to_bool(lic.get("is_okd_compliant")),
            is_osi_compliant=to_bool(lic.get("is_osi_compliant")),
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-nt",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_nt.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )
