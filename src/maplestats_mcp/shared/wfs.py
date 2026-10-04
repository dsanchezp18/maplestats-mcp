"""Shared plumbing for any OGC WFS 2.0 (GeoServer) deployment.

Confirmed live 2026-09-20 against Natural Resources Canada's Canadian
Wildland Fire Information System (CWFIS) GeoServer instance
(cwfis.cfs.nrcan.gc.ca/geoserver). This is the first OGC WFS-platform
source in this codebase (every other geospatial source here is either
an ArcGIS Hub/REST FeatureServer or a bare CKAN/Socrata/Opendatasoft
catalogue); if a future source runs the same GeoServer WFS 2.0 stack,
this client should work unchanged for it, per AGENTS.md's
adaptor-first philosophy. What differs per portal (domain, endpoint
path, rate limit, cache TTLs) stays in each modules/<source>/ package.

Three live-verified platform quirks this module encodes:

1. `outputFormat=application/json` returns GeoJSON for a *successful*
   GetFeature request, but any error (a malformed `CQL_FILTER`, an
   unknown `typeName`) always answers HTTP 400 with an OGC
   `ows:ExceptionReport` in XML, not JSON, regardless of the requested
   outputFormat -- confirmed live for both a CQL syntax error and an
   unknown type name. `_extract_exception_text` below pulls the
   human-readable `<ows:ExceptionText>` out of that XML rather than
   trying to JSON-decode an error response.
2. `propertyName` (a comma-separated field list) both narrows the
   returned attributes *and* suppresses geometry (`"geometry": null`)
   when the geometry field itself is left out of the list -- useful for
   a lightweight, attribute-only query against a dataset whose full
   polygon geometry would otherwise dominate the response size.
   `srsName` reprojects returned geometry (e.g. `EPSG:4326` for plain
   lat/lon instead of a source dataset's native projection).
3. A plain GetFeature response already includes `totalFeatures` and
   `numberMatched` counts alongside the page of `features` actually
   returned -- no separate `resultType=hits` request is needed to get
   a total count before paging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn
from xml.etree import ElementTree

import httpx

from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.upstream_text import is_backend_outage, network_error

_OWS_NS = "{http://www.opengis.net/ows/1.1}"


@dataclass(frozen=True)
class WfsConfig:
    """Per-portal configuration for the shared OGC WFS 2.0 client."""

    source: str
    base_url: str
    rate_limit_per_second: float
    rate_limit_capacity: float


def _limiter(config: WfsConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _extract_exception_text(body: bytes) -> str:
    """Pull the human-readable message out of an OGC ExceptionReport.

    Falls back to a truncated raw-text view if the body isn't parseable
    XML (confirmed live this endpoint always answers errors as XML, but
    guarding here costs nothing and avoids a confusing secondary
    traceback if that ever changes).
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return body[:200].decode("utf-8", errors="replace")
    text_el = root.find(f".//{_OWS_NS}ExceptionText")
    if text_el is not None and text_el.text:
        return text_el.text.strip().splitlines()[0]
    return body[:200].decode("utf-8", errors="replace")


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _extract_exception_text(exc.response.content)
    if status == 404:
        raise call_error(
            NotFound,
            f"{context}: no match found ({detail}).",
            f"{context} : aucune correspondance ({detail}).",
        ) from exc
    if status == 429 or (400 <= status < 500 and is_backend_outage(detail)):
        # Some servers answer a database-pool failure (or throttling) with a 4xx; that
        # is the service being unavailable, not a mistake in the request.
        raise call_error(
            UpstreamUnavailable,
            f"{context}: the service is temporarily unavailable ({detail}). Try again shortly.",
            f"{context} : le service est temporairement indisponible ({detail}). Réessayez "
            "sous peu.",
        ) from exc
    if 400 <= status < 500:
        raise call_error(
            InvalidInput,
            f"{context}: rejected the request ({detail}).",
            f"{context} : requête refusée ({detail}).",
        ) from exc
    raise call_error(
        UpstreamError,
        f"{context} returned HTTP {status}: {detail}",
        f"{context} a renvoyé HTTP {status} : {detail}",
    ) from exc


def feature_url(
    config: WfsConfig,
    type_name: str,
    *,
    cql_filter: str | None = None,
    property_names: str | None = None,
    srs_name: str | None = None,
    sort_by: str | None = None,
    count: int = 10,
    start_index: int = 0,
) -> str:
    """The full GetFeature URL `get_features` requests, for provenance."""
    params = _feature_params(
        type_name, cql_filter, property_names, srs_name, sort_by, count, start_index
    )
    return str(httpx.URL(config.base_url, params=params))


def _feature_params(
    type_name: str,
    cql_filter: str | None,
    property_names: str | None,
    srs_name: str | None,
    sort_by: str | None,
    count: int,
    start_index: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": type_name,
        "outputFormat": "application/json",
        "count": count,
        "startIndex": start_index,
    }
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    if property_names:
        params["propertyName"] = property_names
    if srs_name:
        params["srsName"] = srs_name
    if sort_by:
        params["sortBy"] = sort_by
    return params


async def describe_feature_type(config: WfsConfig, type_name: str) -> list[tuple[str, str]]:
    """The (name, type) of each property of one feature type, in the server's order.

    GeoServer answers DescribeFeatureType with `outputFormat=application/json`
    as {"featureTypes": [{"properties": [{"name", "type"}, ...]}]}; checked
    live 2026-10-03 on BCGW, where a geometry property's type is "gml:..."
    (e.g. "gml:Geometry") and every attribute's is "xsd:...". Errors come back
    as the same XML ExceptionReport as GetFeature's.
    """
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "DescribeFeatureType",
        "typeName": type_name,
        "outputFormat": "application/json",
    }
    await _limiter(config).acquire()
    context = f"{config.source}:describe_feature_type:{type_name}"
    try:
        body = await api_get(config.base_url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise network_error(context, exc) from exc
    types = body.get("featureTypes") if isinstance(body, dict) else None
    if not isinstance(types, list) or not types or not isinstance(types[0], dict):
        raise call_error(
            UpstreamError,
            f"{context}: the answer lists no feature type.",
            f"{context} : la réponse ne liste aucun type d'entité.",
        )
    properties = types[0].get("properties") or []
    return [
        (str(p.get("name")), str(p.get("type") or ""))
        for p in properties
        if isinstance(p, dict) and p.get("name")
    ]


async def get_features(
    config: WfsConfig,
    type_name: str,
    *,
    cql_filter: str | None = None,
    property_names: str | None = None,
    srs_name: str | None = None,
    sort_by: str | None = None,
    count: int = 10,
    start_index: int = 0,
) -> dict[str, Any]:
    """Run a WFS 2.0 GetFeature request against one feature type, as GeoJSON."""
    params = _feature_params(
        type_name, cql_filter, property_names, srs_name, sort_by, count, start_index
    )
    await _limiter(config).acquire()
    context = f"{config.source}:get_features:{type_name}"
    try:
        return await api_get(config.base_url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise network_error(context, exc) from exc
