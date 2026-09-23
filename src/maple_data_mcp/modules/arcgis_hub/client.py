"""HTTP client for every Canadian ArcGIS Hub open-data portal in constants.PORTALS.

Field names and shapes below are verified against live responses: the
Hub Search API v3's GeoJSON-FeatureCollection-with-`properties` search
envelope, its single-item detail shape (same `properties` object), and
the classic ArcGIS REST FeatureServer/MapServer query response — see
shared/arcgis.py for the platform quirks common to every ArcGIS Hub
deployment this client relies on. These portals previously lived in 28
copy-pasted `arcgis_<portal>` modules whose code differed only in the
domain; they now share this one client keyed by `portal`.
"""

from __future__ import annotations

from typing import Any

from maple_data_mcp.modules.arcgis_hub import constants
from maple_data_mcp.modules.arcgis_hub.schemas import (
    DatasetSearchResult,
    DownloadLink,
    FeatureQueryResult,
    ItemDetail,
    ItemSummary,
    PortalInfo,
    PortalList,
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


def _config(portal: str) -> ArcGISHubConfig:
    info = constants.PORTALS.get(portal)
    if info is None:
        raise InvalidInput(f"portal must be one of {sorted(constants.PORTALS)}, got {portal!r}.")
    return ArcGISHubConfig(
        source=constants.rate_limit_source(portal),
        domain=info.domain,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    )


def list_portals(lang: str = "en") -> PortalList:
    """Every portal key this module accepts, with its display name and domain."""
    portals = [
        PortalInfo(
            portal=key,
            name=info.name_fr if lang == "fr" else info.name_en,
            domain=info.domain,
            bilingual_content=info.bilingual_content,
            note=info.note,
        )
        for key, info in constants.PORTALS.items()
    ]
    return PortalList(
        portals=portals,
        provenance=make_provenance(
            source="arcgis-hub",
            url="(static portal registry in modules/arcgis_hub/constants.py)",
            cached=False,
            schema_name="arcgis_hub.PortalList",
        ),
    )


def _item_summary(portal: str, feature: dict[str, Any]) -> ItemSummary:
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
        landing_page_url=f"{constants.landing_page_url(portal)}{item_id}",
    )


async def search_datasets(
    portal: str,
    query: str = "",
    *,
    tag: str | None = None,
    item_type: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search one portal's ArcGIS Hub dataset catalogue; ``lang`` is accepted for consistency."""
    del lang
    config = _config(portal)
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")

    async def fetch() -> dict[str, Any]:
        return await search_items(
            config, query=query, tag=tag, item_type=item_type, limit=limit, offset=offset
        )

    cache_key = f"{config.source}:search:{query}:{tag}:{item_type}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    features = list_or_empty(result, "features")
    total_count = get_or(result, "numberMatched", len(features))
    items = [_item_summary(portal, feature) for feature in features]
    return DatasetSearchResult(
        portal=portal,
        items=items,
        total_count=total_count,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/api/search/v1/collections/dataset/items",
            cached=was_cached,
            schema_name="arcgis_hub.DatasetSearchResult",
            coverage=f"{len(items)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def get_dataset(portal: str, item_id: str, lang: str = "en") -> ItemDetail:
    """Get one dataset item's metadata and download links; ``lang`` is a documented no-op."""
    del lang
    config = _config(portal)
    if not item_id.strip():
        raise InvalidInput("item_id must not be empty.")

    async def fetch() -> dict[str, Any]:
        return await get_item(config, item_id)

    feature, was_cached = await cached_fetch(
        f"{config.source}:get_item:{item_id}", constants.CACHE_TTL_ITEM_SECONDS, fetch
    )
    props = feature.get("properties") or {}
    canonical_id = props.get("id") or item_id
    return ItemDetail(
        portal=portal,
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
        landing_page_url=f"{constants.landing_page_url(portal)}{canonical_id}",
        download_urls=[
            DownloadLink(format=fmt, url=download_url(config, canonical_id, fmt))
            for fmt in DOWNLOAD_FORMATS
        ],
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/api/search/v1/collections/dataset/items/{item_id}",
            cached=was_cached,
            schema_name="arcgis_hub.ItemDetail",
        ),
    )


async def query_feature_layer(
    portal: str,
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
    """Query rows from one FeatureServer/MapServer layer; ``lang`` is accepted for consistency.

    ``layer_index=None`` (the default) resolves to whichever layer or
    table id the service itself reports as its first one, rather than
    assuming 0 — confirmed live that a hosted table (no geometry) can
    sit at a non-zero id (see shared/arcgis.py's ``default_layer_index``).
    """
    del lang
    config = _config(portal)
    if not item_id.strip():
        raise InvalidInput("item_id must not be empty.")
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    where_clause = where or "1=1"

    item = await get_dataset(portal, item_id)
    service_url = item.service_url
    if not service_url:
        raise InvalidInput(
            f"item {item_id!r} ({item.item_type}) has no queryable FeatureServer/MapServer "
            "service_url; use its download_urls instead."
        )
    resolved_layer_index = (
        layer_index if layer_index is not None else await default_layer_index(config, service_url)
    )

    async def fetch() -> dict[str, Any]:
        return await query_layer(
            config,
            service_url,
            resolved_layer_index,
            where=where_clause,
            out_fields=out_fields,
            order_by=order_by,
            return_geometry=return_geometry,
            limit=limit,
            offset=offset,
        )

    cache_key = (
        f"{config.source}:query:{item_id}:{resolved_layer_index}:{where_clause}:{out_fields}:"
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
        portal=portal,
        item_id=item.id,
        layer_index=resolved_layer_index,
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        where=where_clause,
        exceeded_transfer_limit=exceeded,
        provenance=make_provenance(
            source=config.source,
            url=f"{service_url}/{resolved_layer_index}/query",
            cached=was_cached,
            schema_name="arcgis_hub.FeatureQueryResult",
            limits=(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else "")
            ),
        ),
    )
