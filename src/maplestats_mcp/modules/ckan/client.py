"""HTTP client for every CKAN portal in constants.PORTALS.

The Action API envelope, error mapping and bilingual pickers live in
shared/ckan.py. This module turns raw CKAN records into the superset
schemas, applying every portal's documented quirks from constants.py:

- Text fields go through `pick_translated`, which is a no-op on
  portals without `<field>_translated` dicts, so the same code serves
  bilingual (federal, on) and single-language portals.
- Several portals send the literal string "null" or "" for absent
  values (confirmed on BC); `_text` folds both to None everywhere.
- An organization's or group's `image_url` is a bare uploaded filename
  on most portals; `image_display_url` is the real link.
- BC's organization and group rosters come from package_search facets
  because its `organization_list` caps at 25 and `group_list` needs auth.
"""

from __future__ import annotations

import json
from typing import Any

from maplestats_mcp.modules.ckan import constants
from maplestats_mcp.modules.ckan.constants import PORTALS, Portal
from maplestats_mcp.modules.ckan.schemas import (
    DatastoreField,
    DatastoreSearchResult,
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
    PortalInfo,
    PortalList,
    ResourceDetail,
    ResourceInfo,
    TagList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import (
    CkanConfig,
    action,
    excerpt,
    parse_dt,
    pick_fra,
    pick_translated,
    pick_translated_list,
    to_bool,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.json_utils import get_or, list_or_empty


def _portal(key: str) -> Portal:
    portal = PORTALS.get(key)
    if portal is None:
        raise InvalidInput(
            f"Unknown CKAN portal {key!r}. Valid portals: {', '.join(sorted(PORTALS))}."
        )
    return portal


def _config(key: str, portal: Portal) -> CkanConfig:
    return CkanConfig(
        source=f"ckan-{key}",
        base_url=portal.base_url,
        rate_limit_per_second=portal.rate_per_second,
        rate_limit_capacity=portal.rate_capacity,
    )


async def _call(
    key: str, method: str, params: dict[str, Any] | None, ttl: int, cache_suffix: str
) -> tuple[Any, bool]:
    portal = _portal(key)

    async def fetch() -> Any:
        return await action(_config(key, portal), method, params=params)

    return await cached_fetch(f"ckan:{key}:{method}:{cache_suffix}", ttl, fetch)


def _provenance(key: str, path: str, cached: bool, schema: str, **kwargs: Any):
    return make_provenance(
        source=f"ckan-{key}",
        url=f"{PORTALS[key].base_url}{path}",
        cached=cached,
        schema_name=f"ckan.{schema}",
        **kwargs,
    )


def _text(value: Any) -> str | None:
    """Fold CKAN's absent-value spellings (None, "", literal "null") to None."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped in ("", "null") else value
    return str(value)


def _translated(obj: dict[str, Any], key: str, lang: str) -> str | None:
    return _text(pick_translated(obj.get(key), obj.get(f"{key}_translated"), lang))


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _names(obj: dict[str, Any], key: str) -> list[str]:
    """Flatten embedded tag/group objects (or bare strings) to their names."""
    names: list[str] = []
    for item in list_or_empty(obj, key):
        name = (item.get("name") or item.get("display_name")) if isinstance(item, dict) else item
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _extras(obj: dict[str, Any], fields: tuple[str, ...], lang: str) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for name in fields:
        value = obj.get(name)
        translated = obj.get(f"{name}_translated")
        if isinstance(translated, dict) and translated:
            if isinstance(next(iter(translated.values())), list):
                value = pick_translated_list(translated, lang)
            else:
                value = pick_translated(value, translated, lang)
        if isinstance(value, str):
            value = _text(value)
        if value in (None, [], {}):
            continue
        extras[name] = value
    return extras


def _landing(template: str | None, lang: str, ident: str) -> str | None:
    return template.format(lang=lang, id=ident) if template else None


def _dataset_url(portal: Portal, obj: dict[str, Any], lang: str) -> str:
    ident = obj.get("name") if portal.landing_uses_name and obj.get("name") else obj["id"]
    return portal.dataset_url.format(lang=lang, id=ident)


def _image(obj: dict[str, Any]) -> str | None:
    display = _text(obj.get("image_display_url"))
    if display:
        return display
    raw = _text(obj.get("image_url"))
    return raw if raw and raw.startswith("http") else None


def _resource(obj: dict[str, Any], portal: Portal, lang: str) -> ResourceInfo:
    datastore = obj.get("datastore_active")
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=_translated(obj, "name", lang) or _text(obj.get("resource_name")) or obj["id"],
        description=_translated(obj, "description", lang),
        format=_text(obj.get("format")),
        url=_text(obj.get("url")),
        size=_to_int(obj.get("size")),
        resource_type=_text(obj.get("resource_type")) or _text(obj.get("type")),
        language=[str(v) for v in list_or_empty(obj, "language") if v]
        if isinstance(obj.get("language"), list)
        else [],
        datastore_active=None if datastore is None else to_bool(datastore),
        created=parse_dt(obj.get("created")),
        last_modified=parse_dt(obj.get("last_modified")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        mimetype=_text(obj.get("mimetype")),
        extras=_extras(obj, portal.resource_extra_fields, lang),
    )


def _formats(obj: dict[str, Any]) -> list[str]:
    from_resources = {
        fmt for r in list_or_empty(obj, "resources") if (fmt := _text(r.get("format")))
    }
    # Toronto's search results carry a package-level `formats` list instead.
    from_package = {str(f) for f in list_or_empty(obj, "formats") if f}
    return sorted(from_resources | from_package)


def _keywords(obj: dict[str, Any], lang: str) -> list[str]:
    keywords = obj.get("keywords")
    if isinstance(keywords, dict):
        return pick_translated_list(keywords, lang)
    if isinstance(keywords, list):
        return [str(k) for k in keywords if k]
    return []


def _is_open(obj: dict[str, Any]) -> bool | None:
    return None if obj.get("isopen") is None else to_bool(obj.get("isopen"))


def _package_summary(obj: dict[str, Any], portal: Portal, lang: str) -> PackageSummary:
    org = obj.get("organization") or {}
    notes = obj.get("excerpt") or _translated(obj, "notes", lang) or ""
    return PackageSummary(
        id=obj["id"],
        name=obj.get("name"),
        title=_translated(obj, "title", lang) or obj.get("name") or obj["id"],
        organization_name=org.get("name"),
        organization_title=_translated(org, "title", lang) or org.get("name"),
        notes_excerpt=excerpt(notes, constants.NOTES_EXCERPT_LENGTH),
        license_id=obj.get("license_id"),
        license_title=_translated(obj, "license_title", lang),
        is_open=_is_open(obj),
        tags=_names(obj, "tags"),
        groups=_names(obj, "groups"),
        num_resources=get_or(obj, "num_resources", len(list_or_empty(obj, "resources"))),
        resource_formats=_formats(obj),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        landing_page_url=_dataset_url(portal, obj, lang),
    )


def _organization_ref(obj: dict[str, Any], lang: str) -> OrganizationRef:
    return OrganizationRef(
        id=obj["id"], name=obj["name"], title=_translated(obj, "title", lang) or obj["name"]
    )


def list_portals(lang: str = "en") -> PortalList:
    """Every portal key this module accepts, with its capabilities."""
    portals = [
        PortalInfo(
            portal=key,
            name=p.name_fr if lang == "fr" else p.name_en,
            api_url=p.base_url,
            content_language=p.content_language,
            has_tags=p.has_tags,
            has_groups=p.groups != "none",
            has_datastore=p.has_datastore,
            note=(p.note_fr or p.note) if lang == "fr" else p.note,
        )
        for key, p in PORTALS.items()
    ]
    return PortalList(
        portals=portals,
        provenance=make_provenance(
            source="ckan",
            url="(static portal registry in modules/ckan/constants.py)",
            cached=False,
            schema_name="ckan.PortalList",
        ),
    )


async def search_datasets(
    portal: str,
    query: str = "",
    *,
    fq: str | None = None,
    rows: int = constants.SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: str = "en",
) -> PackageSearchResult:
    """`package_search`; an empty `query` deliberately matches everything."""
    info = _portal(portal)
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    result, cached = await _call(
        portal,
        "package_search",
        params,
        constants.CACHE_TTL_SEARCH_SECONDS,
        f"{query}:{fq}:{rows}:{start}:{sort}",
    )
    raw = list_or_empty(result, "results")
    total = get_or(result, "count", len(raw))
    packages = [_package_summary(obj, info, lang) for obj in raw]
    return PackageSearchResult(
        portal=portal,
        packages=packages,
        total_count=total,
        returned_count=len(packages),
        start=start,
        rows=rows,
        query=query,
        provenance=_provenance(
            portal,
            "package_search",
            cached,
            "PackageSearchResult",
            coverage=f"{len(packages)} of {total} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(portal: str, dataset_id: str, lang: str = "en") -> PackageDetail:
    info = _portal(portal)
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    obj, cached = await _call(
        portal,
        "package_show",
        {"id": dataset_id},
        constants.CACHE_TTL_PACKAGE_SECONDS,
        dataset_id,
    )
    resources = list_or_empty(obj, "resources")
    org = obj.get("organization")
    return PackageDetail(
        portal=portal,
        id=obj["id"],
        name=obj.get("name"),
        title=_translated(obj, "title", lang) or obj.get("name") or obj["id"],
        notes=_translated(obj, "notes", lang) or "",
        organization=_organization_ref(org, lang) if org else None,
        license_id=obj.get("license_id"),
        license_title=_translated(obj, "license_title", lang),
        license_url=_text(obj.get("license_url")),
        is_open=_is_open(obj),
        keywords=_keywords(obj, lang),
        tags=_names(obj, "tags"),
        groups=_names(obj, "groups"),
        metadata_created=parse_dt(obj.get("metadata_created")),
        metadata_modified=parse_dt(obj.get("metadata_modified")),
        num_resources=get_or(obj, "num_resources", len(resources)),
        resources=[_resource(r, info, lang) for r in resources],
        extras=_extras(obj, info.extra_fields, lang),
        landing_page_url=_dataset_url(info, obj, lang),
        provenance=_provenance(portal, "package_show", cached, "PackageDetail"),
    )


async def _facet(portal: str, field: str, ttl: int) -> tuple[list[dict[str, Any]], bool]:
    """Roster built from a package_search facet (see BC in constants.py)."""
    result, cached = await _call(
        portal,
        "package_search",
        {"rows": 0, "facet.field": json.dumps([field]), "facet.limit": constants.FACET_LIMIT},
        ttl,
        f"facet:{field}",
    )
    facet = (result.get("search_facets") or {}).get(field) or {}
    return list(facet.get("items") or []), cached


async def list_organizations(portal: str, lang: str = "en") -> OrganizationList:
    info = _portal(portal)
    ttl = constants.CACHE_TTL_ORGANIZATION_SECONDS
    if info.organizations == "facet":
        items, cached = await _facet(portal, "organization", ttl)
        organizations = [
            OrganizationSummary(
                name=item["name"],
                title=item.get("display_name") or item["name"],
                package_count=get_or(item, "count", 0),
            )
            for item in items
        ]
        path = "package_search?rows=0&facet.field=organization"
        coverage = "only organizations with at least one dataset are included"
    else:
        raw, cached = await _call(
            portal, "organization_list", {"all_fields": "true"}, ttl, "all_fields"
        )
        organizations = [
            OrganizationSummary(
                id=o.get("id"),
                name=o["name"],
                title=_translated(o, "title", lang) or o["name"],
                package_count=get_or(o, "package_count", 0),
            )
            for o in raw
        ]
        path = "organization_list?all_fields=true"
        coverage = None
    return OrganizationList(
        portal=portal,
        organizations=organizations,
        total_count=len(organizations),
        provenance=_provenance(
            portal,
            path,
            cached,
            "OrganizationList",
            coverage=coverage,
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(
    portal: str, organization_id: str, lang: str = "en"
) -> OrganizationDetail:
    info = _portal(portal)
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")

    # Dataset and user lists are left out to keep this compact; list an
    # organization's datasets with search_datasets(fq="organization:<name>").
    obj, cached = await _call(
        portal,
        "organization_show",
        {"id": organization_id, "include_datasets": "false", "include_users": "false"},
        constants.CACHE_TTL_ORGANIZATION_SECONDS,
        organization_id,
    )
    return OrganizationDetail(
        portal=portal,
        id=obj["id"],
        name=obj["name"],
        title=_translated(obj, "title", lang) or obj["name"],
        description=_translated(obj, "description", lang),
        package_count=get_or(obj, "package_count", 0),
        image_url=_image(obj),
        landing_page_url=info.organization_url.format(lang=lang, id=obj["name"]),
        provenance=_provenance(
            portal, f"organization_show?id={organization_id}", cached, "OrganizationDetail"
        ),
    )


async def get_resource(portal: str, resource_id: str, lang: str = "en") -> ResourceDetail:
    info = _portal(portal)
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")

    obj, cached = await _call(
        portal,
        "resource_show",
        {"id": resource_id},
        constants.CACHE_TTL_RESOURCE_SECONDS,
        resource_id,
    )
    return ResourceDetail(
        portal=portal,
        resource=_resource(obj, info, lang),
        provenance=_provenance(portal, f"resource_show?id={resource_id}", cached, "ResourceDetail"),
    )


def _optional_bool(lic: dict[str, Any], key: str) -> bool | None:
    return None if lic.get(key) is None else to_bool(lic.get(key))


async def list_licenses(portal: str, lang: str = "en") -> LicenseList:
    _portal(portal)
    raw, cached = await _call(
        portal, "license_list", None, constants.CACHE_TTL_LICENSE_SECONDS, "all"
    )

    # Federal names its French license fields `title_fra`/`url_fra`;
    # Ontario uses `title_translated`; the rest are single-language.
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=pick_fra(
                _translated(lic, "title", lang) or lic["id"], lic.get("title_fra"), lang
            ),
            url=_text(pick_fra(_translated(lic, "url", lang) or "", lic.get("url_fra"), lang)),
            status=_text(lic.get("status")),
            family=_text(lic.get("family")),
            is_okd_compliant=_optional_bool(lic, "is_okd_compliant"),
            is_osi_compliant=_optional_bool(lic, "is_osi_compliant"),
            od_conformance=_text(lic.get("od_conformance")),
            osd_conformance=_text(lic.get("osd_conformance")),
            domain_content=_optional_bool(lic, "domain_content"),
            domain_data=_optional_bool(lic, "domain_data"),
            domain_software=_optional_bool(lic, "domain_software"),
        )
        for lic in raw
    ]
    return LicenseList(
        portal=portal,
        licenses=licenses,
        provenance=_provenance(
            portal,
            "license_list",
            cached,
            "LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )


async def list_tags(portal: str, query: str | None = None, lang: str = "en") -> TagList:
    """`tag_list`; an unfiltered call is capped at TAG_LIST_MAX tags."""
    del lang
    info = _portal(portal)
    if not info.has_tags:
        raise InvalidInput(
            f"The {portal!r} portal does not use CKAN tags (tag_list is empty upstream). "
            "Search with ckan_search_datasets instead."
        )

    params = {"query": query} if query else None
    raw, cached = await _call(
        portal, "tag_list", params, constants.CACHE_TTL_TAG_SECONDS, query or ""
    )
    names = [
        name
        for t in raw
        if isinstance(name := (t.get("name") if isinstance(t, dict) else t), str) and name
    ]
    truncated = query is None and len(names) > constants.TAG_LIST_MAX
    return TagList(
        portal=portal,
        tags=names[: constants.TAG_LIST_MAX] if truncated else names,
        total_count=len(names),
        query=query,
        truncated=truncated,
        provenance=_provenance(
            portal,
            "tag_list",
            cached,
            "TagList",
            limits=(
                f"unfiltered list capped at {constants.TAG_LIST_MAX} of {len(names)} tags; "
                "pass `query` to search a specific term"
                if truncated
                else None
            ),
        ),
    )


def _require_groups(portal: str, info: Portal) -> None:
    if info.groups == "none":
        raise InvalidInput(
            f"The {portal!r} portal does not use CKAN groups (group_list is empty upstream)."
        )


async def list_groups(portal: str, lang: str = "en") -> GroupList:
    info = _portal(portal)
    _require_groups(portal, info)
    ttl = constants.CACHE_TTL_GROUP_SECONDS
    if info.groups == "facet":
        items, cached = await _facet(portal, "groups", ttl)
        groups = [
            GroupSummary(
                name=item["name"],
                title=item.get("display_name") or item["name"],
                package_count=get_or(item, "count", 0),
                landing_page_url=_landing(info.group_url, lang, item["name"]),
            )
            for item in items
        ]
        path = "package_search?rows=0&facet.field=groups"
        coverage = "only groups with at least one dataset are included"
    else:
        raw, cached = await _call(portal, "group_list", {"all_fields": "true"}, ttl, "all_fields")
        groups = [
            GroupSummary(
                id=g.get("id"),
                name=g["name"],
                title=_translated(g, "title", lang) or g["name"],
                description=_translated(g, "description", lang),
                package_count=get_or(g, "package_count", 0),
                landing_page_url=_landing(info.group_url, lang, g["name"]),
            )
            for g in raw
        ]
        path = "group_list?all_fields=true"
        coverage = None
    return GroupList(
        portal=portal,
        groups=groups,
        total_count=len(groups),
        provenance=_provenance(
            portal,
            path,
            cached,
            "GroupList",
            coverage=coverage,
            freshness="group roster changes infrequently; cached 24h",
        ),
    )


async def get_group(portal: str, group_id: str, lang: str = "en") -> GroupDetail:
    info = _portal(portal)
    _require_groups(portal, info)
    if not group_id.strip():
        raise InvalidInput("group_id must not be empty.")

    obj, cached = await _call(
        portal,
        "group_show",
        {"id": group_id, "include_datasets": "false", "include_users": "false"},
        constants.CACHE_TTL_GROUP_SECONDS,
        group_id,
    )
    return GroupDetail(
        portal=portal,
        id=obj["id"],
        name=obj["name"],
        title=_translated(obj, "title", lang) or obj["name"],
        description=_translated(obj, "description", lang),
        package_count=get_or(obj, "package_count", 0),
        image_url=_image(obj),
        landing_page_url=_landing(info.group_url, lang, obj["name"]),
        provenance=_provenance(portal, f"group_show?id={group_id}", cached, "GroupDetail"),
    )


async def datastore_search(
    portal: str,
    resource_id: str,
    *,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    fields: str | None = None,
    limit: int = constants.DATASTORE_ROWS_DEFAULT,
    offset: int = 0,
) -> DatastoreSearchResult:
    """Rows from one DataStore-active resource (check `datastore_active` first)."""
    info = _portal(portal)
    if not info.has_datastore:
        raise InvalidInput(
            f"The {portal!r} portal has no DataStore extension; download the resource URL instead."
        )
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    if limit < 1 or limit > constants.DATASTORE_ROWS_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.DATASTORE_ROWS_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    params: dict[str, Any] = {"resource_id": resource_id, "limit": limit, "offset": offset}
    if filters:
        params["filters"] = json.dumps(filters)
    if query:
        params["q"] = query
    if sort:
        params["sort"] = sort
    if fields:
        params["fields"] = fields

    result, cached = await _call(
        portal,
        "datastore_search",
        params,
        constants.CACHE_TTL_DATASTORE_SECONDS,
        f"{resource_id}:{filters}:{query}:{sort}:{fields}:{limit}:{offset}",
    )
    records = list_or_empty(result, "records")
    return DatastoreSearchResult(
        portal=portal,
        resource_id=resource_id,
        records=records,
        fields=[
            DatastoreField(id=f["id"], type=f.get("type", "unknown"))
            for f in list_or_empty(result, "fields")
        ],
        total_count=get_or(result, "total", len(records)),
        returned_count=len(records),
        limit=limit,
        offset=offset,
        filters=filters,
        query=query,
        provenance=_provenance(
            portal,
            "datastore_search",
            cached,
            "DatastoreSearchResult",
            limits=f"rows capped at {constants.DATASTORE_ROWS_MAX} per request",
        ),
    )
