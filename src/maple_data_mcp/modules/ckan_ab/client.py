"""HTTP client for Open Alberta's CKAN Action API.

The portal follows the standard CKAN envelope but has Alberta-specific
field names such as ``updatefrequency`` and ``subject1``-style fields.
Those names are mapped here after checking live package, resource,
organization, tag, and license responses.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_ab import constants
from maple_data_mcp.modules.ckan_ab.schemas import (
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


def _strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


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


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj.get("name") or obj.get("resource_name") or obj["id"],
        description=obj.get("description") or None,
        format=obj.get("format") or None,
        url=obj.get("url") or "",
        size=obj.get("size"),
        datastore_active=to_bool(obj.get("datastore_active"))
        if obj.get("datastore_active") is not None
        else None,
        resource_type=obj.get("resource_type") or None,
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype") or None,
    )


def _organization_ref(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary(obj: dict[str, Any]) -> PackageSummary:
    organization = obj.get("organization") or {}
    resources = list_or_empty(obj, "resources")
    return PackageSummary(
        id=obj["id"],
        title=obj.get("title") or obj["name"],
        organization_name=organization.get("name"),
        organization_title=organization.get("title"),
        notes_excerpt=excerpt(obj.get("notes") or "", constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        is_open=to_bool(obj.get("isopen")),
        tags=_names(obj, "tags"),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resource_formats=sorted({r["format"] for r in resources if r.get("format")}),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
    )


def _package_detail(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    subjects = []
    for key in ("subject", "subject1", "subject2", "subject3", "subject4", "subject5", "subject6"):
        subjects.extend(_strings(obj.get(key)))
    return PackageDetail(
        id=obj["id"],
        title=obj.get("title") or obj["name"],
        notes=obj.get("notes") or "",
        organization=_organization_ref(obj["organization"]) if obj.get("organization") else None,
        creator=_strings(obj.get("creator")),
        contact=obj.get("contact") or None,
        contact_email=obj.get("contact_email") or obj.get("email") or None,
        date_created=parse_dt(obj.get("createdate") or obj.get("date_created")),
        date_issued=parse_dt(obj.get("issuedate") or obj.get("date_issued")),
        update_frequency=obj.get("updatefrequency") or obj.get("update_frequency") or None,
        is_open=to_bool(obj.get("isopen")),
        language=_strings(obj.get("language")),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url") or None,
        tags=_names(obj, "tags"),
        subjects=subjects,
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource_from_json(resource) for resource in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_ab.PackageDetail",
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
    """Search Open Alberta's datasets; ``lang`` is accepted for consistency."""
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

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_search", params=params)

    cache_key = f"ckan-ab:package_search:{query}:{fq}:{rows}:{start}:{sort}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "count", len(raw_results))
    packages = [_package_summary(obj) for obj in raw_results]
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
            schema_name="ckan_ab.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(
        f"ckan-ab:package_show:{dataset_id}", constants.CACHE_TTL_PACKAGE_SECONDS, fetch
    )
    return _package_detail(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    del lang

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "organization_list", params={"all_fields": "true"})

    organizations_raw, was_cached = await cached_fetch(
        "ckan-ab:organization_list", constants.CACHE_TTL_ORGANIZATION_LIST_SECONDS, fetch
    )
    organizations = [
        OrganizationSummary(
            id=o["id"],
            name=o["name"],
            title=o.get("title") or o.get("display_name") or o["name"],
            package_count=get_or(o, "package_count", 0),
        )
        for o in organizations_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_ab.OrganizationList",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    del lang
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG,
            "organization_show",
            params={"id": organization_id, "include_datasets": "false"},
        )

    obj, was_cached = await cached_fetch(
        f"ckan-ab:organization_show:{organization_id}",
        constants.CACHE_TTL_ORGANIZATION_SECONDS,
        fetch,
    )
    image_url = obj.get("image_display_url") or obj.get("image_url")
    return OrganizationDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj.get("title") or obj.get("display_name") or obj["name"],
        description=obj.get("description") or None,
        package_count=get_or(obj, "package_count", 0),
        image_url=image_url
        if isinstance(image_url, str) and image_url.startswith("http")
        else None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_ab.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    del lang
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(
        f"ckan-ab:resource_show:{resource_id}", constants.CACHE_TTL_RESOURCE_SECONDS, fetch
    )
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_ab.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    del lang

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "license_list")

    raw, was_cached = await cached_fetch(
        "ckan-ab:license_list", constants.CACHE_TTL_LICENSE_LIST_SECONDS, fetch
    )
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=lic.get("title") or lic["id"],
            url=lic.get("url") or None,
            status=lic.get("status", "unknown"),
            family=lic.get("family") or None,
            maintainer=lic.get("maintainer") or None,
            domain_content=to_bool(lic.get("domain_content")),
            domain_data=to_bool(lic.get("domain_data")),
            domain_software=to_bool(lic.get("domain_software")),
            od_conformance=lic.get("od_conformance"),
            osd_conformance=lic.get("osd_conformance"),
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
            schema_name="ckan_ab.LicenseList",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    del lang

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    raw, was_cached = await cached_fetch(
        "ckan-ab:tag_list", constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    tags = [str(tag) for tag in raw]
    truncated = len(tags) > constants.TAG_LIST_MAX
    tags = tags[: constants.TAG_LIST_MAX]
    return TagList(
        tags=tags,
        total_count=len(raw),
        truncated=truncated,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_ab.TagList",
            limits=f"unfiltered tags capped at {constants.TAG_LIST_MAX} in the response",
        ),
    )
