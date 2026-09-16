"""HTTP client for the BC Data Catalogue (CKAN BC) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused by every modules/ckan_<portal>/ in this codebase since it is
CKAN's own core behavior, not something this deployment customizes.
What is deployment-specific, confirmed live this session -- and where
it genuinely differs from modules/ckan_federal/client.py's own
confirmed findings:

- `package_show`/`organization_show`/`resource_show` return HTTP 404
  with `{"success": false, "error": {"__type": "Not Found Error", ...}}`
  for an unknown id, and `package_search` returns HTTP 400 with
  `{"error": {"__type": "Search Query Error", ...}}` for a malformed
  `sort` value -- the same shapes confirmed on ckan_federal, mapped by
  shared/ckan.py to NotFound/InvalidInput respectively.
- Unlike ckan_federal, no `_translated` dict or `_fra`-suffixed field
  was found anywhere (checked package_show, organization_show,
  license_list) -- this portal is English-only. `lang` is still
  accepted by every function here for interface consistency, but is
  never actually used to pick between values (see schemas.py's module
  docstring).
- Unlike ckan_federal, this portal DOES use CKAN tags and groups:
  tag_list returns ~7,087 real entries and group_list returns 26 real
  curated thematic collections, and sampled packages carry populated
  `tags`/`groups` arrays -- confirmed live. list_tags/list_groups/
  get_group exist here specifically because federal's reason for
  omitting them (empty tag_list/group_list) does not hold on this
  portal.
- `group_list(all_fields=True)` returns HTTP 403 with
  `{"success": false, "error": {"__type": "Authorization Error",
  "message": "Access denied"}}` for an anonymous request -- confirmed
  live. `organization_list(all_fields=True)` has no such restriction on
  this same portal. list_groups() below works around this by reading
  `package_search`'s `groups` facet instead (also confirmed live,
  public), rather than calling group_list at all.
- An organization's/group's `image_url` field is a bare uploaded
  filename fragment (e.g.
  "2018-10-26-000525.036919bc-stats-gov-wordmark.png"), not a usable
  URL -- confirmed live. `image_display_url` is the real absolute URL;
  get_organization/get_group below populate their `image_url` output
  field from `image_display_url`, not the raw `image_url` field.
- Several resource fields (`mimetype`, `mimetype_inner`, `cache_url`,
  `url_type`) are sometimes the literal JSON string "null" rather than
  a real null, confirmed live via resource_show -- see `_clean_str`.
  `datastore_active` is inconsistently typed across sibling resources
  of the same package (a real JSON boolean on some, the string "false"
  on others) -- also confirmed live; left as a plain `bool` field since
  Pydantic's lax validation coerces both without extra handling.
- CKAN's package_search hard cap of 1000 rows (confirmed live: rows=5000
  returns exactly 1000 results) matches ckan_federal exactly.
- `package_show`/`organization_show` accept either the record's `id`
  (UUID) or its `name` (slug) interchangeably -- confirmed live, same
  as ckan_federal.
- `organization_list(all_fields=True)` is silently capped at exactly 25
  results on this deployment, regardless of a `limit`/`rows` parameter
  -- confirmed live, unlike ckan_federal where it returns the full
  roster uncapped. `group_list(all_fields=True)` needs authentication
  (see above) -- a second, different restriction on the same style of
  call. Both list_organizations() and list_groups() below route around
  their respective restriction via package_search's facets instead.
- Some long-text fields (confirmed live on at least one group's
  `description`) contain the Unicode replacement character (U+FFFD)
  in place of what reads like a curly quote, even though every
  response's Content-Type header states `charset=utf-8` -- this is
  corrupted source data on the portal's own end (most likely a
  mis-encoded curly quote baked in upstream), not a decoding error in
  `shared/http.py`; passed through as-is rather than guessed-and-fixed.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_bc import constants
from maple_data_mcp.modules.ckan_bc.schemas import (
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
    TagInfo,
    TagList,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.ckan import CkanConfig, action, excerpt, parse_dt
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import list_or_empty

CONFIG = CkanConfig(
    source="ckan-bc",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _clean_str(value: Any) -> str | None:
    """Normalize this portal's "null"-as-a-literal-string quirk to None.

    Confirmed live on resource_show's `mimetype`/`mimetype_inner`/
    `cache_url`/`url_type` fields: some resources carry the literal
    JSON string "null" instead of a real null or an absent key. An
    ordinary empty string is folded in too, matching ckan_federal's
    existing empty-string-to-None normalization for resource
    description.
    """
    if value is None or value == "" or value == "null":
        return None
    return value


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj.get("name") or obj["id"],
        description=_clean_str(obj.get("description")),
        format=_clean_str(obj.get("format")),
        url=_clean_str(obj.get("url")),
        size=obj.get("size"),
        resource_type=_clean_str(obj.get("resource_type")),
        resource_storage_location=_clean_str(obj.get("resource_storage_location")),
        object_name=_clean_str(obj.get("object_name")),
        # NOT bool(...): Python's bool("false") is True for any non-empty
        # string, which would silently invert this portal's string-typed
        # "false" values (see module docstring). Passing the raw value
        # through lets Pydantic's own lax bool validator interpret the
        # string's actual content instead of Python truthiness.
        datastore_active=obj.get("datastore_active") or False,
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=_clean_str(obj.get("mimetype")),
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any]) -> PackageSummary:
    org = obj.get("organization") or {}
    notes = obj.get("notes") or ""
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    return PackageSummary(
        id=obj["id"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=excerpt(notes, constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        num_resources=obj.get("num_resources", len(resources)),
        resource_formats=formats,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
    )


def _package_detail_from_json(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    tags = [t["name"] for t in list_or_empty(obj, "tags")]
    groups = [g["name"] for g in list_or_empty(obj, "groups")]
    return PackageDetail(
        id=obj["id"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(obj["organization"]),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        tags=tags,
        groups=groups,
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=obj.get("num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_bc.PackageDetail",
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
    live the same way as ckan_federal: no `q` (or `q=""`) with only `fq`
    set returns the same total count as CKAN's documented `q=*:*` idiom.
    `lang` is accepted for interface consistency but has no effect --
    this portal is English-only (see schemas.py's module docstring).
    """
    del lang  # English-only portal; kept for tool-signature consistency.
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    cache_key = f"ckan-bc:package_search:{query}:{fq}:{rows}:{start}:{sort}"

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
            source="ckan-bc",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_bc.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    del lang  # English-only portal; kept for tool-signature consistency.
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-bc:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every organization with at least one published dataset, with
    live dataset counts.

    Built from `package_search`'s `organization` facet, not
    `organization_list(all_fields=True)` -- confirmed live that, on this
    deployment specifically, `organization_list(all_fields=True)` is
    silently capped at exactly 25 results regardless of a `limit`/`rows`
    parameter (see constants.py's ORGANIZATION_FACET_LIMIT comment for
    what was tried). `lang` has no effect -- this portal is English-only
    (see schemas.py's module docstring).
    """
    del lang
    cache_key = "ckan-bc:package_search:organization_facet"

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG,
            "package_search",
            params={
                "rows": 0,
                "facet.field": '["organization"]',
                "facet.limit": constants.ORGANIZATION_FACET_LIMIT,
            },
        )

    result, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_ORGANIZATION_LIST_SECONDS, fetch
    )
    facet = (result.get("search_facets") or {}).get("organization") or {}
    items = facet.get("items") or []
    organizations = [
        OrganizationSummary(
            name=item["name"],
            title=item.get("display_name") or item["name"],
            package_count=item.get("count", 0),
        )
        for item in items
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}package_search?rows=0&facet.field=%5B%22organization%22%5D",
            cached=was_cached,
            schema_name="ckan_bc.OrganizationList",
            coverage="only organizations with at least one dataset attached are included",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    """Get detail for one publishing organization.

    `lang` has no effect -- this portal is English-only (see schemas.py's
    module docstring). `include_users=false`/`include_datasets=false` are
    passed explicitly (confirmed live: both are honored and trim staff
    contact info and the full dataset list out of the response) since
    neither is used by this function's output.
    """
    del lang
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-bc:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG,
            "organization_show",
            params={"id": organization_id, "include_datasets": "false", "include_users": "false"},
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ORGANIZATION_SECONDS, fetch)
    return OrganizationDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj.get("title") or obj["name"],
        description=_clean_str(obj.get("description")),
        package_count=obj.get("package_count", 0),
        # image_display_url, not the raw image_url (a bare filename
        # fragment on this portal, confirmed live) -- see module docstring.
        image_url=_clean_str(obj.get("image_display_url")),
        website_url=_clean_str(obj.get("url")),
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_bc.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    del lang  # English-only portal; kept for tool-signature consistency.
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-bc:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_bc.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under.

    `lang` has no effect -- confirmed live this portal's license_list
    has no `title_fra`/`_translated` counterpart at all, unlike
    ckan_federal's (see schemas.py's module docstring).
    """
    del lang
    cache_key = "ckan-bc:license_list"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "license_list")

    licenses_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_LICENSE_LIST_SECONDS, fetch
    )
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=lic["title"],
            url=_clean_str(lic.get("url")),
            status=lic.get("status", "unknown"),
            is_open=bool(lic.get("is_open")),
            is_okd_compliant=bool(lic.get("is_okd_compliant")),
            is_osi_compliant=bool(lic.get("is_osi_compliant")),
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_bc.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(query: str | None = None, lang: str = "en") -> TagList:
    """List/search this portal's tag vocabulary via `tag_list(all_fields=True)`.

    Confirmed live: tag_list has no server-side rows/limit parameter, so
    an unfiltered call returns the full ~7,087-tag vocabulary in one
    response -- capped client-side at TAG_LIST_MAX when `query` is not
    given. `query` is tag_list's own substring-match parameter
    (confirmed live), the intended way to search a specific term rather
    than paging through the capped full list. `lang` has no effect --
    this portal is English-only (see schemas.py's module docstring).
    """
    del lang
    cache_key = f"ckan-bc:tag_list:{query}"

    async def fetch() -> list[dict[str, Any]]:
        params: dict[str, Any] = {"all_fields": "true"}
        if query:
            params["query"] = query
        return await action(CONFIG, "tag_list", params=params)

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )
    total_count = len(tags_raw)
    truncated = query is None and total_count > constants.TAG_LIST_MAX
    display_raw = tags_raw[: constants.TAG_LIST_MAX] if truncated else tags_raw
    tags = [
        TagInfo(id=t["id"], name=t["name"], display_name=t.get("display_name") or t["name"])
        for t in display_raw
    ]
    return TagList(
        tags=tags,
        total_count=total_count,
        query=query,
        truncated=truncated,
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_bc.TagList",
            limits=(
                f"unfiltered tag list capped at {constants.TAG_LIST_MAX} of {total_count} tags; "
                "pass `query` to search a specific term"
                if truncated
                else None
            ),
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List this portal's curated thematic groups, with live dataset counts.

    Built from `package_search`'s `groups` facet, not `group_list` --
    `group_list(all_fields=True)` returns HTTP 403 for an anonymous
    request on this deployment (confirmed live, see module docstring),
    while the facet path is public. Only groups with at least one
    dataset attached appear, since a facet count is computed from search
    matches. `lang` has no effect -- this portal is English-only (see
    schemas.py's module docstring).
    """
    del lang
    cache_key = "ckan-bc:package_search:groups_facet"

    async def fetch() -> dict[str, Any]:
        return await action(
            CONFIG,
            "package_search",
            params={
                "rows": 0,
                "facet.field": '["groups"]',
                "facet.limit": constants.GROUP_FACET_LIMIT,
            },
        )

    result, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_GROUP_LIST_SECONDS, fetch
    )
    facet = (result.get("search_facets") or {}).get("groups") or {}
    items = facet.get("items") or []
    groups = [
        GroupSummary(
            name=item["name"],
            title=item.get("display_name") or item["name"],
            dataset_count=item.get("count", 0),
            landing_page_url=f"{constants.GROUP_LANDING_URL}{item['name']}",
        )
        for item in items
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}package_search?rows=0&facet.field=%5B%22groups%22%5D",
            cached=was_cached,
            schema_name="ckan_bc.GroupList",
            coverage="only groups with at least one dataset attached are included",
            freshness="group roster changes infrequently; cached 24h",
        ),
    )


async def get_group(group_id: str, lang: str = "en") -> GroupDetail:
    """Get detail for one curated thematic group.

    `lang` has no effect -- this portal is English-only (see schemas.py's
    module docstring). `include_users=false` is passed explicitly
    (confirmed live: honored, trims a staff-name/email list out of the
    response) since it is not used by this function's output.
    """
    del lang
    if not group_id.strip():
        raise InvalidInput("group_id must not be empty.")
    cache_key = f"ckan-bc:group_show:{group_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "group_show", params={"id": group_id, "include_users": "false"})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_GROUP_SECONDS, fetch)
    return GroupDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj.get("title") or obj["name"],
        description=_clean_str(obj.get("description")),
        package_count=obj.get("package_count", 0),
        # image_display_url, not the raw image_url (a bare filename
        # fragment on this portal, confirmed live) -- see module docstring.
        image_url=_clean_str(obj.get("image_display_url")),
        landing_page_url=f"{constants.GROUP_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-bc",
            url=f"{constants.BASE_URL}group_show?id={group_id}",
            cached=was_cached,
            schema_name="ckan_bc.GroupDetail",
        ),
    )
