"""Client for StatCan's survey directory and IMDB survey metadata.

Confirmed live 2026-09-21. The survey directory's listing page needs
the same browser-shaped session as the Reference/Analysis catalogues
(`modules/statcan/reference`) before it renders its ~899 survey links
-- a bare request without first visiting the page renders none,
confirmed live. This module keeps its own small `httpx.AsyncClient`
(the same pattern as `modules/statcan/reference/client.py`, not a
shared instance -- these are two independent modules) with
`follow_redirects=True`, warming up the session once per language
before its first real fetch.

IMDB itself needs no such warm-up (a bare request returns the full
survey page directly, confirmed live) -- only the directory listing
does.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup, Tag

from maple_data_mcp.modules.statcan.surveys import constants
from maple_data_mcp.modules.statcan.surveys.schemas import (
    SurveyListing,
    SurveyListResult,
    SurveyMetadata,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import new_client
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = new_client(follow_redirects=True)
_warmed_list_langs: set[str] = set()


def _list_url(lang: str) -> str:
    return constants.SURVEY_LIST_URL_FR if lang == "fr" else constants.SURVEY_LIST_URL_EN


def _imdb_url(lang: str) -> str:
    return constants.IMDB_BASE_URL_FR if lang == "fr" else constants.IMDB_BASE_URL_EN


async def _warm_up_list(lang: str, *, force: bool = False) -> None:
    if lang in _warmed_list_langs and not force:
        return
    response = await _client.get(_list_url(lang), headers={"User-Agent": "maple-data-mcp/0.1"})
    response.raise_for_status()
    _warmed_list_langs.add(lang)


def _has_survey_links(html: str) -> bool:
    return bool(BeautifulSoup(html, "html.parser").select("ul.ndm-surveys-az li a"))


async def search_surveys(
    query: str = "", *, lang: str = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> SurveyListResult:
    """Search StatCan's A-Z survey and statistical program directory."""
    if lang not in ("en", "fr"):
        raise InvalidInput(
            f"statcan_surveys:search_surveys: lang must be one of ('en', 'fr'), got {lang!r}."
        )
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_surveys:search_surveys: limit must be between 1 and "
            f"{constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    url = _list_url(lang)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            await _warm_up_list(lang)
            response = await _client.get(url, headers={"User-Agent": "maple-data-mcp/0.1"})
            response.raise_for_status()
            if _has_survey_links(response.text):
                return response.text

            # An empty directory means the session cookie expired (the page
            # renders no links without one): re-warm once rather than cache
            # "no surveys" for the whole TTL.
            await _warm_up_list(lang, force=True)
            response = await _client.get(url, headers={"User-Agent": "maple-data-mcp/0.1"})
            response.raise_for_status()
            if not _has_survey_links(response.text):
                _warmed_list_langs.discard(lang)
                raise UpstreamError(
                    "statcan_surveys:search_surveys: the directory rendered no surveys even "
                    "after refreshing its session. Try again shortly."
                )
            return response.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(f"statcan_surveys:search_surveys returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_surveys:search_surveys did not respond in time. Try again shortly."
            ) from exc

    cache_key = f"statcan-surveys:list:{lang}"
    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LIST_SECONDS, fetch)

    soup = BeautifulSoup(html, "html.parser")
    all_surveys: list[SurveyListing] = []
    for link in soup.select("ul.ndm-surveys-az li a"):
        href_attr = link.get("href")
        href = href_attr if isinstance(href_attr, str) else ""
        segment = href.rstrip("/").rsplit("/", 1)[-1]
        if not segment.isdigit():
            continue
        all_surveys.append(SurveyListing(survey_id=int(segment), name=link.get_text(strip=True)))

    query_lower = query.strip().lower()
    matched = (
        [s for s in all_surveys if query_lower in s.name.lower()] if query_lower else all_surveys
    )

    page = matched[:limit]
    return SurveyListResult(
        query=query,
        surveys=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_surveys.SurveyListResult",
        ),
    )


def _section_text(soup: BeautifulSoup, heading_id: str) -> str | None:
    heading = soup.find(id=heading_id)
    if heading is None:
        return None
    sibling = heading.find_next_sibling("p")
    return sibling.get_text(strip=True) if sibling is not None else None


def _row_value(soup: BeautifulSoup, label: str) -> str | None:
    for row in soup.select("div.row"):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 2:
            continue
        if label.lower() in cols[0].get_text(strip=True).lower():
            return cols[1].get_text(strip=True) or None
    return None


def _parse_survey_metadata(html: str, survey_id: int, url: str, was_cached: bool) -> SurveyMetadata:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1") or soup.find(id="wb-cont")
    name = heading.get_text(strip=True) if heading is not None else ""

    status = _row_value(soup, "Status")
    frequency = _row_value(soup, "Frequency")
    description = _section_text(soup, "a1")

    subjects: list[str] = []
    subjects_heading = None
    for h4 in soup.find_all("h4"):
        if h4.get_text(strip=True).lower() in ("subjects", "sujets"):
            subjects_heading = h4
            break
    if subjects_heading is not None:
        subjects_list = subjects_heading.find_next_sibling("ul")
        if isinstance(subjects_list, Tag):
            subjects = [li.get_text(strip=True) for li in subjects_list.find_all("li")]

    return SurveyMetadata(
        survey_id=survey_id,
        name=name,
        status=status,
        frequency=frequency,
        description=description,
        subjects=subjects,
        detail_url=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_surveys.SurveyMetadata",
        ),
    )


async def get_survey_metadata(survey_id: int, *, lang: str = "en") -> SurveyMetadata:
    """Fetch a survey's IMDB metadata: status, frequency, description, and subjects."""
    if lang not in ("en", "fr"):
        raise InvalidInput(
            f"statcan_surveys:get_survey_metadata: lang must be one of ('en', 'fr'), got {lang!r}."
        )
    url = f"{_imdb_url(lang)}?Function=getSurvey&SDDS={survey_id}"

    async def fetch() -> httpx.Response:
        await _LIMITER.acquire()
        try:
            return await _client.get(url, headers={"User-Agent": "maple-data-mcp/0.1"})
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_surveys:get_survey_metadata did not respond in time. Try again shortly."
            ) from exc

    cache_key = f"statcan-surveys:metadata:{lang}:{survey_id}"
    response, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_METADATA_SECONDS, fetch
    )
    # An unknown SDDS number redirects through
    # .../error-erreur/stc_srvmsg404.html -- StatCan's own dedicated
    # 404 page -- which itself answers HTTP 500 due to a broken
    # redirect chain on their end (confirmed live: 302 -> 301 -> 500,
    # reproduced identically with a raw curl). This is IMDB's
    # deterministic "no such survey" signal, not a generic upstream
    # failure, so it is treated as NotFound rather than UpstreamError.
    if response.status_code in (404, 500) and "srvmsg404" in str(response.url):
        raise NotFound(f"statcan_surveys:get_survey_metadata: no survey found for id {survey_id}.")
    if response.status_code != 200:
        raise UpstreamError(
            f"statcan_surveys:get_survey_metadata returned HTTP {response.status_code}."
        )
    return _parse_survey_metadata(response.text, survey_id, url, was_cached)
