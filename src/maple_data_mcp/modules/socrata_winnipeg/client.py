"""HTTP client for the City of Winnipeg's Socrata (SODA) platform.

Field names and shapes below are verified against live responses: the
discovery API's `resource`/`classification`/`link`/`permalink`
envelope, the Views API's flat metadata document (with Unix-seconds
timestamps — see shared/socrata.py's `parse_epoch_seconds`), and the
SODA resource API's plain list-of-row-objects shape. Same platform,
same client shape as modules/socrata_ns/client.py.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.socrata_winnipeg import constants
from maple_data_mcp.modules.socrata_winnipeg.schemas import (
    CategoryCount,
    CategoryList,
    ColumnInfo,
    DatasetDetail,
    DatasetSearchResult,
    DatasetSummary,
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

CONFIG = SocrataConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain=constants.DOMAIN,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
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
    query: str = "",
    *,
    category: str | None = None,
    tag: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search Winnipeg's dataset catalogue; ``lang`` is accepted for consistency."""
    del lang
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await catalog_search(
            CONFIG, query=query, category=category, tag=tag, limit=limit, offset=offset
        )

    cache_key = f"socrata-winnipeg:search:{query}:{category}:{tag}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "resultSetSize", len(raw_results))
    datasets = [_dataset_summary(obj) for obj in raw_results]
    return DatasetSearchResult(
        datasets=datasets,
        total_count=total_count,
        returned_count=len(datasets),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{CATALOG_BASE_URL}?domains={constants.DOMAIN}",
            cached=was_cached,
            schema_name="socrata_winnipeg.DatasetSearchResult",
            coverage=f"{len(datasets)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> DatasetDetail:
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await get_view(CONFIG, dataset_id)

    obj, was_cached = await cached_fetch(
        f"socrata-winnipeg:get_view:{dataset_id}", constants.CACHE_TTL_DATASET_SECONDS, fetch
    )
    license_info = obj.get("license") or {}
    return DatasetDetail(
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
        landing_page_url=f"{constants.DATASET_LANDING_URL}{obj['id']}",
        csv_download_url=f"https://{constants.DOMAIN}/api/views/{obj['id']}/rows.csv?accessType=DOWNLOAD",
        query_url=f"https://{constants.DOMAIN}/resource/{obj['id']}.json",
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/views/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata_winnipeg.DatasetDetail",
        ),
    )


async def query_dataset_rows(
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
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> list[dict[str, Any]]:
        return await query_rows(
            CONFIG,
            dataset_id,
            select=select,
            where=where,
            order=order,
            q=q,
            limit=limit,
            offset=offset,
        )

    cache_key = f"socrata-winnipeg:rows:{dataset_id}:{select}:{where}:{order}:{q}:{limit}:{offset}"
    rows, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ROWS_SECONDS, fetch)
    return RowQueryResult(
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
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/resource/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata_winnipeg.RowQueryResult",
            limits=f"rows capped at {constants.ROWS_LIMIT_MAX} per request",
        ),
    )


async def list_categories(lang: str = "en") -> CategoryList:
    del lang

    async def fetch() -> list[dict[str, Any]]:
        return await facet_categories(CONFIG)

    raw, was_cached = await cached_fetch(
        "socrata-winnipeg:domain_categories", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    categories = [
        CategoryCount(category=c["domain_category"], dataset_count=get_or(c, "count", 0))
        for c in raw
        if c.get("domain_category")
    ]
    return CategoryList(
        categories=categories,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{CATALOG_BASE_URL}/domain_categories?domains={constants.DOMAIN}",
            cached=was_cached,
            schema_name="socrata_winnipeg.CategoryList",
        ),
    )


async def list_tags(lang: str = "en") -> TagList:
    del lang

    async def fetch() -> list[dict[str, Any]]:
        return await facet_tags(CONFIG)

    raw, was_cached = await cached_fetch(
        "socrata-winnipeg:domain_tags", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    tags = [
        TagCount(tag=t["domain_tag"], dataset_count=get_or(t, "count", 0))
        for t in raw
        if t.get("domain_tag")
    ]
    return TagList(
        tags=tags,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{CATALOG_BASE_URL}/domain_tags?domains={constants.DOMAIN}",
            cached=was_cached,
            schema_name="socrata_winnipeg.TagList",
        ),
    )
