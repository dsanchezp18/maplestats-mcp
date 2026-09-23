"""HTTP client for every Canadian Socrata (SODA) portal in constants.PORTALS.

Field names and shapes below are verified against live responses: the
discovery API's `resource`/`classification`/`link`/`permalink`
envelope, the Views API's flat metadata document (with Unix-seconds
timestamps — see shared/socrata.py's `parse_epoch_seconds`), and the
SODA resource API's plain list-of-row-objects shape. These portals
previously lived in five copy-pasted `socrata_<portal>` modules whose
code differed only in the domain; they now share this client keyed by
`portal`.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.socrata import constants
from maple_data_mcp.modules.socrata.schemas import (
    CategoryCount,
    CategoryList,
    ColumnInfo,
    DatasetDetail,
    DatasetSearchResult,
    DatasetSummary,
    PortalInfo,
    PortalList,
    RowQueryResult,
    TagCount,
    TagList,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import get_or, list_or_empty
from maple_data_mcp.shared.socrata import (
    CATALOG_BASE_URL,
    SocrataConfig,
    catalog_search,
    excerpt,
    facet_categories,
    facet_tags,
    get_view,
    parse_dt,
    parse_epoch_seconds,
    query_rows,
)


def _config(portal: str) -> SocrataConfig:
    info = constants.PORTALS.get(portal)
    if info is None:
        raise InvalidInput(f"portal must be one of {sorted(constants.PORTALS)}, got {portal!r}.")
    return SocrataConfig(
        source=f"socrata-{portal}",
        domain=info.domain,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    )


def list_portals(lang: str = "en") -> PortalList:
    """Every portal key this module accepts, with its display name and domain."""
    return PortalList(
        portals=[
            PortalInfo(
                portal=key,
                name=info.name_fr if lang == "fr" else info.name_en,
                domain=info.domain,
                bilingual_content=info.bilingual_content,
            )
            for key, info in constants.PORTALS.items()
        ],
        provenance=make_provenance(
            source="socrata",
            url="(static portal registry in modules/socrata/constants.py)",
            cached=False,
            schema_name="socrata.PortalList",
        ),
    )


def _dataset_summary(obj: dict[str, Any]) -> DatasetSummary:
    resource = obj.get("resource") or {}
    classification = obj.get("classification") or {}
    return DatasetSummary(
        id=resource["id"],
        name=resource.get("name") or resource["id"],
        description_excerpt=excerpt(
            resource.get("description") or "", constants.DESCRIPTION_EXCERPT_LENGTH
        ),
        category=classification.get("domain_category") or None,
        tags=list_or_empty(classification, "domain_tags"),
        dataset_type=resource.get("lens_view_type") or "unknown",
        updated_at=parse_dt(resource.get("updatedAt")),
        download_count=get_or(resource, "download_count", 0),
        permalink=obj.get("permalink") or "",
        landing_page_url=obj.get("link") or obj.get("permalink") or "",
    )


def _column_info(obj: dict[str, Any]) -> ColumnInfo:
    return ColumnInfo(
        name=obj.get("name") or obj.get("fieldName") or "",
        field_name=obj.get("fieldName") or "",
        data_type=obj.get("dataTypeName") or "unknown",
        description=obj.get("description") or None,
    )


async def search_datasets(
    portal: str,
    query: str = "",
    *,
    category: str | None = None,
    tag: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search one portal's dataset catalogue; ``lang`` is accepted for consistency."""
    del lang
    config = _config(portal)
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await catalog_search(
            config, query=query, category=category, tag=tag, limit=limit, offset=offset
        )

    cache_key = f"{config.source}:search:{query}:{category}:{tag}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "resultSetSize", len(raw_results))
    datasets = [_dataset_summary(obj) for obj in raw_results]
    return DatasetSearchResult(
        portal=portal,
        datasets=datasets,
        total_count=total_count,
        returned_count=len(datasets),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.DatasetSearchResult",
            coverage=f"{len(datasets)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def get_dataset(portal: str, dataset_id: str, lang: str = "en") -> DatasetDetail:
    del lang
    config = _config(portal)
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await get_view(config, dataset_id)

    obj, was_cached = await cached_fetch(
        f"{config.source}:get_view:{dataset_id}", constants.CACHE_TTL_DATASET_SECONDS, fetch
    )
    license_info = obj.get("license") or {}
    return DatasetDetail(
        portal=portal,
        id=obj["id"],
        name=obj.get("name") or obj["id"],
        description=obj.get("description") or "",
        category=obj.get("category") or None,
        attribution=obj.get("attribution") or None,
        license_name=license_info.get("name"),
        license_url=license_info.get("termsLink"),
        tags=list_or_empty(obj, "tags"),
        columns=[_column_info(c) for c in list_or_empty(obj, "columns")],
        created_at=parse_epoch_seconds(obj.get("createdAt")),
        rows_updated_at=parse_epoch_seconds(obj.get("rowsUpdatedAt")),
        publication_date=parse_epoch_seconds(obj.get("publicationDate")),
        download_count=get_or(obj, "downloadCount", 0),
        view_count=get_or(obj, "viewCount", 0),
        landing_page_url=f"https://{config.domain}/d/{obj['id']}",
        csv_download_url=f"https://{config.domain}/api/views/{obj['id']}/rows.csv?accessType=DOWNLOAD",
        query_url=f"https://{config.domain}/resource/{obj['id']}.json",
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/api/views/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata.DatasetDetail",
        ),
    )


async def query_dataset_rows(
    portal: str,
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    q: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> RowQueryResult:
    """Run a SoQL query against one dataset's rows; ``lang`` is accepted for consistency."""
    del lang
    config = _config(portal)
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> list[dict[str, Any]]:
        return await query_rows(
            config,
            dataset_id,
            select=select,
            where=where,
            order=order,
            q=q,
            limit=limit,
            offset=offset,
        )

    cache_key = f"{config.source}:rows:{dataset_id}:{select}:{where}:{order}:{q}:{limit}:{offset}"
    rows, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ROWS_SECONDS, fetch)
    return RowQueryResult(
        portal=portal,
        dataset_id=dataset_id,
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        select=select,
        where=where,
        order=order,
        q=q,
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/resource/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata.RowQueryResult",
            limits=f"rows capped at {constants.ROWS_LIMIT_MAX} per request",
        ),
    )


async def list_categories(portal: str, lang: str = "en") -> CategoryList:
    del lang
    config = _config(portal)

    async def fetch() -> list[dict[str, Any]]:
        return await facet_categories(config)

    raw, was_cached = await cached_fetch(
        f"{config.source}:domain_categories", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    categories = [
        CategoryCount(category=c["domain_category"], dataset_count=get_or(c, "count", 0))
        for c in raw
        if c.get("domain_category")
    ]
    return CategoryList(
        portal=portal,
        categories=categories,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}/domain_categories?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.CategoryList",
        ),
    )


async def list_tags(portal: str, lang: str = "en") -> TagList:
    del lang
    config = _config(portal)

    async def fetch() -> list[dict[str, Any]]:
        return await facet_tags(config)

    raw, was_cached = await cached_fetch(
        f"{config.source}:domain_tags", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    tags = [
        TagCount(tag=t["domain_tag"], dataset_count=get_or(t, "count", 0))
        for t in raw
        if t.get("domain_tag")
    ]
    return TagList(
        portal=portal,
        tags=tags,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}/domain_tags?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.TagList",
        ),
    )
