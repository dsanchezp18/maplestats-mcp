"""Shared plumbing for any Socrata (SODA) open-data deployment.

Every Socrata-hosted government portal runs the same platform, so the
catalog-search, dataset-metadata, and row-query surface is identical
across domains by construction — confirmed live against
data.novascotia.ca and gnb.socrata.com. What differs per portal
(domain, rate limit, cache TTLs, whether content is bilingual) stays in
each modules/socrata_<portal>/ package, per AGENTS.md.

Two live-verified quirks this module encodes so a per-portal client.py
does not have to rediscover them:

1. The cross-domain discovery API at api.us.socrata.com only applies a
   `categories`/`tags` facet filter when `search_context=<domain>` is
   sent alongside `domains=<domain>` — `domains` alone silently returns
   zero results for an otherwise-valid category/tag value (confirmed
   live: `categories=Health and Wellness` returned 0 results with only
   `domains` set, and 194 — matching the domain_categories facet count
   — once `search_context` was added). Every catalog call here sends
   both.
2. A Socrata deployment reports two different JSON error shapes
   depending on which endpoint failed: the discovery API returns
   `{"error": "Domain not found: ..."}` (a bare string under "error"),
   while the per-domain Views/SODA APIs return `{"message": "...",
   "errorCode": "..."}` or `{"code": "...", "error": true, "message":
   "...", "data": {...}}`. `_error_detail` below checks "message" before
   falling back to a string-valued "error", so both shapes surface a
   real reason instead of the raw response body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter

CATALOG_BASE_URL = "https://api.us.socrata.com/api/catalog/v1"


@dataclass(frozen=True)
class SocrataConfig:
    """Per-portal configuration for the shared Socrata client."""

    source: str
    domain: str
    rate_limit_per_second: float
    rate_limit_capacity: float


def _limiter(config: SocrataConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return exc.response.text[:200]
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
        error = body.get("error")
        if isinstance(error, str) and error:
            return error
    return exc.response.text[:200]


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(config: SocrataConfig, context: str, url: str, params: dict[str, Any]) -> Any:
    await _limiter(config).acquire()
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc


async def catalog_search(
    config: SocrataConfig,
    *,
    query: str = "",
    category: str | None = None,
    tag: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search one domain's dataset catalog via the cross-domain discovery API."""
    params: dict[str, Any] = {
        "domains": config.domain,
        "search_context": config.domain,
        "only": "datasets",
        "limit": limit,
        "offset": offset,
    }
    if query:
        params["q"] = query
    if category:
        params["categories"] = category
    if tag:
        params["tags"] = tag
    return await _get(config, f"{config.source}:catalog_search", CATALOG_BASE_URL, params)


async def facet_categories(config: SocrataConfig) -> list[dict[str, Any]]:
    """List the domain's dataset categories and how many datasets carry each."""
    data = await _get(
        config,
        f"{config.source}:domain_categories",
        f"{CATALOG_BASE_URL}/domain_categories",
        {"domains": config.domain},
    )
    return data.get("results", []) if isinstance(data, dict) else []


async def facet_tags(config: SocrataConfig) -> list[dict[str, Any]]:
    """List the domain's free-text dataset tags and how many datasets carry each."""
    data = await _get(
        config,
        f"{config.source}:domain_tags",
        f"{CATALOG_BASE_URL}/domain_tags",
        {"domains": config.domain},
    )
    return data.get("results", []) if isinstance(data, dict) else []


async def get_view(config: SocrataConfig, dataset_id: str) -> dict[str, Any]:
    """Fetch one dataset's Views API metadata (columns, license, timestamps)."""
    url = f"https://{config.domain}/api/views/{dataset_id}.json"
    return await _get(config, f"{config.source}:get_view:{dataset_id}", url, {})


async def query_rows(
    config: SocrataConfig,
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    q: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Run a SoQL query against one dataset's rows via the SODA resource API."""
    params: dict[str, Any] = {"$limit": limit, "$offset": offset}
    if select:
        params["$select"] = select
    if where:
        params["$where"] = where
    if order:
        params["$order"] = order
    if q:
        params["$q"] = q
    url = f"https://{config.domain}/resource/{dataset_id}.json"
    data = await _get(config, f"{config.source}:query_rows:{dataset_id}", url, params)
    return data if isinstance(data, list) else []


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_epoch_seconds(value: object) -> datetime | None:
    """Convert a Views API Unix-seconds timestamp to a datetime.

    Confirmed live: the Views API (`/api/views/<id>.json`) reports
    `createdAt`, `publicationDate`, and `rowsUpdatedAt` as integer Unix
    seconds, not ISO-8601 strings like the rest of this codebase's
    sources — a plain `datetime.fromisoformat` would raise on them.
    """
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def excerpt(text: str, max_length: int) -> str:
    text = text.strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"
