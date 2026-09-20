"""HTTP client for the Strathcona County Open Data, an ArcGIS Hub deployment.

Field names and shapes below are verified against live responses: the
Hub Search API v3's GeoJSON-FeatureCollection-with-`properties` search
envelope, its single-item detail shape (same `properties` object), and
the classic ArcGIS REST FeatureServer/MapServer query response — see
shared/arcgis.py for the platform quirks common to every ArcGIS Hub
deployment this client relies on.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.arcgis_strathcona_county import constants
from maple_data_mcp.modules.arcgis_strathcona_county.schemas import (
    DatasetSearchResult,
    DownloadLink,
    FeatureQueryResult,
    ItemDetail,
    ItemSummary,
)
from maple_data_mcp.shared.arcgis import (
    DOWNLOAD_FORMATS,
    ArcGISHubConfig,
    default_layer_index,
    download_url,
    excerpt,
    get_item,
    parse_epoch_millis,
    query_layer,
    search_items,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput
from maple_data_mcp.shared.json_utils import get_or, list_or_empty

CONFIG = ArcGISHubConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain=constants.DOMAIN,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


def _item_summary(feature: dict[str, Any]) -> ItemSummary:
    props = feature.get("properties") or {}
    item_id = props.get("id") or feature.get("id") or ""
    return ItemSummary(
        id=item_id,
        title=props.get("title") or item_id,
        description_excerpt=excerpt(
            props.get("snippet") or props.get("description") or "",
            constants.DESCRIPTION_EXCERPT_LENGTH,
        ),
        item_type=props.get("type") or "unknown",
        tags=list_or_empty(props, "tags"),
        categories=list_or_empty(props, "categories"),
        owner=props.get("owner") or None,
        modified_at=parse_epoch_millis(props.get("modified")),
        num_views=get_or(props, "numViews", 0),
        landing_page_url=f"{constants.LANDING_PAGE_URL}{item_id}",
    )


async def search_datasets(
    query: str = "",
    *,
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search Strathcona County's ArcGIS Hub dataset catalogue; ``lang`` is accepted for consistency."""
    del lang
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await search_items(
            CONFIG, query=query, tag=tag, item_type=item_type, limit=limit, offset=offset
        )

    cache_key = f"arcgis-strathcona-county:search:{query}:{tag}:{item_type}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    features = list_or_empty(result, "features")
    total_count = get_or(result, "numberMatched", len(features))
    items = [_item_summary(feature) for feature in features]
    return DatasetSearchResult(
        items=items,
        total_count=total_count,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/search/v1/collections/dataset/items",
            cached=was_cached,
            schema_name="arcgis_strathcona_county.DatasetSearchResult",
            coverage=f"{len(items)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def get_dataset(item_id: str, lang: str = "en") -> ItemDetail:
    """Get one Strathcona County dataset item's metadata and download links; ``lang`` is a documented no-op."""
    del lang
    if not item_id.strip():
        raise InvalidInput("item_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await get_item(CONFIG, item_id)

    feature, was_cached = await cached_fetch(
        f"arcgis-strathcona-county:get_item:{item_id}", constants.CACHE_TTL_ITEM_SECONDS, fetch
    )
    props = feature.get("properties") or {}
    canonical_id = props.get("id") or item_id
    return ItemDetail(
        id=canonical_id,
        title=props.get("title") or canonical_id,
        description=props.get("description") or props.get("snippet") or "",
        item_type=props.get("type") or "unknown",
        tags=list_or_empty(props, "tags"),
        categories=list_or_empty(props, "categories"),
        owner=props.get("owner") or None,
        license_info=props.get("licenseInfo") or None,
        created_at=parse_epoch_millis(props.get("created")),
        modified_at=parse_epoch_millis(props.get("modified")),
        num_views=get_or(props, "numViews", 0),
        extent=feature.get("geometry") or None,
        spatial_reference_wkid=props.get("spatialReference") or None,
        service_url=props.get("url") or None,
        landing_page_url=f"{constants.LANDING_PAGE_URL}{canonical_id}",
        download_urls=[
            DownloadLink(format=fmt, url=download_url(CONFIG, canonical_id, fmt))
            for fmt in DOWNLOAD_FORMATS
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"https://{constants.DOMAIN}/api/search/v1/collections/dataset/items/{item_id}",
            cached=was_cached,
            schema_name="arcgis_strathcona_county.ItemDetail",
        ),
    )


async def query_feature_layer(
    item_id: str,
    *,
    layer_index: int | None = None,
    where: str | None = None,
    out_fields: str = "*",
    order_by: str | None = None,
    return_geometry: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FeatureQueryResult:
    """Query rows from one Strathcona County FeatureServer/MapServer layer; ``lang`` is accepted for consistency.

    ``layer_index=None`` (the default) resolves to whichever layer or
    table id the service itself reports as its first one, rather than
    assuming 0 — confirmed live that a hosted table (no geometry) can
    sit at a non-zero id (see shared/arcgis.py's ``default_layer_index``).
    """
    del lang
    if not item_id.strip():
        raise InvalidInput("item_id must not be empty.")
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    where_clause = where or "1=1"

    item = await get_dataset(item_id)
    if not item.service_url:
        raise InvalidInput(
            f"item {item_id!r} ({item.item_type}) has no queryable FeatureServer/MapServer "
            "service_url; use its download_urls instead."
        )
    resolved_layer_index = (
        layer_index
        if layer_index is not None
        else await default_layer_index(CONFIG, item.service_url)
    )

    async def fetch() -> dict[str, Any]:
        return await query_layer(
            CONFIG,
            item.service_url,  # type: ignore[arg-type]
            resolved_layer_index,
            where=where_clause,
            out_fields=out_fields,
            order_by=order_by,
            return_geometry=return_geometry,
            limit=limit,
            offset=offset,
        )

    cache_key = (
        f"arcgis-strathcona-county:query:{item_id}:{resolved_layer_index}:{where_clause}:{out_fields}:"
        f"{order_by}:{return_geometry}:{limit}:{offset}"
    )
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ROWS_SECONDS, fetch)
    features = list_or_empty(body, "features")
    rows: list[dict[str, Any]] = []
    for feature in features:
        row = dict(feature.get("attributes") or {})
        if return_geometry and feature.get("geometry") is not None:
            row["_geometry"] = feature["geometry"]
        rows.append(row)
    exceeded = bool(body.get("exceededTransferLimit", False))
    return FeatureQueryResult(
        item_id=item.id,
        layer_index=resolved_layer_index,
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        where=where_clause,
        exceeded_transfer_limit=exceeded,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{item.service_url}/{resolved_layer_index}/query",
            cached=was_cached,
            schema_name="arcgis_strathcona_county.FeatureQueryResult",
            limits=(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else "")
            ),
        ),
    )
