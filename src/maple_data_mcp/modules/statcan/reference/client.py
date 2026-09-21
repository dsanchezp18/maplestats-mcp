"""Client for StatCan's Drupal-based catalogue searches (Reference
resources and Analysis share one Drupal 10 search engine and one
`_search` implementation here, differing only in path/query-param
config -- see constants.py).

Confirmed live 2026-09-21. This search view requires a real
browser-shaped session before it will honour the `text`/`texte` query
parameter -- a bare request to the search URL renders every document
in the catalogue, ignoring the keyword, unless that same client
already visited the unparameterized base page and carries the session
cookie it set (reproduced with a raw `curl` and a cookie jar: identical
URL and query string, different result depending only on whether the
base page was fetched first). This module keeps its own
`httpx.AsyncClient` (not `shared/http.py`'s shared one) with
`follow_redirects=True` so the cookie handshake from an unrelated
anti-scraping redirect on first contact resolves within one logical
call, and "warms up" that session with one request to the base page
before the first real search per (catalogue, language) pair, tracked
with a module-level set so later calls skip the extra round trip.

The results page also renders the same paginated result set more than
once: one combined `<details id="all">` (or `"tout"` in French)
holding the actual paginated list, immediately followed by several
more `<details>` sections that re-list the identical items grouped by
category (confirmed live: "housing" returned 30 parsed items against
a `count=10` request before this was scoped down). Parsing is
restricted to that first `<details>` only.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from maple_data_mcp.modules.statcan.reference import constants
from maple_data_mcp.modules.statcan.reference.schemas import (
    ReferenceDocument,
    ReferenceSearchResult,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = httpx.AsyncClient(timeout=30.0, http2=True, follow_redirects=True)
_warmed: set[tuple[str, str]] = set()


def _base_url(catalogue: str, lang: str) -> str:
    config = constants.CATALOGUE_CONFIG[(catalogue, lang)]
    return constants.BASE_URL_TEMPLATE.format(lang=lang, path=config["path"])


async def _warm_up(catalogue: str, lang: str) -> None:
    key = (catalogue, lang)
    if key in _warmed:
        return
    await _client.get(_base_url(catalogue, lang), headers={"User-Agent": "maple-data-mcp/0.1"})
    _warmed.add(key)


def _parse_results(html: str, context: str) -> tuple[list[ReferenceDocument], int]:
    soup = BeautifulSoup(html, "html.parser")
    results_container = soup.find(id="ndm-results")
    if results_container is None:
        raise UpstreamError(f"{context}: unexpected response shape (missing #ndm-results).")

    # The page renders the combined, paginated result set in the FIRST
    # <details> (id="all"/"tout"), immediately followed by several more
    # <details> sections that re-list the same items grouped by
    # category -- confirmed live. Scoping to only the first one avoids
    # silently returning duplicates across every category grouping.
    first_details = results_container.find("details")
    if first_details is None:
        raise UpstreamError(f"{context}: unexpected response shape (no <details> in #ndm-results).")

    total_matched = 0
    summary = first_details.find("summary")
    if summary is not None:
        digits = re.sub(r"[^0-9]", "", summary.get_text())
        total_matched = int(digits) if digits else 0

    documents: list[ReferenceDocument] = []
    for item in first_details.select("li.ndm-item"):
        title_link = item.select_one(".ndm-result-title a")
        if title_link is None:
            continue
        title = title_link.get_text(strip=True)
        href_attr = title_link.get("href")
        href = href_attr if isinstance(href_attr, str) else ""
        url = href if href.startswith("http") else f"https://www150.statcan.gc.ca{href}"

        category = None
        catalogue_number = None
        productid_div = item.select_one(".ndm-result-productid")
        if productid_div is not None:
            heading = productid_div.find("span")
            full_text = productid_div.get_text(" ", strip=True)
            if heading is not None:
                heading_text = heading.get_text(strip=True)
                category = heading_text.rstrip(":") or None
                catalogue_number = full_text.replace(heading_text, "", 1).strip() or None
            else:
                catalogue_number = full_text or None

        description = None
        description_div = item.select_one(".ndm-result-description")
        if description_div is not None:
            heading = description_div.find("span")
            full_text = description_div.get_text(" ", strip=True)
            if heading is not None:
                full_text = full_text.replace(heading.get_text(strip=True), "", 1).strip()
            description = full_text or None

        release_date = None
        date_div = item.select_one(".ndm-result-date")
        if date_div is not None:
            date_span = date_div.find("span", class_="ndm-result-date")
            release_date = date_span.get_text(strip=True) if date_span else None

        documents.append(
            ReferenceDocument(
                title=title,
                url=url,
                catalogue_number=catalogue_number,
                category=category,
                description=description,
                release_date=release_date,
            )
        )
    return documents, total_matched


async def _search(
    catalogue: str,
    tool_name: str,
    query: str,
    *,
    count: int,
    page: int,
    lang: str,
) -> ReferenceSearchResult:
    context = f"statcan_reference:{tool_name}"
    if (catalogue, lang) not in constants.CATALOGUE_CONFIG:
        raise InvalidInput(f"{context}: lang must be one of ('en', 'fr'), got {lang!r}.")
    if count < 1 or count > constants.SEARCH_COUNT_MAX:
        raise InvalidInput(
            f"{context}: count must be between 1 and {constants.SEARCH_COUNT_MAX}, got {count}."
        )
    if page < 0:
        raise InvalidInput(f"{context}: page must be >= 0, got {page}.")

    config = constants.CATALOGUE_CONFIG[(catalogue, lang)]
    params: dict[str, str] = {"count": str(count)}
    if query.strip():
        params[config["query_param"]] = query.strip()
    if page > 0:
        params["p"] = f"{page - 1}-All"
    url = _base_url(catalogue, lang)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            await _warm_up(catalogue, lang)
            response = await _client.get(
                url, params=params, headers={"User-Agent": "maple-data-mcp/0.1"}
            )
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(f"{context} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"{context} did not respond in time. Try again shortly."
            ) from exc

    cache_key = f"statcan-reference:{catalogue}:{lang}:{query.strip().lower()}:{count}:{page}"
    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    documents, total_matched = _parse_results(html, context)

    return ReferenceSearchResult(
        catalogue=catalogue,
        query=query,
        documents=documents,
        returned_count=len(documents),
        total_matched=total_matched,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_reference.ReferenceSearchResult",
        ),
    )


async def search_documents(
    query: str = "",
    *,
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
    lang: str = "en",
) -> ReferenceSearchResult:
    """Search StatCan's Reference resources catalogue (definitions, data sources, methods)."""
    return await _search("reference", "search_documents", query, count=count, page=page, lang=lang)


async def search_analysis(
    query: str = "",
    *,
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
    lang: str = "en",
) -> ReferenceSearchResult:
    """Search StatCan's Analysis catalogue (analytical articles, journals and periodicals)."""
    return await _search("analysis", "search_analysis", query, count=count, page=page, lang=lang)
