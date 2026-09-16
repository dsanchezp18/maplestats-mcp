"""HTTP client for the Quebec Open Data (CKAN QC) API.

The HTTP/rate-limit/error/envelope plumbing lives in shared/ckan.py,
reused here the same way ckan_federal/client.py reuses it. What is
deployment-specific, confirmed live this session against
https://www.donneesquebec.ca/recherche/api/3/action/...:

- `package_show`/`organization_show`/`resource_show` return HTTP 404
  with `{"success": false, "error": {"__type": "Not Found Error",
  "message": "Introuvable"}}` for an unknown id -- the same shape
  ckan_federal confirmed (French `message` text instead of English, but
  shared/ckan.py's error mapping only inspects `status`/`__type`, not
  the message text, so this needs no special handling here).
- `package_search` returns HTTP 400 with
  `{"error": {"__type": "Search Query Error", ...}}` for a malformed
  `sort` value -- mapped to InvalidInput, same as ckan_federal.
- This portal has NO bilingual-extension infrastructure: no sampled
  package/organization/resource record anywhere carries a
  `<field>_translated` dict or an `_fra`-suffixed field (confirmed
  live). `language` is a flat, single-value field on each package, and
  a live facet check found only "FR" (1,601 of 1,610 datasets) and
  "FR_EN" (9) as its values -- "FR_EN" describes a dataset's own
  content, not a second language's worth of translated metadata for
  it. Every function below still accepts `lang` for interface
  consistency with every other CKAN module in this codebase, but it is
  a documented no-op: the same (French) content is returned regardless
  of `lang`. shared/ckan.py's `pick_translated`/`pick_translated_list`/
  `pick_fra` are deliberately not imported here as a result -- there is
  nothing on this deployment for them to pick between.
- `tag_list` and `group_list` both return real, populated data here --
  unlike ckan_federal, where both are confirmed empty. `tag_list`
  (4,402 entries, unfiltered) is free-text and uncontrolled (publishers
  type their own casing/spelling); `group_list(all_fields=true)`
  (12 entries) is a small, curated, essentially static set of thematic
  categories. See constants.py's TAGS_LIST_MAX for how an unfiltered
  ckan_qc_list_tags call stays compact.
- `organization_list(all_fields=true)` returns the SAME rich shape
  `organization_show` does here (both carry `description` and
  `image_display_url`) -- unlike ckan_federal, where organization_list
  is confirmed thinner than organization_show.
- An organization's/group's real, clickable logo URL is the
  `image_display_url` field, not `image_url` (confirmed live:
  `image_url` is the bare uploaded filename, e.g.
  "2020-11-11-154709.431257AMD.png"). This module's `image_url` model
  field is sourced from `image_display_url` in the raw JSON.
- `spatial_data` is a flat "Oui"/"Non" string (confirmed live, no third
  value seen in a live sample) -- normalized to `has_spatial_data: bool
  | None` by `_parse_oui_non` below; an empty/absent value means the
  field was never filled in, not "no", so it maps to `None`.
- No hard `rows` cap was found: `package_search?rows=5000&q=` returned
  all 1,610 live catalogue datasets with no truncation, unlike
  ckan_federal's confirmed silent truncation to 1000. SEARCH_ROWS_MAX
  still caps requests here for agent-facing compactness, not because
  this server enforces a lower ceiling of its own.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.ckan_qc import constants
from maple_data_mcp.modules.ckan_qc.schemas import (
    GroupInfo,
    GroupList,
    GroupRef,
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
    source="ckan-qc",
    base_url=constants.BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _parse_oui_non(value: str | None) -> bool | None:
    """Normalize this portal's flat "Oui"/"Non" spatial_data field to a
    bool. An empty or absent value means the field was never filled in
    (confirmed: neither "Oui" nor "Non" is the field's default), not a
    negative answer, so it maps to None rather than False."""
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized == "oui":
        return True
    if normalized == "non":
        return False
    return None


def _resource_from_json(obj: dict[str, Any]) -> ResourceInfo:
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=obj["name"],
        description=(obj.get("description") or None),
        format=obj.get("format") or None,
        url=obj["url"],
        size=obj.get("size"),
        resource_type=obj.get("resource_type") or None,
        datastore_active=bool(obj.get("datastore_active")),
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
    notes = obj.get("notes") or ""
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    tags = [t["name"] for t in list_or_empty(obj, "tags") if t.get("name")]
    group_names = [g.get("title") or g["name"] for g in list_or_empty(obj, "groups")]
    return PackageSummary(
        id=obj["id"],
        name=obj["name"],
        title=obj["title"],
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=excerpt(notes, constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        num_resources=obj.get("num_resources", len(resources)),
        resource_formats=formats,
        tags=tags,
        group_names=group_names,
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['name']}",
    )


def _package_detail_from_json(obj: dict[str, Any], *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    tags = [t["name"] for t in list_or_empty(obj, "tags") if t.get("name")]
    groups = [_group_ref_from_json(g) for g in list_or_empty(obj, "groups")]
    return PackageDetail(
        id=obj["id"],
        name=obj["name"],
        title=obj["title"],
        notes=obj.get("notes") or "",
        organization=_organization_ref_from_json(obj["organization"]),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        tags=tags,
        groups=groups,
        language=obj.get("language") or None,
        update_frequency=obj.get("update_frequency") or None,
        has_spatial_data=_parse_oui_non(obj.get("spatial_data")),
        methodology=obj.get("methodologie") or None,
        temporal_coverage=obj.get("temporal") or None,
        is_open=bool(obj.get("isopen")),
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=obj.get("num_resources", len(resources)),
        resources=[_resource_from_json(r) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_qc.PackageDetail",
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

    An empty `query` is a deliberate match-all, not an error -- same
    confirmed behavior as ckan_federal. `lang` has no effect (see this
    module's docstring): this portal has no translated fields to pick
    between.
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

    cache_key = f"ckan-qc:package_search:{query}:{fq}:{rows}:{start}:{sort}"

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
            source="ckan-qc",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_qc.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan-qc:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`.

    Unlike ckan_federal, `all_fields=true` here already returns the
    same `description`/`image_display_url` fields organization_show
    does (confirmed live), so OrganizationSummary carries them too.
    `lang` has no effect (see this module's docstring).
    """
    cache_key = "ckan-qc:organization_list:all_fields"

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
            description=o.get("description") or None,
            package_count=o.get("package_count", 0),
            image_url=o.get("image_display_url") or None,
        )
        for o in orgs_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_qc.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan-qc:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false the same way ckan_federal
        # does -- full dataset listing for an org goes through
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
        package_count=obj.get("package_count", 0),
        image_url=obj.get("image_display_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL}{obj['name']}",
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_qc.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan-qc:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await action(CONFIG, "resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj),
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_qc.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under.

    Confirmed live this deployment's license records differ from
    ckan_federal's: no `is_osi_compliant` field (the analogous flag
    here is `is_ost_compliant`), and both compliance flags are entirely
    absent (not `false`) on some licenses -- left as `None` rather than
    coerced to `False`.
    """
    cache_key = "ckan-qc:license_list"

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
            is_okd_compliant=lic.get("is_okd_compliant"),
            is_ost_compliant=lic.get("is_ost_compliant"),
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_qc.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_groups(lang: str = "en") -> GroupList:
    """List every thematic group via `group_list(all_fields=True)`.

    Confirmed live this portal actually uses groups (12, a small,
    curated, essentially static set of subject categories) -- unlike
    ckan_federal, where group_list is confirmed to return `[]`.
    """
    cache_key = "ckan-qc:group_list:all_fields"

    async def fetch() -> list[dict[str, Any]]:
        return await action(CONFIG, "group_list", params={"all_fields": "true"})

    groups_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_GROUP_LIST_SECONDS, fetch
    )
    groups = [
        GroupInfo(
            id=g["id"],
            name=g["name"],
            title=g.get("title") or g["name"],
            description=g.get("description") or None,
            package_count=g.get("package_count", 0),
            landing_page_url=f"{constants.GROUP_LANDING_URL}{g['name']}",
        )
        for g in groups_raw
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}group_list",
            cached=was_cached,
            schema_name="ckan_qc.GroupList",
            freshness="the group roster is a small, curated set; cached 24h",
        ),
    )


async def list_tags(query: str | None = None, lang: str = "en") -> TagList:
    """List/search the free-text tag namespace via `tag_list`.

    Confirmed live this portal actually uses tags (4,402 entries,
    unfiltered) -- unlike ckan_federal, where tag_list is confirmed to
    return `[]`. The namespace is uncontrolled (publishers type their
    own casing/spelling, confirmed live), so an unfiltered call is
    capped at TAGS_LIST_MAX with `truncated=True`; pass `query` (a
    substring filter, applied server-side via tag_list's own `query`
    parameter, confirmed live) to search it instead.
    """
    params: dict[str, Any] | None = {"query": query} if query else None
    cache_key = f"ckan-qc:tag_list:{query}"

    async def fetch() -> list[str]:
        return await action(CONFIG, "tag_list", params=params)

    tags_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TAG_LIST_SECONDS, fetch
    )

    truncated = False
    tags = tags_raw
    if query is None and len(tags) > constants.TAGS_LIST_MAX:
        tags = tags[: constants.TAGS_LIST_MAX]
        truncated = True

    return TagList(
        tags=tags,
        total_count=len(tags_raw),
        query=query,
        truncated=truncated,
        provenance=make_provenance(
            source="ckan-qc",
            url=f"{constants.BASE_URL}tag_list",
            cached=was_cached,
            schema_name="ckan_qc.TagList",
            limits=(
                f"unfiltered tag list capped at {constants.TAGS_LIST_MAX} of "
                f"{len(tags_raw)} total tags; pass query to search instead"
                if truncated
                else None
            ),
        ),
    )
