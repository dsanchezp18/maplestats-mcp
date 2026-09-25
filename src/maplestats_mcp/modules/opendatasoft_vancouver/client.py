"""HTTP client for the City of Vancouver's Opendatasoft deployment.

Field names and shapes below are verified against live responses: the
Explore API V2's `{"links": [...], "dataset": {...}}` envelope for a
single dataset (list items are `{"links": [...], "dataset": {...}}`
too, one per entry), the `metas.default`/`metas.dcat` metadata split,
and the record-query response's `{"links": [...], "records": [{"id":
..., "timestamp": ..., "size": ..., "fields": {...}}]}` shape -- see
shared/opendatasoft.py for the platform quirks common to any
Opendatasoft deployment this client relies on.
"""

from __future__ import annotations

from typing import Any

from maplestats_mcp.modules.opendatasoft_vancouver import constants
from maplestats_mcp.modules.opendatasoft_vancouver.schemas import (
    DatasetDetail,
    DatasetSearchResult,
    DatasetSummary,
    DownloadLink,
    FieldInfo,
    RecordQueryResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.json_utils import get_or, list_or_empty
from maplestats_mcp.shared.opendatasoft import (
    OpendatasoftConfig,
    download_url,
    excerpt,
    parse_dt,
)
from maplestats_mcp.shared.opendatasoft import (
    get_dataset as _fetch_dataset,
)
from maplestats_mcp.shared.opendatasoft import (
    query_records as _fetch_records,
)
from maplestats_mcp.shared.opendatasoft import (
    search_datasets as _fetch_search,
)

CONFIG = OpendatasoftConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain=constants.DOMAIN,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _dataset_summary(entry: dict[str, Any]) -> DatasetSummary:
    dataset = entry.get("dataset") or {}
    dataset_id = dataset.get("dataset_id") or ""
    meta = (dataset.get("metas") or {}).get("default") or {}
    return DatasetSummary(
        id=dataset_id,
        title=meta.get("title") or dataset_id,
        description_excerpt=excerpt(
            meta.get("description") or "", constants.DESCRIPTION_EXCERPT_LENGTH
        ),
        theme=list_or_empty(meta, "theme"),
        keyword=list_or_empty(meta, "keyword"),
        records_count=get_or(meta, "records_count", 0),
        modified=parse_dt(meta.get("modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL}{dataset_id}/",
    )


def _field_info(field: dict[str, Any]) -> FieldInfo:
    return FieldInfo(
        name=field.get("name") or "",
        label=field.get("label") or None,
        type=field.get("type") or "unknown",
        description=field.get("description") or None,
    )


async def search_datasets(
    query: str = "",
    *,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search Vancouver's Opendatasoft dataset catalogue; ``lang`` is accepted for consistency."""
    del lang
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await _fetch_search(CONFIG, query=query, limit=limit, offset=offset)

    cache_key = f"opendatasoft-vancouver:search:{query}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    entries = list_or_empty(result, "datasets")
    total_count = get_or(result, "total_count", len(entries))
    datasets = [_dataset_summary(entry) for entry in entries]
    return DatasetSearchResult(
        datasets=datasets,
        total_count=total_count,
        returned_count=len(datasets),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/v2/catalog/datasets",
            cached=was_cached,
            schema_name="opendatasoft_vancouver.DatasetSearchResult",
            coverage=f"{len(datasets)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> DatasetDetail:
    """Get one Vancouver dataset's metadata, fields, and download links; ``lang`` is a documented no-op."""
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await _fetch_dataset(CONFIG, dataset_id)

    result, was_cached = await cached_fetch(
        f"opendatasoft-vancouver:get_dataset:{dataset_id}",
        constants.CACHE_TTL_DATASET_SECONDS,
        fetch,
    )
    dataset = result.get("dataset") or {}
    canonical_id = dataset.get("dataset_id") or dataset_id
    meta = (dataset.get("metas") or {}).get("default") or {}
    return DatasetDetail(
        id=canonical_id,
        title=meta.get("title") or canonical_id,
        description=meta.get("description") or "",
        theme=list_or_empty(meta, "theme"),
        keyword=list_or_empty(meta, "keyword"),
        license_name=meta.get("license") or None,
        license_url=meta.get("license_url") or None,
        publisher=meta.get("publisher") or None,
        update_frequency=meta.get("update_frequency") or None,
        records_count=get_or(meta, "records_count", 0),
        modified=parse_dt(meta.get("modified")),
        fields=[_field_info(field) for field in list_or_empty(dataset, "fields")],
        landing_page_url=f"{constants.DATASET_LANDING_URL}{canonical_id}/",
        download_urls=[
            DownloadLink(format=fmt, url=download_url(CONFIG, canonical_id, fmt))
            for fmt in constants.DOWNLOAD_FORMATS
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/v2/catalog/datasets/{dataset_id}",
            cached=was_cached,
            schema_name="opendatasoft_vancouver.DatasetDetail",
        ),
    )


async def query_records(
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order_by: str | None = None,
    query: str | None = None,
    limit: int = constants.RECORDS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> RecordQueryResult:
    """Query records from one Vancouver dataset with ODSQL filtering/sorting; ``lang`` is accepted for consistency.

    ``where`` is raw ODSQL (e.g. ``"service_category_1 = 'Housing'"``);
    ``query`` instead runs a full-text ``search(*, '...')`` match. If
    both are given, ``where`` wins -- see shared/opendatasoft.py.
    """
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    if limit < 1 or limit > constants.RECORDS_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.RECORDS_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await _fetch_records(
            CONFIG,
            dataset_id,
            select=select,
            where=where,
            order_by=order_by,
            query=query,
            limit=limit,
            offset=offset,
        )

    cache_key = (
        f"opendatasoft-vancouver:records:{dataset_id}:{select}:{where}:{order_by}:{query}:"
        f"{limit}:{offset}"
    )
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RECORDS_SECONDS, fetch)
    entries = list_or_empty(result, "records")
    rows = [entry.get("record", {}).get("fields", {}) for entry in entries]
    total_count = get_or(result, "total_count", len(rows))
    return RecordQueryResult(
        dataset_id=dataset_id,
        rows=rows,
        returned_count=len(rows),
        total_count=total_count,
        limit=limit,
        offset=offset,
        select=select,
        where=where,
        order_by=order_by,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/v2/catalog/datasets/{dataset_id}/records",
            cached=was_cached,
            schema_name="opendatasoft_vancouver.RecordQueryResult",
            coverage=f"{len(rows)} of {total_count} total matching records returned",
            limits=f"records capped at {constants.RECORDS_LIMIT_MAX} per request",
        ),
    )
