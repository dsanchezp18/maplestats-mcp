"""Client for StatCan's official Indicators JSON feeds.

Confirmed live 2026-09-21. Most text fields are bilingual objects
(`{"en": ..., "fr": ...}`); this client resolves each to the
requested `lang` rather than exposing the raw bilingual shape.
`daily_url` is a root-relative path (e.g.
"/daily-quotidien/260617/dq260617a-eng.htm") and is resolved to an
absolute URL. `geo_code` is an int on each indicator but a string in
the response's own `geo` lookup array -- this client matches them by
string value to build a geo_code -> name map, then looks up each
indicator's name from it.
"""

from __future__ import annotations

from typing import Any

import httpx

from maplestats_mcp.modules.statcan.indicators import constants
from maplestats_mcp.modules.statcan.indicators.schemas import Indicator, IndicatorList
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _localized(value: Any, lang: str) -> str | None:
    if isinstance(value, dict):
        return value.get(lang) or value.get("en")
    if isinstance(value, str):
        return value
    return None


async def get_indicators(
    dataset: str = "all",
    query: str = "",
    *,
    geo_code: int | None = None,
    lang: str = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> IndicatorList:
    """Fetch current StatCan indicators, optionally filtered by keyword and geography."""
    url = constants.DATASET_URLS.get(dataset)
    if url is None:
        raise InvalidInput(
            f"statcan_indicators:get_indicators: dataset must be one of "
            f"{sorted(constants.DATASET_URLS)}, got {dataset!r}."
        )
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_indicators:get_indicators: limit must be between 1 and "
            f"{constants.SEARCH_LIMIT_MAX}, got {limit}."
        )

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                f"statcan_indicators:get_indicators returned HTTP {status}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_indicators:get_indicators did not respond in time. Try again shortly."
            ) from exc

    cache_key = f"statcan-indicators:{dataset}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    results = (payload or {}).get("results") or {}
    if "indicators" not in results:
        raise UpstreamError(
            "statcan_indicators:get_indicators: unexpected response shape (missing indicators)."
        )

    geo_names = {
        str(entry.get("geo_code")): _localized(entry.get("label"), lang)
        for entry in results.get("geo") or []
    }

    query_lower = query.strip().lower()
    matched: list[Indicator] = []
    for entry in results["indicators"]:
        title = _localized(entry.get("title"), lang) or ""
        if query_lower and query_lower not in title.lower():
            continue
        entry_geo_code = entry.get("geo_code")
        if geo_code is not None and entry_geo_code != geo_code:
            continue

        growth_rate = entry.get("growth_rate") or {}
        daily_url_raw = _localized(entry.get("daily_url"), lang)
        daily_url = (
            f"https://www.statcan.gc.ca{daily_url_raw}"
            if daily_url_raw and daily_url_raw.startswith("/")
            else daily_url_raw
        )

        matched.append(
            Indicator(
                registry_number=entry.get("registry_number") or 0,
                indicator_number=entry.get("indicator_number") or 0,
                geo_code=entry_geo_code or 0,
                geo_name=geo_names.get(str(entry_geo_code)),
                title=title,
                value=_localized(entry.get("value"), lang) or "",
                reference_period=_localized(entry.get("refper"), lang),
                daily_url=daily_url,
                daily_title=_localized(entry.get("daily_title"), lang),
                source_table=entry.get("source"),
                release_date=entry.get("release_date"),
                growth=_localized(growth_rate.get("growth"), lang),
                growth_details=_localized(growth_rate.get("details"), lang),
            )
        )

    page = matched[:limit]
    return IndicatorList(
        dataset=dataset,
        indicators=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_indicators.IndicatorList",
        ),
    )
