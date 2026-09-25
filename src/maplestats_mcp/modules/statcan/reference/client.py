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

from maplestats_mcp.modules.statcan.reference import constants
from maplestats_mcp.modules.statcan.reference.schemas import (
    DocumentEdition,
    DocumentFormatLink,
    DocumentFormats,
    ReferenceDocument,
    ReferenceSearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = new_client(follow_redirects=True)
_warmed: set[tuple[str, str]] = set()


def _base_url(catalogue: str, lang: str) -> str:
    config = constants.CATALOGUE_CONFIG[(catalogue, lang)]
    return constants.BASE_URL_TEMPLATE.format(lang=lang, path=config["path"])


async def _warm_up(catalogue: str, lang: str, *, force: bool = False) -> None:
    key = (catalogue, lang)
    if key in _warmed and not force:
        return
    response = await _client.get(
        _base_url(catalogue, lang), headers={"User-Agent": "maplestats-mcp/0.1"}
    )
    response.raise_for_status()
    _warmed.add(key)


def _query_ignored(html: str, query_param: str) -> bool:
    """Whether the page's own search box came back empty despite a keyword.

    Confirmed live 2026-09-22: when the session cookie is missing or has
    expired, the view silently ignores the keyword and renders all 2,031
    documents with an empty search box (`<input name="text" value="">`);
    when the keyword is honoured, that same input carries it back. A
    process-level "already warmed" flag cannot know the server-side
    session expired, so this check is what keeps an unfiltered listing
    from being returned (and cached) as if it matched the query.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields = soup.find_all("input", attrs={"name": query_param})
    # No search box at all is a different page shape, left for
    # _parse_results to reject; only an *empty* box signals a lost session.
    return bool(fields) and not any(str(field.get("value") or "").strip() for field in fields)


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
                url, params=params, headers={"User-Agent": "maplestats-mcp/0.1"}
            )
            response.raise_for_status()
            if config["query_param"] not in params or not _query_ignored(
                response.text, config["query_param"]
            ):
                return response.text

            # The keyword was ignored, so the session has expired: re-warm
            # once and retry before giving up rather than return every
            # document in the catalogue as a "match".
            await _warm_up(catalogue, lang, force=True)
            response = await _client.get(
                url, params=params, headers={"User-Agent": "maplestats-mcp/0.1"}
            )
            response.raise_for_status()
            if _query_ignored(response.text, config["query_param"]):
                _warmed.discard((catalogue, lang))
                raise UpstreamError(
                    f"{context}: the catalogue ignored the search keyword even after "
                    "refreshing its session, so results would be unfiltered. Try again shortly."
                )
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


async def search_data(
    query: str = "",
    *,
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
    lang: str = "en",
) -> ReferenceSearchResult:
    """Search StatCan's Data catalogue (tables plus PUMFs, geographic and other bulk files)."""
    return await _search("data", "search_data", query, count=count, page=page, lang=lang)


def _parse_document_formats(
    html: str, catalogue_number: str, page_url: str, was_cached: bool
) -> DocumentFormats:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(id="wb-cont")
    title = heading.get_text(strip=True) if heading is not None else ""

    category = None
    resolved_number = catalogue_number
    conttype = soup.select_one(".block-ndm-conttype")
    if conttype is not None:
        spans = conttype.find_all("span")
        if len(spans) >= 2:
            category = spans[0].get_text(strip=True).rstrip(":") or None
            resolved_number = spans[1].get_text(strip=True) or catalogue_number

    description = None
    product_block = soup.select_one(".block-ndm-product-block")
    if product_block is not None:
        heading_span = product_block.find("span")
        full_text = product_block.get_text(" ", strip=True)
        if heading_span is not None:
            full_text = full_text.replace(heading_span.get_text(strip=True), "", 1).strip()
        description = full_text or None

    # A specific issue/article's own page lists its file formats (one
    # row per HTML/PDF link, header "Format"); a series-level catalogue
    # number's page instead lists its editions (one row per edition,
    # header "Titles"/"Titres", confirmed live) -- same row shape
    # (link + date), different meaning, so the header decides which
    # list a row belongs in rather than assuming one shape always
    # applies.
    formats: list[DocumentFormatLink] = []
    editions: list[DocumentEdition] = []
    for table in soup.find_all("table"):
        header_cells = [th.get_text(strip=True).lower() for th in table.select("thead th")]
        is_format_table = header_cells and "format" in header_cells[0]
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            link = cells[0].find("a")
            if link is None:
                continue
            href_attr = link.get("href")
            row_url = href_attr if isinstance(href_attr, str) else ""
            if not row_url:
                continue
            release_date = cells[1].get_text(strip=True) or None
            if is_format_table:
                formats.append(
                    DocumentFormatLink(
                        format=link.get_text(strip=True), url=row_url, release_date=release_date
                    )
                )
            else:
                title_attr = link.get("title")
                edition_title = (
                    title_attr if isinstance(title_attr, str) and title_attr else None
                ) or link.get_text(strip=True)
                editions.append(
                    DocumentEdition(title=edition_title, url=row_url, release_date=release_date)
                )

    return DocumentFormats(
        catalogue_number=resolved_number,
        title=title,
        category=category,
        description=description,
        formats=formats,
        editions=editions,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=page_url,
            cached=was_cached,
            schema_name="statcan_reference.DocumentFormats",
        ),
    )


