"""HTTP client for the City of Toronto Open Data (CKAN Toronto) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused here the same way ckan_federal/client.py does since it is
CKAN's own core behavior, not something this deployment customizes.
What is deployment-specific, confirmed live this session:

- `package_show`/`organization_show`/`resource_show` return HTTP 404
  for an unknown id, but -- unlike the federal portal -- the body is a
  plain HTML "403/404 Error" page, not a CKAN JSON error envelope
  (confirmed live). shared/ckan.py's `_error_detail` already falls
  back to the raw response text when the body doesn't parse as JSON,
  so this still raises NotFound correctly; the detail message is just
  less informative than on the federal portal.
- `package_search` returns HTTP 400 with a proper CKAN JSON error body
  (`{"error": {"__type": "Search Query Error", ...}}`) for a malformed
  `sort` value -- same shape as federal, mapped to InvalidInput by
  shared/ckan.py.
- `lang` has no effect anywhere: confirmed live across 50 sampled
  packages, the organization record, and every resource that no
  `_translated`/`_fra`-suffixed field exists on this deployment at
  all. Unlike the federal portal (which has the bilingual extension
  installed but ignores the `lang` query param), this portal simply
  has no French content to select between.
- `tag_list` returns a populated, real vocabulary (909 tags live) and
  sampled packages carry populated `tags` arrays -- this portal DOES
  use CKAN tags, unlike federal. `group_list` returns `[]` live and
  every sampled package's `groups` array is empty -- this portal does
  NOT use CKAN groups. See schemas.py's module docstring.
- A package's `id` (UUID) and `name` (slug) are genuinely different
  values here (confirmed live), unlike the federal portal where they
  are identical. Both resolve correctly against `package_show` and
  against the open.toronto.ca landing page (confirmed live for both),
  so either is accepted as `dataset_id`.
- `license_list` returns the CKAN stock license register, with
  `domain_content`/`domain_data`/`domain_software`/`is_generic` as the
  JSON strings "True"/"False" (confirmed live) -- `_to_bool` below
  coerces these before constructing LicenseInfo, rather than modelling
  them as `str` and pushing the parsing burden onto callers.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_toronto import constants
from maple_data_mcp.modules.ckan_toronto.schemas import (
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
from maple_data_mcp.shared.ckan import CkanConfig, action, excerpt, parse_dt
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import list_or_empty

CONFIG = CkanConfig(
    source="ckan-toronto",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _to_bool(value: object) -> bool:
    """Coerce license_list's "True"/"False" JSON strings to bool.

    Confirmed live: domain_content/domain_data/domain_software/
    is_generic on this deployment's license_list are strings, not
    JSON booleans, unlike everywhere else in this API that uses real
    booleans (e.g. package `isopen`, resource `datastore_active`).
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _tag_names(tags: list[dict[str, Any]]) -> list[str]:
    """Flatten package_search/package_show's tag-dict list to plain names."""
    return [t["name"] for t in tags if t.get("name")]


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj.get("name") or obj["id"],
        format=obj.get("format") or None,
        url=obj["url"],
        size=obj.get("size"),
        datastore_active=bool(obj.get("datastore_active")),
        record_count=obj.get("record_count"),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype"),
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any]) -> PackageSummary:
    org = obj.get("organization") or {}
    excerpt_text = excerpt(
        obj.get("excerpt") or obj.get("notes") or "", constants.EXCERPT_MAX_LENGTH
    )
    return PackageSummary(
        id=obj["id"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        excerpt=excerpt_text,
        dataset_category=obj.get("dataset_category") or None,
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        is_retired=bool(obj.get("is_retired")),
        num_resources=obj.get("num_resources", len(list_or_empty(obj, "resources"))),
        formats=list_or_empty(obj, "formats"),
        tags=_tag_names(list_or_empty(obj, "tags")),
        topics=list_or_empty(obj, "topics"),
        refresh_rate=obj.get("refresh_rate") or None,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}/",
    )


