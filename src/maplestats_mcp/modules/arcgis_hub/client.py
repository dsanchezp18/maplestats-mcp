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
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import get_or, list_or_empty

# French only: most portals publish their own text in English.
_SOURCE_TEXT_FR = (
    "Titres, descriptions et étiquettes tels que publiés par le portail, le plus souvent en "
    "anglais seulement."
)


def _config(portal: str, lang: str = "en") -> ArcGISHubConfig:
    info = constants.PORTALS.get(portal)
    if info is None:
        raise_localized(
            InvalidInput,
            f"portal must be one of {sorted(constants.PORTALS)}, got {portal!r}.",
            f"portal doit être l'une des valeurs {sorted(constants.PORTALS)}; reçu {portal!r}.",
            lang,
        )
    return ArcGISHubConfig(
        source=constants.rate_limit_source(portal),
        domain=info.domain,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
        collection=info.collection,
    )


def _item_id(item_id: str, lang: str = "en") -> str:
    """The item id, checked before it goes into a URL path (see shared/arcgis.py)."""
    cleaned = item_id.strip()
    if not cleaned:
        raise_localized(
            InvalidInput, "item_id must not be empty.", "item_id ne doit pas être vide.", lang
        )
    if not ITEM_ID_PATTERN.match(cleaned):
        raise_localized(
            InvalidInput,
            f"item_id must be an ArcGIS item id (32 hex digits, optionally '_<layer id>') "
            f"as returned by arcgis_hub_search_datasets, got {item_id!r}.",
            "item_id doit être un identifiant d'élément ArcGIS (32 chiffres hexadécimaux, "
            "suivis au besoin de « _<id de couche> »), comme ceux que renvoie "
            f"arcgis_hub_search_datasets; reçu {item_id!r}.",
            lang,
        )
    return cleaned


def _check_page(limit: int, offset: int, limit_max: int, lang: str) -> None:
    if limit < 1 or limit > limit_max:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {limit_max}, got {limit}.",
            f"limit doit être entre 1 et {limit_max}; reçu {limit}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être supérieur ou égal à 0; reçu {offset}.",
            lang,
        )


def list_portals(lang: str = "en") -> PortalList:
    """Every portal key this module accepts, with its display name and domain."""
    portals = [
        PortalInfo(
            portal=key,
            name=pick(lang, info.name_en, info.name_fr),
            domain=info.domain,
            bilingual_content=info.bilingual_content,
            note=pick(lang, info.note or "", constants.NOTES_FR.get(key, "")) or None,
        )
        for key, info in constants.PORTALS.items()
    ]
    return PortalList(
        portals=portals,
        provenance=make_provenance(
            source="arcgis-hub",
            url=pick(
                lang,
                "(static portal registry in modules/arcgis_hub/constants.py)",
                "(registre fixe des portails dans modules/arcgis_hub/constants.py)",
            ),
            cached=False,
            schema_name="arcgis_hub.PortalList",
            lang=lang,
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
    """Search one portal's ArcGIS Hub dataset catalogue in the language ``lang``."""
    config = _config(portal, lang)
    item_type = item_type or constants.PORTALS[portal].default_item_type
    _check_page(limit, offset, constants.SEARCH_LIMIT_MAX, lang)
    if offset + limit > SEARCH_WINDOW_MAX:
        raise_localized(
            InvalidInput,
            f"offset + limit must be at most {SEARCH_WINDOW_MAX} (the catalogue search does "
            f"not page further), got {offset + limit}; narrow the query, tag or item_type.",
            f"offset + limit doit être d'au plus {SEARCH_WINDOW_MAX} (la recherche dans le "
            f"catalogue ne va pas plus loin); reçu {offset + limit}. Précisez query, tag ou "
            "item_type.",
            lang,
        )

    async def fetch() -> dict[str, Any]:
        return await search_items(
            config,
            query=query,
            tag=tag,
            item_type=item_type,
            limit=limit,
            offset=offset,
            lang=lang,
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
            coverage=pick(
                lang,
                f"{len(items)} of {total_count} total matches returned",
                f"{len(items)} résultats renvoyés sur {total_count} au total",
            ),
            limits=pick(
                lang,
                f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
                f"limit plafonné à {constants.SEARCH_LIMIT_MAX} par requête. {_SOURCE_TEXT_FR}",
            ),
            lang=lang,
        ),
    )


async def _item_feature(
    config: ArcGISHubConfig, item_id: str, lang: str = "en"
) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        return await get_item(config, item_id, lang)

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
    """Get one dataset item's metadata and download links in the language ``lang``."""
    config = _config(portal, lang)
    item_id = _item_id(item_id, lang)
    feature, was_cached = await _item_feature(config, item_id, lang)
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
            limits=pick(lang, "", _SOURCE_TEXT_FR) or None,
            lang=lang,
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
    """Query rows from one FeatureServer/MapServer layer in the language ``lang``.

    ``layer_index=None`` (the default) resolves to whichever layer or
    table id the service itself reports as its first one, rather than
    assuming 0 — confirmed live that a hosted table (no geometry) can
    sit at a non-zero id (see shared/arcgis.py's ``default_layer_index``).
    """
    config = _config(portal, lang)
    item_id = _item_id(item_id, lang)
    _check_page(limit, offset, constants.ROWS_LIMIT_MAX, lang)

    # A negative id reached the service, which answered an empty, "successful"
    # page (live 2026-10-03).
    if layer_index is not None and layer_index < 0:
        raise_localized(
            InvalidInput,
            f"layer_index must be >= 0, got {layer_index}.",
            f"layer_index doit être supérieur ou égal à 0; reçu {layer_index}.",
            lang,
        )
    where_clause = where or "1=1"

    feature, _ = await _item_feature(config, item_id, lang)
    props = feature.get("properties") or {}
    canonical_id = props.get("id") or item_id
    item_type = props.get("type") or "unknown"
    service_url = props.get("url") or None
    if (
        service_url
        and item_kind(item_type, service_url) == "none"
        and "/ImageServer" in service_url
    ):
        raise_localized(
            InvalidInput,
            f"item {item_id!r} is an Image Service (raster imagery), which has no rows to "
            "query; open its service_url in a GIS or use another item.",
            f"l'élément {item_id!r} est un Image Service (imagerie matricielle), qui n'a pas "
            "de lignes à interroger; ouvrez son service_url dans un SIG ou choisissez un autre "
            "élément.",
            lang,
        )
    if not service_url or "/rest/services/" not in service_url:
        raise_localized(
            InvalidInput,
            f"item {item_id!r} ({item_type}) has no queryable FeatureServer/MapServer "
            "service_url; use its download_urls (arcgis_hub_get_dataset) instead.",
            f"l'élément {item_id!r} ({item_type}) n'a pas de service_url FeatureServer/"
            "MapServer interrogeable; utilisez plutôt ses download_urls "
            "(arcgis_hub_get_dataset).",
            lang,
        )
    resolved_layer_index = (
        layer_index
        if layer_index is not None
        else await default_layer_index(config, service_url, lang)
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
            lang=lang,
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
            limits=pick(
                lang,
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else ""),
                f"lignes plafonnées à {constants.ROWS_LIMIT_MAX} par requête"
                + (
                    " (la limite de transfert propre à la couche a été atteinte avant)"
                    if exceeded
                    else ""
                )
                + "; noms de champs et valeurs tels que publiés par le service",
            ),
            lang=lang,
        ),
    )