async def get_document_formats(catalogue_number: str, *, lang: str = "en") -> DocumentFormats:
    """Resolve a StatCan catalogue number to its format download links or its editions.

    An issue/article-level catalogue number (e.g.
    "46-28-0001202600100004") returns `formats` -- its actual HTML/PDF
    download links. A series-level catalogue number (e.g. "16-511-X")
    has no formats of its own; its page instead lists `editions`, each
    with its own catalogue number to pass back into this same function
    for that edition's formats -- confirmed live these are two
    genuinely different page shapes with the same row layout (link +
    date), distinguished here only by the table's own header text
    ("Format" vs "Titles"/"Titres").

    Confirmed live 2026-09-21: catalogue-number normalization is also
    genuinely inconsistent -- some numbers resolve as given (e.g.
    "16-511-X"), others only resolve with dashes/spaces stripped (e.g.
    "46-28-0001" 404s, "46280001" works) -- so this tries the number as
    given first and only strips punctuation on a 404, rather than
    guessing a single normalization rule that would break the other
    case.
    """
    number = catalogue_number.strip()
    if not number:
        raise InvalidInput(
            "statcan_reference:get_document_formats: catalogue_number must not be empty."
        )
    if lang not in ("en", "fr"):
        raise InvalidInput(
            f"statcan_reference:get_document_formats: lang must be one of ('en', 'fr'), got {lang!r}."
        )
    suffix = lang
    candidates = [number]
    stripped = re.sub(r"[^0-9A-Za-z]", "", number)
    if stripped and stripped != number:
        candidates.append(stripped)

    last_status: int | None = None
    for candidate in candidates:
        url = f"https://www150.statcan.gc.ca/n1/{suffix}/catalogue/{candidate}"

        async def fetch(url: str = url) -> httpx.Response:
            await _LIMITER.acquire()
            try:
                return await _client.get(url, headers={"User-Agent": "maplestats-mcp/0.1"})
            except httpx.HTTPError as exc:
                raise UpstreamUnavailable(
                    "statcan_reference:get_document_formats did not respond in time. "
                    "Try again shortly."
                ) from exc

        cache_key = f"statcan-reference:catalogue:{suffix}:{candidate}"
        response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
        if response.status_code == 200:
            return _parse_document_formats(response.text, candidate, url, was_cached)
        last_status = response.status_code

    if last_status == 404:
        raise NotFound(
            f"statcan_reference:get_document_formats: no catalogue entry found for "
            f"{catalogue_number!r}."
        )
    raise UpstreamError(
        f"statcan_reference:get_document_formats returned HTTP {last_status} for "
        f"{catalogue_number!r}."
    )
