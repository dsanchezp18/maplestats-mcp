"""HTTP client for the Ontario Data Catalogue CKAN API.

Ontario returns standard CKAN envelopes but adds bilingual fields and
Ontario-specific metadata such as access level, current-as-of date, and
geographic coverage. The client selects translations locally because the
Action API does not provide a dependable language switch for JSON.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_on import constants
from maple_data_mcp.modules.ckan_on.schemas import (
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
from maple_data_mcp.shared.ckan import (
    CkanConfig,
    action,
    excerpt,
    parse_dt,
    pick_translated,
    pick_translated_list,
    to_bool,
)
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import get_or, list_or_empty

CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _names(obj: dict[str, Any], key: str) -> list[str]:
    values = list_or_empty(obj, key)
    names: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("display_name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _resource_from_json(obj: dict[str, Any], lang: str) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=pick_translated(obj.get("name"), obj.get("name_translated"), lang)
        or obj.get("resource_name")
        or obj["id"],
        description=pick_translated(obj.get("description"), obj.get("description_translated"), lang)
        or None,
        format=obj.get("format") or None,
        url=obj.get("url") or "",
        size=obj.get("size"),
        datastore_active=to_bool(obj.get("datastore_active"))
        if obj.get("datastore_active") is not None
        else None,
        resource_type=obj.get("resource_type") or obj.get("type") or None,
        data_last_updated=parse_dt(obj.get("data_last_updated")),
        data_range_start=parse_dt(obj.get("data_range_start")),
        data_range_end=parse_dt(obj.get("data_range_end")),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype") or None,
    )


def _organization_ref(obj: dict[str, Any], lang: str) -> OrganizationRef:
    return OrganizationRef(
        id=obj["id"],
        name=obj["name"],
        title=pick_translated(obj.get("title"), obj.get("title_translated"), lang) or obj["name"],
    )


def _package_summary(obj: dict[str, Any], lang: str) -> PackageSummary:
    organization = obj.get("organization") or {}
    resources = list_or_empty(obj, "resources")
    return PackageSummary(
        id=obj["id"],
        title=pick_translated(obj.get("title"), obj.get("title_translated"), lang) or obj["id"],
        organization_name=organization.get("name"),
        organization_title=pick_translated(
            organization.get("title"), organization.get("title_translated"), lang
        )
        or organization.get("name"),
        notes_excerpt=excerpt(
            pick_translated(obj.get("notes"), obj.get("notes_translated"), lang),
            constants.NOTES_EXCERPT_LENGTH,
        ),
        license_id=obj.get("license_id"),
        license_title=pick_translated(
            obj.get("license_title"), obj.get("license_title_translated"), lang
        )
        or None,
        is_open=to_bool(obj.get("isopen")),
        tags=[str(tag.get("name")) for tag in list_or_empty(obj, "tags") if isinstance(tag, dict)],
        num_resources=get_or(obj, "num_resources", len(resources)),
        resource_formats=sorted({r["format"] for r in resources if r.get("format")}),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
    )


def _package_detail(obj: dict[str, Any], lang: str, *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    geographic_coverage = pick_translated(
        obj.get("geographic_coverage"), obj.get("geographic_coverage_translated"), lang
    )
    keywords = obj.get("keywords")
    return PackageDetail(
        id=obj["id"],
        title=pick_translated(obj.get("title"), obj.get("title_translated"), lang) or obj["id"],
        notes=pick_translated(obj.get("notes"), obj.get("notes_translated"), lang),
        organization=_organization_ref(obj["organization"], lang)
        if obj.get("organization")
        else None,
        author=obj.get("author") or None,
        maintainer=pick_translated(obj.get("maintainer"), obj.get("maintainer_translated"), lang)
        or None,
        maintainer_email=obj.get("maintainer_email") or None,
        access_level=obj.get("access_level") or None,
        current_as_of=parse_dt(obj.get("current_as_of")),
        geographic_coverage=geographic_coverage or None,
        geographic_granularity=obj.get("geographic_granularity") or None,
        update_frequency=obj.get("update_frequency") or None,
        is_open=to_bool(obj.get("isopen")),
        keywords=pick_translated_list(keywords, lang) if isinstance(keywords, dict) else [],
        license_id=obj.get("license_id"),
        license_title=pick_translated(
            obj.get("license_title"), obj.get("license_title_translated"), lang
        )
        or None,
        license_url=obj.get("license_url") or None,
        tags=[str(tag.get("name")) for tag in list_or_empty(obj, "tags") if isinstance(tag, dict)],
        groups=_names(obj, "groups"),
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(resource, lang) for resource in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_on.PackageDetail",
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
    """Search Ontario datasets and return metadata in the requested language."""
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")
    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_search", params=params)

    cache_key = f"ckan-on:package_search:{query}:{fq}:{rows}:{start}:{sort}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "count", len(raw_results))
    packages = [_package_summary(obj, lang) for obj in raw_results]
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
            schema_name="ckan_on.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(
        f"ckan-on:package_show:{dataset_id}", constants.CACHE_TTL_PACKAGE_SECONDS, fetch
    )
    return _package_detail(obj, lang, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "organization_list", params={"all_fields": "true"})

    raw, was_cached = await cached_fetch(
        "ckan-on:organization_list", constants.CACHE_TTL_ORGANIZATION_LIST_SECONDS, fetch
    )
    organizations = [
        OrganizationSummary(
            id=o["id"],
            name=o["name"],
            title=o.get("title") or o.get("display_name") or o["name"],
            package_count=get_or(o, "package_count", 0),
        )
        for o in raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_on.OrganizationList",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG,
            "organization_show",
            params={"id": organization_id, "include_datasets": "false"},
        )

    obj, was_cached = await cached_fetch(
        f"ckan-on:organization_show:{organization_id}",
        constants.CACHE_TTL_ORGANIZATION_SECONDS,
        fetch,
    )
    title = pick_translated(obj.get("title"), obj.get("title_translated"), lang) or obj["name"]
    image_url = obj.get("image_display_url") or obj.get("image_url")
    return OrganizationDetail(
        id=obj["id"],
        name=obj["name"],
        title=title,
        description=pick_translated(obj.get("description"), obj.get("description_translated"), lang)
        or None,
        package_count=get_or(obj, "package_count", 0),
        image_url=image_url
        if isinstance(image_url, str) and image_url.startswith("http")
        else None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL.format(lang=lang)}{obj['name']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_on.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(
        f"ckan-on:resource_show:{resource_id}", constants.CACHE_TTL_RESOURCE_SECONDS, fetch
    )
    return ResourceDetail(
        resource=_resource_from_json(obj, lang),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_on.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "license_list")

    raw, was_cached = await cached_fetch(
        "ckan-on:license_list", constants.CACHE_TTL_LICENSE_LIST_SECONDS, fetch
    )
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=pick_translated(lic.get("title"), lic.get("title_translated"), lang) or lic["id"],
            url=pick_translated(lic.get("url"), lic.get("url_translated"), lang) or None,
            status=lic.get("status", "unknown"),
            family=lic.get("family") or None,
            maintainer=lic.get("maintainer") or None,
            domain_content=to_bool(lic.get("domain_content")),
            domain_data=to_bool(lic.get("domain_data")),
            domain_software=to_bool(lic.get("domain_software")),
            od_conformance=lic.get("od_conformance"),
            osd_conformance=lic.get("osd_conformance"),
            is_generic=to_bool(lic.get("is_generic")) if "is_generic" in lic else None,
            is_okd_compliant=lic.get("is_okd_compliant"),
            is_osi_compliant=lic.get("is_osi_compliant"),
        )
        for lic in raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_on.LicenseList",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    del lang

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    raw, was_cached = await cached_fetch(
        "ckan-on:tag_list", constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    tags = [str(tag) for tag in raw]
    truncated = len(tags) > constants.TAG_LIST_MAX
    return TagList(
        tags=tags[: constants.TAG_LIST_MAX],
        total_count=len(tags),
        truncated=truncated,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_on.TagList",
            limits=f"unfiltered tags capped at {constants.TAG_LIST_MAX} in the response",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "group_list", params={"all_fields": "true"})

    raw, was_cached = await cached_fetch(
        "ckan-on:group_list", constants.CACHE_TTL_GROUP_LIST_SECONDS, fetch
    )
    groups = [
        GroupSummary(
            id=group["id"],
            name=group["name"],
            title=group.get("title") or group.get("display_name") or group["name"],
            description=group.get("description") or None,
            package_count=get_or(group, "package_count", 0),
            landing_page_url=f"{constants.GROUP_LANDING_URL.format(lang=lang)}{group['name']}",
        )
        for group in raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}group_list",
            cached=was_cached,
            schema_name="ckan_on.GroupList",
        ),
    )