def _package_detail_from_json(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    return PackageDetail(
        id=obj["id"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        excerpt=excerpt(obj.get("excerpt") or "", constants.EXCERPT_MAX_LENGTH),
        organization=_organization_ref_from_json(obj["organization"]),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        dataset_category=obj.get("dataset_category") or None,
        is_retired=bool(obj.get("is_retired")),
        information_url=obj.get("information_url") or None,
        limitations=obj.get("limitations") or None,
        civic_issues=list_or_empty(obj, "civic_issues"),
        tags=_tag_names(list_or_empty(obj, "tags")),
        topics=list_or_empty(obj, "topics"),
        refresh_rate=obj.get("refresh_rate") or None,
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=obj.get("num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}/",
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_toronto.PackageDetail",
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

    `lang` is accepted for interface consistency with every other
    module's tools but has no effect -- see this module's docstring.
    An empty `query` is a deliberate match-all, matching package_list's
    total count (confirmed live: q="" with rows=999999 returned all
    557 catalogue entries).
    """
    del lang  # confirmed no effect on this deployment; see module docstring
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    cache_key = f"ckan-toronto:package_search:{query}:{fq}:{rows}:{start}:{sort}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_search", params=params)

    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)

    raw_results = list_or_empty(result, "results")
    total_count = result.get("count", len(raw_results))
    packages = [_package_summary_from_json(obj) for obj in raw_results]
    return PackageSearchResult(
        packages=packages,
        total_count=total_count,
        returned_count=len(packages),
        start=start,
        rows=rows,
        query=query,
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_toronto.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    """`dataset_id` accepts either the package's UUID `id` or its slug
    `name` -- confirmed live both resolve to the same record on this
    deployment (unlike federal, where id and name are identical
    strings to begin with)."""
    del lang  # confirmed no effect on this deployment; see module docstring
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-toronto:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`.

    Confirmed live this portal has exactly one organization
    (city-of-toronto) -- see schemas.py's OrganizationList docstring.
    `lang` has no effect; see this module's docstring.
    """
    del lang  # confirmed no effect on this deployment; see module docstring
    cache_key = "ckan-toronto:organization_list:all_fields"

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
            package_count=o.get("package_count", 0),
        )
        for o in orgs_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_toronto.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
            coverage="this portal publishes through a single organization (city-of-toronto)",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    del lang  # confirmed no effect on this deployment; see module docstring
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-toronto:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false, matching ckan_federal's
        # convention -- full dataset listing for the organization goes
        # through search_datasets(fq="organization:<name>") instead.
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
        package_count=obj.get("package_count", 0),
        image_url=obj.get("image_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_toronto.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    del lang  # confirmed no effect on this deployment; see module docstring
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-toronto:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_toronto.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    del lang  # confirmed no effect on this deployment; see module docstring
    cache_key = "ckan-toronto:license_list"

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
            domain_content=_to_bool(lic.get("domain_content")),
            domain_data=_to_bool(lic.get("domain_data")),
            domain_software=_to_bool(lic.get("domain_software")),
            is_generic=_to_bool(lic.get("is_generic")),
            od_conformance=lic.get("od_conformance") or None,
            osd_conformance=lic.get("osd_conformance") or None,
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_toronto.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    """List every tag in this portal's vocabulary via `tag_list`.

    Confirmed live this returns a plain list of tag-name strings (not
    the `all_fields=True` dict form) -- see schemas.py's TagList
    docstring. `lang` has no effect; see this module's docstring.
    """
    del lang  # confirmed no effect on this deployment; see module docstring
    cache_key = "ckan-toronto:tag_list"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list")

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    return TagList(
        tags=list(tags_raw),
        total_count=len(tags_raw),
        provenance=make_provenance(
            source="ckan-toronto",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_toronto.TagList",
            freshness="tag vocabulary changes infrequently; cached 24h",
        ),
    )
