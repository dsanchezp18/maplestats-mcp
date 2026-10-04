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

from maplestats_mcp.modules.arcgis_hub import constants
from maplestats_mcp.modules.arcgis_hub.schemas import (
    DatasetSearchResult,
    DownloadLink,
    FeatureQueryResult,
    ItemDetail,
    ItemSummary,
    PortalInfo,
    PortalList,
)
from maplestats_mcp.shared.arcgis import (
    ITEM_ID_PATTERN,
    SEARCH_WINDOW_MAX,
    ArcGISHubConfig,
    collection_url,
    default_layer_index,
    download_url,
    excerpt,
    file_format,
    get_item,
    item_data_url,
    item_kind,
    layer_query_url,
    parse_epoch_millis,
    query_layer,
    search_items,
    supported_download_formats,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.json_utils import get_or, list_or_empty


def _config(portal: str) -> ArcGISHubConfig:
    info = constants.PORTALS.get(portal)
    if info is None:
        raise InvalidInput(f"portal must be one of {sorted(constants.PORTALS)}, got {portal!r}.")
    return ArcGISHubConfig(
        source=constants.rate_limit_source(portal),
        domain=info.domain,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
        collection=info.collection,
    )


def _item_id(item_id: str) -> str:
    """The item id, checked before it goes into a URL path (see shared/arcgis.py)."""
    cleaned = item_id.strip()
    if not cleaned:
        raise InvalidInput("item_id must not be empty.")
    if not ITEM_ID_PATTERN.match(cleaned):
        raise InvalidInput(
            f"item_id must be an ArcGIS item id (32 hex digits, optionally '_<layer id>') "
            f"as returned by arcgis_hub_search_datasets, got {item_id!r}."
        )
    return cleaned


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
    item_type = item_type or constants.PORTALS[portal].default_item_type
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    if offset + limit > SEARCH_WINDOW_MAX:
        raise InvalidInput(
            f"offset + limit must be at most {SEARCH_WINDOW_MAX} (the catalogue search does "
            f"not page further), got {offset + limit}; narrow the query, tag or item_type."
        )

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
            url=f"{collection_url(config)}/items",
            cached=was_cached,
            schema_name="arcgis_hub.DatasetSearchResult",
            coverage=f"{len(items)} of {total_count} total matches returned",
            limits=f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
        ),
    )


async def _item_feature(config: ArcGISHubConfig, item_id: str) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        return await get_item(config, item_id)

    return await cached_fetch(
        f"{config.source}:get_item:{item_id}", constants.CACHE_TTL_ITEM_SECONDS, fetch
    )


async def _download_links(
    config: ArcGISHubConfig, canonical_id: str, item_type: str, service_url: str | None
) -> list[DownloadLink]:
    """Links that answer, chosen by item kind (see shared/arcgis.py's item_kind)."""
    # Checked live 2026-09-27 (Cochrane, Okotoks, Ottawa): a layer-level item's
    # id is "<item id>_<layer id>", which the download API rejects with HTTP 400;
    # it wants the bare item id and the layer's own id, which is not always 0
    # (Cochrane's "Parks" is layer 18 and 404s with layers=0).
    download_id, _, suffix = canonical_id.partition("_")
    kind = item_kind(item_type, service_url)
    if kind == "file":
        return [DownloadLink(format=file_format(item_type), url=item_data_url(download_id))]
    if kind == "none" or service_url is None:
        return []
    layer_index = int(suffix) if suffix.isdigit() else None
    if layer_index is None:
        # The layer lookup is optional: a secured, broken or misconfigured
        # service (Orangeville's cc70cff5..., whose service answers "Invalid
        # URL", live 2026-10-03) still returns its detail, without links.
        try:
            layer_index = await default_layer_index(config, service_url)
        except (InvalidInput, NotFound, UpstreamUnavailable, UpstreamError):
            return []
    formats = await supported_download_formats(config, download_id, layer_index)
    return [
        DownloadLink(
            format=fmt, url=download_url(config, download_id, fmt, layer_index=layer_index)
        )
        for fmt in formats
    ]


async def get_dataset(portal: str, item_id: str, lang: str = "en") -> ItemDetail:
    """Get one dataset item's metadata and download links; ``lang`` is a documented no-op."""
    del lang
    config = _config(portal)
    item_id = _item_id(item_id)
    feature, was_cached = await _item_feature(config, item_id)
    props = feature.get("properties") or {}
    canonical_id = props.get("id") or item_id
    service_url = props.get("url") or None
    item_type = props.get("type") or "unknown"
    download_urls = (
        await _download_links(config, canonical_id, item_type, service_url)
        if constants.PORTALS[portal].downloads
        else []
    )
    return ItemDetail(
        portal=portal,
        id=canonical_id,
        title=props.get("title") or canonical_id,
        description=props.get("description") or props.get("snippet") or "",
        item_type=item_type,
        tags=list_or_empty(props, "tags"),
        categories=list_or_empty(props, "categories"),
        owner=props.get("owner") or None,
        license_info=props.get("licenseInfo") or None,
        created_at=parse_epoch_millis(props.get("created")),
        modified_at=parse_epoch_millis(props.get("modified")),
        num_views=get_or(props, "numViews", 0),
        extent=feature.get("geometry") or None,
        spatial_reference_wkid=props.get("spatialReference") or None,
        service_url=service_url,
        landing_page_url=f"{constants.landing_page_url(portal)}{canonical_id}",
        download_urls=download_urls,
        provenance=make_provenance(
            source=config.source,
            url=f"{collection_url(config)}/items/{item_id}",
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
    item_id = _item_id(item_id)
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    # A negative id reached the service, which answered an empty, "successful"
    # page (live 2026-10-03).
    if layer_index is not None and layer_index < 0:
        raise InvalidInput(f"layer_index must be >= 0, got {layer_index}.")
    where_clause = where or "1=1"

    feature, _ = await _item_feature(config, item_id)
    props = feature.get("properties") or {}
    canonical_id = props.get("id") or item_id
    item_type = props.get("type") or "unknown"
    service_url = props.get("url") or None
    if (
        service_url
        and item_kind(item_type, service_url) == "none"
        and "/ImageServer" in service_url
    ):
        raise InvalidInput(
            f"item {item_id!r} is an Image Service (raster imagery), which has no rows to "
            "query; open its service_url in a GIS or use another item."
        )
    if not service_url or "/rest/services/" not in service_url:
        raise InvalidInput(
            f"item {item_id!r} ({item_type}) has no queryable FeatureServer/MapServer "
            "service_url; use its download_urls (arcgis_hub_get_dataset) instead."
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
    for record in features:
        row = dict(record.get("attributes") or {})
        if return_geometry and record.get("geometry") is not None:
            row["_geometry"] = record["geometry"]
        rows.append(row)
    exceeded = bool(body.get("exceededTransferLimit", False))
    return FeatureQueryResult(
        portal=portal,
        item_id=canonical_id,
        layer_index=resolved_layer_index,
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        where=where_clause,
        exceeded_transfer_limit=exceeded,
        provenance=make_provenance(
            source=config.source,
            url=layer_query_url(service_url, resolved_layer_index),
            cached=was_cached,
            schema_name="arcgis_hub.FeatureQueryResult",
            limits=(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else "")
            ),
        ),
    )
