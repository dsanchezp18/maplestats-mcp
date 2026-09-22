"""HTTP client for StatCan's Sustainable Development Goals (SDG) Data Hub.

Both frameworks (see constants.py) are plain static-file GitHub Pages
hosts -- errors are standard HTTP status codes (404 for an unknown
indicator code), not one of StatCan's other quirky embedded-error
response shapes, so this client uses `shared/http.py`'s ordinary
`api_get` with normal `raise_for_status()` handling.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from maple_data_mcp.modules.statcan.sdg import constants
from maple_data_mcp.modules.statcan.sdg.schemas import (
    SdgIndicatorData,
    SdgIndicatorMetadata,
    SdgIndicatorSearchResult,
    SdgIndicatorSummary,
    SdgObservation,
    SdgSource,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# Indicator codes (e.g. "12-1-1", "1-a-1") and lang are interpolated
# directly into the request path and the cache key.
_VALID_CODE = re.compile(r"^[0-9A-Za-z.-]+$")


def _base_url(framework: str) -> str:
    if framework not in constants.FRAMEWORK_BASE_URLS:
        raise InvalidInput(
            f"framework must be one of {sorted(constants.FRAMEWORK_BASE_URLS)}, got {framework!r}."
        )
    return constants.FRAMEWORK_BASE_URLS[framework]


def _validate_code(code: str) -> str:
    if not _VALID_CODE.match(code):
        raise InvalidInput(f"code {code!r} must contain only letters, digits, '.', or '-'.")
    return code


def _validate_lang(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be one of ('en', 'fr'), got {lang!r}.")
    return lang


async def _get_json(context: str, url: str) -> Any:
    await _LIMITER.acquire()
    try:
        return await api_get(url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(f"{context}: not found at {url}.") from exc
        raise UpstreamError(f"{context} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). "
            "Try again shortly."
        ) from exc


def _summary_from_meta(code: str, meta: dict[str, Any]) -> SdgIndicatorSummary:
    return SdgIndicatorSummary(
        code=code,
        goal_number=meta.get("goal_number"),
        target_number=meta.get("target_number"),
        indicator_name=meta.get("indicator_name", ""),
        reporting_status=meta.get("reporting_status"),
    )


async def _get_index(framework: str, lang: str) -> dict[str, Any]:
    url = f"{_base_url(framework)}/{lang}/meta/all.json"
    cache_key = f"statcan-sdg:index:{framework}:{lang}"

    async def fetch() -> Any:
        return await _get_json(f"statcan_sdg:{framework}", url)

    body, _ = await cached_fetch(cache_key, constants.CACHE_TTL_INDEX_SECONDS, fetch)
    return body


async def search_indicators(
    framework: str,
    query: str = "",
    *,
    lang: str = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> SdgIndicatorSearchResult:
    """Search one SDG framework's indicators by name (client-side, over
    the framework's own cached indicator index). Leave `query` empty to
    list every indicator (86 for "canada", 251 for "global",
    confirmed live)."""
    lang = _validate_lang(lang)
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )

    index = await _get_index(framework, lang)
    needle = query.strip().lower()
    matches = [
        (code, meta)
        for code, meta in index.items()
        if not needle or needle in meta.get("indicator_name", "").lower()
    ]
    summaries = [_summary_from_meta(code, meta) for code, meta in matches[:limit]]
    return SdgIndicatorSearchResult(
        framework=framework,
        query=query,
        indicators=summaries,
        returned_count=len(summaries),
        total_matched=len(matches),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{_base_url(framework)}/{lang}/meta/all.json",
            cached=True,
            schema_name="statcan_sdg.SdgIndicatorSearchResult",
        ),
    )


def _sources_from_meta(meta: dict[str, Any]) -> list[SdgSource]:
    sources: list[SdgSource] = []
    for n in range(1, constants.MAX_SOURCES + 1):
        url = meta.get(f"source_url_{n}")
        organisation = meta.get(f"source_organisation_{n}")
        url_text = meta.get(f"source_url_text_{n}")
        periodicity = meta.get(f"source_periodicity_{n}")
        if not any((url, organisation, url_text, periodicity)):
            break
        sources.append(
            SdgSource(
                organisation=organisation, url=url, url_text=url_text, periodicity=periodicity
            )
        )
    return sources


async def get_indicator_metadata(
    framework: str, code: str, *, lang: str = "en"
) -> SdgIndicatorMetadata:
    """Get one indicator's metadata: goal/target, description, units, and sources.

    Confirmed live: the two frameworks use genuinely different field
    names for the description text -- the Canadian framework's
    `national_indicator_description` and the Global framework's
    `STAT_CONC_DEF` -- this tries the Canadian field first, then the
    Global one, rather than assuming one name applies to both.
    """
    lang = _validate_lang(lang)
    code = _validate_code(code)
    url = f"{_base_url(framework)}/{lang}/meta/{code}.json"
    cache_key = f"statcan-sdg:meta:{framework}:{lang}:{code}"

    async def fetch() -> Any:
        return await _get_json(f"statcan_sdg:get_indicator_metadata:{framework}", url)

    meta, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_METADATA_SECONDS, fetch)
    description = meta.get("national_indicator_description") or meta.get("STAT_CONC_DEF")
    return SdgIndicatorMetadata(
        code=code,
        framework=framework,
        goal_number=meta.get("goal_number"),
        target_number=meta.get("target_number"),
        indicator_name=meta.get("indicator_name", ""),
        description=description,
        computation_units=meta.get("computation_units"),
        reporting_status=meta.get("reporting_status"),
        published=meta.get("published"),
        sources=_sources_from_meta(meta),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_sdg.SdgIndicatorMetadata",
        ),
    )


async def get_indicator_data(framework: str, code: str, *, lang: str = "en") -> SdgIndicatorData:
    """Get one indicator's observations.

    The upstream file is columnar (one list per column, e.g. `Year`,
    `Value`, and zero or more disaggregation columns such as
    `Geography` or `Pillar` that vary per indicator, confirmed live);
    this reshapes it into one row per observation, with every
    non-Year/Value column carried in `disaggregations`.
    """
    lang = _validate_lang(lang)
    code = _validate_code(code)
    url = f"{_base_url(framework)}/{lang}/data/{code}.json"
    cache_key = f"statcan-sdg:data:{framework}:{lang}:{code}"

    async def fetch() -> Any:
        return await _get_json(f"statcan_sdg:get_indicator_data:{framework}", url)

    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DATA_SECONDS, fetch)
    years = body.get("Year", [])
    values = body.get("Value", [])
    disaggregation_columns = [c for c in body if c not in ("Year", "Value")]
    observations = [
        SdgObservation(
            year=years[i],
            value=values[i] if i < len(values) else None,
            disaggregations={
                column: body[column][i]
                for column in disaggregation_columns
                if body[column][i] is not None
            },
        )
        for i in range(len(years))
    ]
    return SdgIndicatorData(
        code=code,
        framework=framework,
        observations=observations,
        returned_count=len(observations),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_sdg.SdgIndicatorData",
        ),
    )
