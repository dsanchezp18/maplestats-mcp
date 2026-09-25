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
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

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
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


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

    await _limiter(config).acquire()
    context = f"{config.source}:get_features:{type_name}"
    try:
        return await api_get(config.base_url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc
