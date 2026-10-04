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

from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.modules.statcan.sdg import constants
from maplestats_mcp.modules.statcan.sdg.schemas import (
    SdgIndicatorData,
    SdgIndicatorMetadata,
    SdgIndicatorSearchResult,
    SdgIndicatorSummary,
    SdgObservation,
    SdgSource,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

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
            say(
                f"framework must be one of {sorted(constants.FRAMEWORK_BASE_URLS)}, got {framework!r}.",
                f"framework doit être l'une des valeurs {sorted(constants.FRAMEWORK_BASE_URLS)}, reçu {framework!r}.",
            )
        )
    return constants.FRAMEWORK_BASE_URLS[framework]


def _validate_code(code: str) -> str:
    if not _VALID_CODE.match(code):
        raise InvalidInput(
            say(
                f"code {code!r} must contain only letters, digits, '.', or '-'.",
                f"le code {code!r} ne doit contenir que des lettres, des chiffres, « . » ou « - ».",
            )
        )
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
            raise NotFound(
                say(f"{context}: not found at {url}.", f"{context} : introuvable à {url}.")
            ) from exc
        raise UpstreamError(
            say(
                f"{context} returned HTTP {exc.response.status_code}.",
                f"{context} a renvoyé HTTP {exc.response.status_code}.",
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(
                f"{context} did not respond in time (already retried by shared/http.py). "
                "Try again shortly.",
                f"{context} n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
            )
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
    use_lang(lang)
    lang = _validate_lang(lang)
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
                f"limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
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
            lang=lang,
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
    use_lang(lang)
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
            lang=lang,
        ),
    )


async def get_indicator_data(
    framework: str,
    code: str,
    *,
    lang: str = "en",
    limit: int = constants.DATA_LIMIT_DEFAULT,
    offset: int = 0,
    start_year: int | None = None,
    end_year: int | None = None,
    filters: dict[str, str] | None = None,
) -> SdgIndicatorData:
    """Get one indicator's observations, filtered and paged.

    The upstream file is columnar (one list per column, e.g. `Year`,
    `Value`, and zero or more disaggregation columns such as
    `Geography` or `Pillar` that vary per indicator, confirmed live);
    this reshapes it into one row per observation, with every
    non-Year/Value column carried in `disaggregations`. Canada indicator
    1-1-1 is 6,041 rows (1 MB of JSON), so `limit` caps the rows returned
    and `start_year`/`end_year`/`filters` (column name -> exact value,
    e.g. {"Geography": "Alberta"}) narrow them first.

    Confirmed live 2026-10-02: a Global-framework indicator with no data
    (1-1-1) has the body `[]`, not an object -- zero observations.
    """
    use_lang(lang)
    lang = _validate_lang(lang)
    code = _validate_code(code)
    if limit < 1 or limit > constants.DATA_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"limit must be between 1 and {constants.DATA_LIMIT_MAX}, got {limit}.",
                f"limit doit être entre 1 et {constants.DATA_LIMIT_MAX}, reçu {limit}.",
            )
        )
    if offset < 0:
        raise InvalidInput(
            say(f"offset must be >= 0, got {offset}.", f"offset doit être >= 0, reçu {offset}.")
        )
    url = f"{_base_url(framework)}/{lang}/data/{code}.json"
    cache_key = f"statcan-sdg:data:{framework}:{lang}:{code}"

    async def fetch() -> Any:
        return await _get_json(f"statcan_sdg:get_indicator_data:{framework}", url)

    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DATA_SECONDS, fetch)
    no_data = not isinstance(body, dict)
    if no_data:
        body = {}
    years = list_or_empty(body, "Year")
    values = list_or_empty(body, "Value")
    disaggregation_columns = [c for c in body if c not in ("Year", "Value")]
    unknown = [c for c in (filters or {}) if c not in disaggregation_columns]
    if unknown:
        raise InvalidInput(
            say(
                f"filters name unknown column(s) {unknown}; this indicator's columns are "
                f"{disaggregation_columns}.",
                f"filters nomme des colonnes inconnues {unknown} ; les colonnes de cet indicateur sont {disaggregation_columns}.",
            )
        )

    def column_value(column: str, i: int) -> Any:
        column_values = body[column]
        return column_values[i] if i < len(column_values) else None

    matched = [
        i
        for i in range(len(years))
        if (start_year is None or years[i] >= start_year)
        and (end_year is None or years[i] <= end_year)
        and all(str(column_value(c, i)) == v for c, v in (filters or {}).items())
    ]
    page = matched[offset : offset + limit]
    observations = [
        SdgObservation(
            year=years[i],
            value=values[i] if i < len(values) else None,
            disaggregations={
                column: column_value(column, i)
                for column in disaggregation_columns
                if column_value(column, i) is not None
            },
        )
        for i in page
    ]
    notes: list[str] = []
    if no_data or not years:
        notes.append(
            say(
                "upstream publishes no observations for this indicator",
                "la source ne publie aucune observation pour cet indicateur",
            )
        )
    if len(page) < len(matched):
        notes.append(
            say(
                f"returned {len(page)} of {len(matched)} matching rows; use offset/limit, "
                "start_year/end_year or filters for the rest",
                f"{len(page)} des {len(matched)} lignes correspondantes renvoyées ; utilisez "
                "offset/limit, start_year/end_year ou filters pour la suite",
            )
        )
    return SdgIndicatorData(
        code=code,
        framework=framework,
        observations=observations,
        returned_count=len(observations),
        total_matched=len(matched),
        offset=offset,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_sdg.SdgIndicatorData",
            limits="; ".join(notes) if notes else None,
            lang=lang,
        ),
    )
