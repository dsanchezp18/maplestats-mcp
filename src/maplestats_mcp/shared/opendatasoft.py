"""Shared plumbing for any Opendatasoft open-data deployment.

Confirmed live 2026-09-19 against opendata.vancouver.ca's Explore API
V2 (`/api/v2/catalog/...`). Opendatasoft is the platform behind several
Canadian and international government portals; the catalog-search,
dataset-metadata, and record-query surface is identical by
construction across any domain running it, so this shared client
should work unchanged for a future Opendatasoft-hosted source. What
differs per portal (domain, rate limit, cache TTLs) stays in each
modules/opendatasoft_<portal>/ package, per AGENTS.md.

Two live-verified platform quirks this module encodes:

1. Full-text search uses Opendatasoft's own query language (ODSQL), not
   a plain `q=` parameter — confirmed live: `GET /api/v2/catalog/
   datasets?q=park` silently ignores the term and returns the full,
   unfiltered catalogue (`total_count` identical to no filter at all),
   while `GET /api/v2/catalog/datasets?where=search(*,'park')`
   correctly filters. `search_datasets`/`query_records` below always
   build a `where=search(*, '...')` clause instead of a bare `q=`.
2. Errors from both the catalog and per-dataset endpoints share one
   envelope, `{"error_code": ..., "message": ...}`, with a real
   `error_code` value worth surfacing verbatim (`NotFoundResource`,
   `InvalidRESTParameterError`, `ODSQLSyntaxError`) rather than only
   the free-text `message` — confirmed live for a missing dataset
   (404), an out-of-range `limit` (400), and a malformed caller-
   supplied `where`/`order_by` clause (400, since a caller-facing tool
   parameter is passed straight through as raw ODSQL here). `limit` is
   capped at 100 per request on both the catalog and records
   endpoints; a value above that returns 400, not a silently truncated
   page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter


@dataclass(frozen=True)
class OpendatasoftConfig:
    """Per-portal configuration for the shared Opendatasoft client."""

    source: str
    domain: str
    rate_limit_per_second: float
    rate_limit_capacity: float


def _limiter(config: OpendatasoftConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _catalog_url(config: OpendatasoftConfig) -> str:
    return f"https://{config.domain}/api/v2/catalog"


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return exc.response.text[:200]
    if isinstance(body, dict):
        message = body.get("message")
        error_code = body.get("error_code")
        if isinstance(message, str) and message:
            return f"{error_code}: {message}" if error_code else message
        if isinstance(error_code, str) and error_code:
            return error_code
    return exc.response.text[:200]


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(config: OpendatasoftConfig, context: str, url: str, params: dict[str, Any]) -> Any:
    await _limiter(config).acquire()
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc


def _search_where(query: str) -> str | None:
    if not query:
        return None
    escaped = query.replace("'", "''")
    return f"search(*, '{escaped}')"


async def search_datasets(
    config: OpendatasoftConfig,
    *,
    query: str = "",
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search one Opendatasoft domain's dataset catalogue."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    where = _search_where(query)
    if where:
        params["where"] = where
    return await _get(
        config, f"{config.source}:search_datasets", f"{_catalog_url(config)}/datasets", params
    )


async def get_dataset(config: OpendatasoftConfig, dataset_id: str) -> dict[str, Any]:
    """Fetch one dataset's full catalogue metadata."""
    url = f"{_catalog_url(config)}/datasets/{dataset_id}"
    return await _get(config, f"{config.source}:get_dataset:{dataset_id}", url, {})


async def query_records(
    config: OpendatasoftConfig,
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order_by: str | None = None,
    query: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Query one dataset's records, optionally filtered/sorted with raw ODSQL.

    `where` (if given) is passed through verbatim as ODSQL, letting a
    caller filter on any field; `query` instead builds a `search(*,
    '...')` full-text clause the same way `search_datasets` does. If
    both are given, `where` wins and `query` is ignored, since ODSQL
    has no documented way to combine two independent `where` values
    from this client's own construction without risking an invalid
    combined clause.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if select:
        params["select"] = select
    if where:
        params["where"] = where
    elif query:
        search_clause = _search_where(query)
        if search_clause:
            params["where"] = search_clause
    if order_by:
        params["order_by"] = order_by
    url = f"{_catalog_url(config)}/datasets/{dataset_id}/records"
    return await _get(config, f"{config.source}:query_records:{dataset_id}", url, params)


def download_url(config: OpendatasoftConfig, dataset_id: str, fmt: str) -> str:
    """Build a direct export-download link for one dataset.

    Confirmed live: `https://<domain>/api/v2/catalog/datasets/<id>/
    exports/<fmt>` streams the file directly (csv/json/geojson/jsonl
    and others, per that dataset's own `/exports` listing).
    """
    return f"{_catalog_url(config)}/datasets/{dataset_id}/exports/{fmt}"


def parse_dt(value: str | None) -> datetime | None:
    """Parse an Opendatasoft ISO-8601 timestamp (e.g. `metas.default.modified`)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def excerpt(text: str, max_length: int) -> str:
    text = text.strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"
