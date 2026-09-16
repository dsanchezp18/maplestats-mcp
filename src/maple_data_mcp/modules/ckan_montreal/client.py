"""HTTP client for the City of Montreal open-data (CKAN Montreal) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused here the same way ckan_federal/client.py does, since it is CKAN's
own core behavior, not something this deployment customizes. What is
deployment-specific, confirmed live this session:

- `package_show`/`organization_show`/`resource_show` return HTTP 404 with
  `{"success": false, "error": {"__type": "Not Found Error", "message":
  "Indisponible"}}` for an unknown id -- mapped to NotFound by
  shared/ckan.py. Note the French error message ("Indisponible" =
  "Unavailable") -- this deployment's CKAN instance is itself localized
  to French, unlike federal's English error strings.
- `package_search` does NOT reject an unknown `sort` field the way
  federal does -- confirmed live that `sort=bogus_field_zzz` returns
  HTTP 200 with results in the default order, not an error. A
  syntactically malformed `fq` (e.g. unbalanced parentheses) instead
  returns HTTP 409 with `{"error": {"__type": "Search Error", ...}}`
  (confirmed live) rather than federal's HTTP 400 `"Search Query
  Error"`. shared/ckan.py's `_raise_for_status_error` only special-cases
  400/404, so this 409 surfaces as UpstreamError -- still a typed error,
  just not InvalidInput, since the status code this deployment actually
  uses for a malformed query differs from federal's.
- No bilingual `_translated`/`_fra` fields exist anywhere on this
  deployment (confirmed live across a 50-package sample: every record is
  flat `language: "FR"`, and `fq=language:EN` matches 0 of 404 total
  packages) -- so, unlike ckan_federal's client.py, nothing here calls
  `pick_translated`/`pick_translated_list`/`pick_fra`. `lang` is accepted
  on every function for interface consistency with ckan_federal and only
  affects `landing_page_url`'s `{lang}` path segment (both `/en/...` and
  `/fr/...` paths were confirmed live to return HTTP 200; the dataset
  content behind either path is the same French text).
- `tag_list` and `group_list` are both genuinely populated here (1,174
  tags, 12 groups, confirmed live) -- the opposite of federal, which
  confirmed both empty. `list_tags`/`list_groups` client functions and
  tools exist here as a direct result.
- An organization's raw `image_url` field is a bare uploaded filename,
  not a usable link (confirmed live) -- `image_display_url` is the
  actual resolved URL. `_organization_detail_from_json` reads
  `image_display_url`, not `image_url`, despite the field name match
  with ckan_federal's (unrelated) `image_url` field.
- `name` (URL slug) and `id` (UUID) are NOT always equal here (confirmed
  live), unlike federal where they were confirmed equal -- `dataset_id`
  accepts either, since CKAN's `package_show` itself resolves both, but
  this client always surfaces both fields separately rather than
  assuming one implies the other.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_montreal import constants
from maple_data_mcp.modules.ckan_montreal.schemas import (
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
    source="ckan-montreal",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _tag_names(obj: dict[str, Any]) -> list[str]:
    """Tag objects embedded in a package carry id/name/display_name/state
    -- only `name` is kept here, matching how `tag_list` itself returns
    plain names (see list_tags), not full objects."""
    return [t["name"] for t in list_or_empty(obj, "tags") if t.get("name")]


def _group_names(obj: dict[str, Any]) -> list[str]:
    return [g["name"] for g in list_or_empty(obj, "groups") if g.get("name")]


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj["name"],
        description=obj.get("description") or None,
        format=obj.get("format") or None,
        resource_type=obj.get("resource_type") or None,
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
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    return PackageSummary(
        id=obj["id"],
        name=obj["name"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=excerpt(obj.get("notes") or "", constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        is_open=to_bool(obj.get("isopen")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resource_formats=formats,
        tags=_tag_names(obj),
        update_frequency=obj.get("update_frequency") or None,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['name']}",
    )


def _package_detail_from_json(obj: dict[str, Any], lang: str, *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    return PackageDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(org) if (org := obj.get("organization")) else None,
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        is_open=to_bool(obj.get("isopen")),
        tags=_tag_names(obj),
        groups=_group_names(obj),
        update_frequency=obj.get("update_frequency") or None,
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['name']}",
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_montreal.PackageDetail",
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
    live that `package_search` with no `q` (or `q=""`) returns a stable
    `count` (404) across repeated calls, the whole catalogue. `lang` has
    no effect on result content (see module docstring); it is accepted
    only for interface consistency with ckan_federal.
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

    cache_key = f"ckan-montreal:package_search:{query}:{fq}:{rows}:{start}:{sort}"

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
            source="ckan-montreal",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_montreal.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-montreal:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, lang, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`.

    Only 6 total, confirmed live -- a small municipal roster, not
    federal's ~350. `lang` has no effect (see module docstring).
    """
    cache_key = "ckan-montreal:organization_list:all_fields"

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
            description_excerpt=(
                excerpt(o["description"], constants.DESCRIPTION_EXCERPT_LENGTH)
                if o.get("description")
                else None
            ),
            package_count=get_or(o, "package_count", 0),
        )
        for o in orgs_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_montreal.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-montreal:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false (confirmed live: absent
        # already omits `packages`) so this stays compact -- full
        # dataset listing for an org goes through
        # search_datasets(fq="organization:<name>") instead.
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
        # image_display_url, not the raw image_url filename -- see
        # module docstring point 4.
        image_url=obj.get("image_display_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL.format(lang=lang)}{obj['name']}",
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_montreal.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-montreal:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_montreal.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    cache_key = "ckan-montreal:license_list"

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
            source="ckan-montreal",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_montreal.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    """List every distinct tag name via `tag_list`.

    Confirmed live: this deployment's default `tag_list` call returns a
    flat list of 1,174 name strings, not objects -- unlike a package's
    embedded `tags` array, which carries full id/name/display_name/state
    objects (see `_tag_names`). `lang` has no effect (see module
    docstring).
    """
    cache_key = "ckan-montreal:tag_list"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    return TagList(
        tags=tags_raw,
        total_count=len(tags_raw),
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_montreal.TagList",
            freshness="tag roster changes infrequently; cached 24h",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List every subject-area group via `group_list(all_fields=True)`.

    Confirmed live: 12 real groups, each with a French title/description
    and a non-trivial package_count -- unlike ckan_federal, which
    confirmed group_list returns `[]` on that portal. `lang` has no
    effect (see module docstring).
    """
    cache_key = "ckan-montreal:group_list:all_fields"

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
            description_excerpt=(
                excerpt(g["description"], constants.DESCRIPTION_EXCERPT_LENGTH)
                if g.get("description")
                else None
            ),
            package_count=get_or(g, "package_count", 0),
        )
        for g in groups_raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="ckan-montreal",
            url=f"{constants.BASE_URL}group_list",
            cached=was_cached,
            schema_name="ckan_montreal.GroupList",
            freshness="group roster changes infrequently; cached 24h",
        ),
    )
