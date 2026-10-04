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
from maplestats_mcp.modules.statcan.lang import say, use_lang
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
    use_lang(lang)
    url = constants.DATASET_URLS.get(dataset)
    if url is None:
        raise InvalidInput(
            say(
                f"statcan_indicators:get_indicators: dataset must be one of "
                f"{sorted(constants.DATASET_URLS)}, got {dataset!r}.",
                f"statcan_indicators:get_indicators : dataset doit être l'une des valeurs {sorted(constants.DATASET_URLS)}, reçu {dataset!r}.",
            )
        )
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_indicators:get_indicators: limit must be between 1 and "
                f"{constants.SEARCH_LIMIT_MAX}, got {limit}.",
                f"statcan_indicators:get_indicators : limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
        )

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_indicators:get_indicators returned HTTP {status}.",
                    f"statcan_indicators:get_indicators a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_indicators:get_indicators did not respond in time. Try again shortly.",
                    "statcan_indicators:get_indicators n'a pas répondu à temps. Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-indicators:{dataset}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    results = (payload or {}).get("results") or {}
    if "indicators" not in results:
        raise UpstreamError(
            say(
                "statcan_indicators:get_indicators: unexpected response shape (missing indicators).",
                "statcan_indicators:get_indicators : réponse de forme inattendue (indicators absent).",
            )
        )

    geo_names = {
        str(entry.get("geo_code")): _localized(entry.get("label"), lang)
        for entry in results.get("geo") or []
    }

    # The feed numbers geographies 0-13 (0 Canada, 1 NL ... 9 AB, 10 BC, 11 YT,
    # 12 NT, 13 NU), not SGC province codes: geo_code=48 matched nothing and
    # returned an empty list with no hint. A code the feed does not use but
    # that is a province/territory SGC code is mapped; 10-13 are valid feed
    # codes and are never reinterpreted as SGC.
    note: str | None = None
    if geo_code is not None and str(geo_code) not in geo_names:
        mapped = constants.SGC_TO_FEED_GEO_CODE.get(geo_code)
        if mapped is None or str(mapped) not in geo_names:
            valid = ", ".join(f"{code}={name}" for code, name in geo_names.items())
            raise InvalidInput(
                say(
                    f"statcan_indicators:get_indicators: geo_code {geo_code} is not in this feed. "
                    f"Use one of: {valid} (or a province SGC code such as 48 for Alberta).",
                    f"statcan_indicators:get_indicators : geo_code {geo_code} ne figure pas dans ce fil. Utilisez l'un de ces codes : {valid} (ou un code de province de la CGT, comme 48 pour l'Alberta).",
                )
            )
        note = say(
            f"geo_code {geo_code} read as SGC code and mapped to feed code {mapped}",
            f"geo_code {geo_code} lu comme un code de la CGT et associé au code {mapped} du fil",
        )
        geo_code = mapped

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
            limits=note,
            lang=lang,
        ),
    )
