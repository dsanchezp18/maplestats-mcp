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

import asyncio
import heapq
import itertools
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.statcan.lang import current_lang, say, use_lang
from maplestats_mcp.modules.statcan.reference import constants, pages, pdf
from maplestats_mcp.modules.statcan.reference.schemas import (
    Publication,
    PublicationEdition,
    PublicationSection,
    PublicationText,
    ReferenceDocument,
    ReferenceSearchResult,
    SectionText,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.retrying import get_with_retry

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# Every request sends a Referer: see statcan/reference/constants.py, REFERER.
_client = new_client(follow_redirects=True, headers={"Referer": constants.REFERER})
_warmed: set[tuple[str, str]] = set()


# statcan.gc.ca answers HTTP 429 when its catalogue pages are hit in quick
# succession (seen in the live smoke run of 2026-09-30); the shared retrying
# GET waits and retries, honouring Retry-After.
async def _get(url: str, params: dict[str, str] | None = None) -> httpx.Response:
    return await get_with_retry(_client, url, params=params)


def _base_url(catalogue: str, lang: str) -> str:
    config = constants.CATALOGUE_CONFIG[(catalogue, lang)]
    return constants.BASE_URL_TEMPLATE.format(lang=lang, path=config["path"])


async def _warm_up(catalogue: str, lang: str, *, force: bool = False) -> None:
    key = (catalogue, lang)
    if key in _warmed and not force:
        return
    response = await _get(_base_url(catalogue, lang))
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


def _no_results(soup: BeautifulSoup) -> bool:
    """Whether the page is StatCan's "found no results" page.

    Confirmed live 2026-11-09 (reference "owned accommodation CPI", and the
    same shape on the analysis and data catalogues and in French): a search
    matching nothing renders no `#ndm-results` at all. Its results block,
    `section.block-ndm-results-block`, holds only an `alert-warning` saying
    the search "found no results in this section of the site" ("n'a donné
    aucun résultat"). Treating that page as a changed layout made every
    zero-match search an upstream_error; it is an empty result.
    """
    block = soup.select_one("section.block-ndm-results-block")
    return block is not None and block.select_one(".alert-warning") is not None


def _parse_results(html: str, context: str) -> tuple[list[ReferenceDocument], int]:
    soup = BeautifulSoup(html, "html.parser")
    results_container = soup.find(id="ndm-results")
    if results_container is None and _no_results(soup):
        return [], 0
    if results_container is None:
        raise UpstreamError(
            say(
                f"{context}: unexpected response shape (missing #ndm-results).",
                f"{context} : réponse de forme inattendue (#ndm-results absent).",
            )
        )

    # The page renders the combined, paginated result set in the FIRST
    # <details> (id="all"/"tout"), immediately followed by several more
    # <details> sections that re-list the same items grouped by
    # category -- confirmed live. Scoping to only the first one avoids
    # silently returning duplicates across every category grouping.
    first_details = results_container.find("details")
    if first_details is None:
        raise UpstreamError(
            say(
                f"{context}: unexpected response shape (no <details> in #ndm-results).",
                f"{context} : réponse de forme inattendue (aucun <details> dans #ndm-results).",
            )
        )

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
            say(
                f"{context}: count must be between 1 and {constants.SEARCH_COUNT_MAX}, got {count}.",
                f"{context} : count doit être entre 1 et {constants.SEARCH_COUNT_MAX}, reçu {count}.",
            )
        )
    if page < 0:
        raise InvalidInput(
            say(
                f"{context}: page must be >= 0, got {page}.",
                f"{context} : page doit être >= 0, reçu {page}.",
            )
        )

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
            response = await _get(url, params=params)
            response.raise_for_status()
            if config["query_param"] not in params or not _query_ignored(
                response.text, config["query_param"]
            ):
                return response.text

            # The keyword was ignored, so the session has expired: re-warm
            # once and retry before giving up rather than return every
            # document in the catalogue as a "match".
            await _warm_up(catalogue, lang, force=True)
            response = await _get(url, params=params)
            response.raise_for_status()
            if _query_ignored(response.text, config["query_param"]):
                _warmed.discard((catalogue, lang))
                raise UpstreamError(
                    say(
                        f"{context}: the catalogue ignored the search keyword even after "
                        "refreshing its session, so results would be unfiltered. Try again shortly.",
                        f"{context} : le catalogue a ignoré le mot-clé de recherche même après le renouvellement de sa session, donc les résultats ne seraient pas filtrés. Réessayez sous peu.",
                    )
                )
            return response.text
        except (httpx.HTTPStatusError, httpx.TooManyRedirects) as exc:
            # Since 2026-10-29 every /n1/{lang}/type/ listing answers 404 (a
            # browser loops on redirects instead) while StatCan's own menus
            # still link them: an outage on their side, not a moved page.
            # Say so, rather than a bare status a caller cannot act on.
            if isinstance(exc, httpx.TooManyRedirects) or exc.response.status_code == 404:
                raise UpstreamUnavailable(
                    say(
                        f"{context}: StatCan's catalogue page {url} is unavailable (HTTP 404 "
                        "or a redirect loop on StatCan's side). Try again later; meanwhile "
                        "wds_search_cubes searches StatCan data tables.",
                        f"{context} : la page de catalogue de Statistique Canada {url} est "
                        "indisponible (HTTP 404 ou boucle de redirection du côté de "
                        "Statistique Canada). Réessayez plus tard ; en attendant, "
                        "wds_search_cubes cherche dans les tableaux de données de "
                        "Statistique Canada.",
                    )
                ) from exc
            status = exc.response.status_code
            raise UpstreamError(
                say(f"{context} returned HTTP {status}.", f"{context} a renvoyé HTTP {status}.")
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    f"{context} did not respond in time. Try again shortly.",
                    f"{context} n'a pas répondu à temps. Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-reference:{catalogue}:{lang}:{query.strip().lower()}:{count}:{page}"
    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    documents, total_matched = _parse_results(html, context)

    # The catalogue requires every word of the keyword to match (checked live
    # 2026-11-09: "CPI" finds 19 reference documents, "owned accommodation
    # CPI" none), so an empty result usually means too many or too narrow
    # words, not that StatCan has nothing on the topic.
    limits = None
    if not documents and query.strip():
        limits = say(
            f"No {catalogue} document matched every word of {query.strip()!r}: this "
            "catalogue requires all words to match. Try fewer or broader words (e.g. one "
            "key term), the other statcan_reference_ catalogues, or wds_search_cubes for "
            "data tables.",
            f"Aucun document du catalogue {catalogue} ne contient tous les mots de "
            f"{query.strip()!r} : ce catalogue exige que tous les mots correspondent. "
            "Essayez moins de mots ou des mots plus généraux (par exemple un seul terme "
            "clé), les autres catalogues statcan_reference_, ou wds_search_cubes pour les "
            "tableaux de données.",
        )

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
            limits=limits,
            schema_name="statcan_reference.ReferenceSearchResult",
            lang=current_lang(),
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
    use_lang(lang)
    return await _search("reference", "search_documents", query, count=count, page=page, lang=lang)


async def search_analysis(
    query: str = "",
    *,
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
    lang: str = "en",
) -> ReferenceSearchResult:
    """Search StatCan's Analysis catalogue (analytical articles, journals and periodicals)."""
    use_lang(lang)
    return await _search("analysis", "search_analysis", query, count=count, page=page, lang=lang)


async def search_data(
    query: str = "",
    *,
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
    lang: str = "en",
) -> ReferenceSearchResult:
    """Search StatCan's Data catalogue (tables plus PUMFs, geographic and other bulk files)."""
    use_lang(lang)
    return await _search("data", "search_data", query, count=count, page=page, lang=lang)


# --- Publications: a catalogue number to its editions, sections and text ---------
#
# Verified live 2026-11-10 (pages.py has the page layouts). A catalogue number's
# page, /n1/{lang}/catalogue/<number>, lists the editions; each edition is a main
# page under /n1/pub/ and, for most guides, more pages in its issue folder. These
# requests go through their own client that does not follow redirects by itself:
# the URLs come from callers, so every hop is checked against ALLOWED_HOSTS before
# it is fetched (StatCan's own links answer 301 from /pub/ to /n1/pub/).

_page_client = new_client(follow_redirects=False, headers={"Referer": constants.REFERER})

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "de",
        "des",
        "du",
        "en",
        "et",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "la",
        "le",
        "les",
        "of",
        "on",
        "or",
        "ou",
        "par",
        "pour",
        "que",
        "qui",
        "the",
        "to",
        "un",
        "une",
        "what",
        "which",
        "with",
        "dans",
        "sur",
        "au",
        "aux",
        "est",
        "sont",
    ]
)


@dataclass
class _Resolved:
    catalogue: pages.CataloguePage | None
    edition: pages.Edition | None
    edition_url: str  # the edition's HTML main page, or its PDF
    focus_url: str | None  # a page of the edition given directly as a URL
    pdf_only: bool
    cached: bool
    catalogue_url: str | None = None


def _context(tool: str) -> str:
    return f"statcan_reference:{tool}"


def _checked_url(url: str, tool: str) -> str:
    """An https StatCan URL, or InvalidInput: no other host is ever fetched."""
    text = url.strip()
    if text.lower().startswith("www"):
        text = f"https://{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in constants.ALLOWED_HOSTS:
        raise InvalidInput(
            say(
                f"{_context(tool)}: only Statistics Canada publication pages "
                f"(https://www150.statcan.gc.ca/n1/pub/...) are read, got {url!r}.",
                f"{_context(tool)} : seules les pages de publication de Statistique Canada "
                f"(https://www150.statcan.gc.ca/n1/pub/...) sont lues, reçu {url!r}.",
            )
        )
    if parsed.scheme == "http":
        text = "https" + text[4:]
    return pages.normalize_url(text)


def _decode(response: httpx.Response) -> str:
    """A page's text. The LFS guide's 2007-2012 pages are windows-1252 sent under
    "charset=UTF-8" (71-543-g/2008001/5204157-eng.htm, checked 2026-11-10), which
    httpx would decode with U+FFFD in place of every accented letter."""
    declared = (response.charset_encoding or "utf-8").lower().replace("_", "-")
    if declared not in ("utf-8", "utf8"):
        return response.text
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return response.content.decode("cp1252", errors="replace")


async def _fetch(url: str, tool: str, *, ttl: int, missing: str) -> tuple[dict[str, str], bool]:
    """A page's HTML and final URL, cached; `missing` is the NotFound message on a 404."""

    async def fetch() -> dict[str, str]:
        current = url
        for _ in range(constants.MAX_REDIRECTS + 1):
            await _LIMITER.acquire()
            try:
                response = await get_with_retry(_page_client, current)
            except httpx.HTTPError as exc:
                raise UpstreamUnavailable(
                    say(
                        f"{_context(tool)}: {current} did not respond in time. Try again shortly.",
                        f"{_context(tool)} : {current} n'a pas répondu à temps. Réessayez "
                        "sous peu.",
                    )
                ) from exc
            if response.is_redirect:
                location = response.headers.get("location", "")
                current = _checked_url(urljoin(current, location), tool)
                continue
            if response.status_code == 404:
                raise NotFound(missing)
            if response.status_code >= 400:
                status = response.status_code
                raise UpstreamError(
                    say(
                        f"{_context(tool)}: {current} returned HTTP {status}.",
                        f"{_context(tool)} : {current} a renvoyé HTTP {status}.",
                    )
                )
            content_type = response.headers.get("content-type", "text/html")
            if "html" not in content_type.lower():
                raise UpstreamError(
                    say(
                        f"{_context(tool)}: {current} is not an HTML page ({content_type}).",
                        f"{_context(tool)} : {current} n'est pas une page HTML ({content_type}).",
                    )
                )
            return {"html": _decode(response), "url": current}
        raise UpstreamError(
            say(
                f"{_context(tool)}: {url} redirected more than {constants.MAX_REDIRECTS} times.",
                f"{_context(tool)} : {url} a été redirigée plus de {constants.MAX_REDIRECTS} fois.",
            )
        )

    return await cached_fetch(f"statcan-reference:page:{url}", ttl, fetch)


async def _catalogue(number: str, lang: str, tool: str) -> tuple[pages.CataloguePage, str, bool]:
    url = constants.CATALOGUE_URL_TEMPLATE.format(lang=lang, number=pages.catalogue_path(number))
    data, cached = await _fetch(
        url,
        tool,
        ttl=constants.CATALOGUE_CACHE_TTL_SECONDS,
        missing=say(
            f"{_context(tool)}: StatCan has no catalogue number {number!r} ({url}). Find the "
            "number with statcan_reference_search_documents or statcan_reference_search_analysis.",
            f"{_context(tool)} : Statistique Canada n'a pas de numéro au catalogue {number!r} "
            f"({url}). Trouvez le numéro avec statcan_reference_search_documents ou "
            "statcan_reference_search_analysis.",
        ),
    )
    parsed = pages.parse_catalogue_page(data["html"], data["url"])
    if parsed is None:
        raise UpstreamError(
            say(
                f"{_context(tool)}: {url} does not have a catalogue page's usual layout "
                "(no <h1> and product type); StatCan may have changed the page.",
                f"{_context(tool)} : {url} n'a pas la forme habituelle d'une page du catalogue "
                "(pas de <h1> ni de type de produit) ; Statistique Canada a peut-être changé "
                "la page.",
            )
        )
    return parsed, url, cached


def _pick_edition(catalogue: pages.CataloguePage, edition: str | None, tool: str) -> pages.Edition:
    if not catalogue.editions:
        raise NotFound(
            say(
                f"{_context(tool)}: {catalogue.title} ({catalogue.catalogue_number}) has no "
                "edition online (no HTML or PDF link on its catalogue page).",
                f"{_context(tool)} : {catalogue.title} ({catalogue.catalogue_number}) n'a "
                "aucune édition en ligne (pas de lien HTML ni PDF sur sa page du catalogue).",
            )
        )
    if edition is None or not edition.strip():
        return catalogue.editions[0]
    key = edition.strip().upper()
    for candidate in catalogue.editions:
        number = (candidate.catalogue_number or "").upper()
        if key in (candidate.issue, number) or (number and number.endswith(key)):
            return candidate
    if re.fullmatch(r"\d{4}", key):
        for candidate in catalogue.editions:
            year = candidate.release_date.year if candidate.release_date else None
            if (candidate.issue or "").startswith(key) or str(year) == key:
                return candidate
    issues = ", ".join(e.issue or e.title for e in catalogue.editions[:15])
    raise NotFound(
        say(
            f"{_context(tool)}: {catalogue.catalogue_number} has no edition {edition!r}. "
            f"Editions, newest first: {issues}.",
            f"{_context(tool)} : {catalogue.catalogue_number} n'a pas d'édition {edition!r}. "
            f"Éditions, de la plus récente : {issues}.",
        )
    )


def _same_page(a: str, b: str) -> bool:
    def bare(url: str) -> str:
        return pages.with_lang(urlparse(url).path, "en")

    return bare(a) == bare(b)


def _parse_publication(text: str, lang: str, tool: str) -> tuple[str | None, str | None, bool]:
    """(catalogue number, publication page URL, the URL is a PDF) from the argument."""
    if not text:
        raise InvalidInput(
            say(
                f"{_context(tool)}: give a catalogue number (e.g. '71-543-G') or a "
                "www150.statcan.gc.ca publication URL.",
                f"{_context(tool)} : donnez un numéro au catalogue (par exemple '71-543-G') "
                "ou l'adresse d'une publication sur www150.statcan.gc.ca.",
            )
        )
    if not re.match(r"^(https?://|www)", text, re.IGNORECASE):
        if re.fullmatch(r"\d{2}[0-9A-Za-z-]{2,40}", text):
            return text.upper(), None, False
        raise InvalidInput(
            say(
                f"{_context(tool)}: {text!r} is not a catalogue number (e.g. '71-543-G', "
                "'62F0014M2021011') or a www150.statcan.gc.ca URL.",
                f"{_context(tool)} : {text!r} n'est ni un numéro au catalogue (par exemple "
                "'71-543-G', '62F0014M2021011') ni une adresse www150.statcan.gc.ca.",
            )
        )
    if "www23.statcan.gc.ca/imdb" in text.lower():
        raise InvalidInput(
            say(
                f"{_context(tool)}: {text} is an IMDB survey record, not a publication: read "
                "it with statcan_surveys_get_survey_metadata (its SDDS number is the survey_id).",
                f"{_context(tool)} : {text} est une fiche d'enquête de la BMDI, pas une "
                "publication : lisez-la avec statcan_surveys_get_survey_metadata (son numéro "
                "SDDS est le survey_id).",
            )
        )
    url = _checked_url(text, tool)
    path = urlparse(url).path
    if "/daily-quotidien/" in path:
        raise InvalidInput(
            say(
                f"{_context(tool)}: {text} is a Daily article: read it with "
                "statcan_daily_get_article.",
                f"{_context(tool)} : {text} est un article du Quotidien : lisez-le avec "
                "statcan_daily_get_article.",
            )
        )
    catalogue_match = re.match(r"^/n1/(?:en|fr)/catalogue/([^/?#]+)", path)
    if catalogue_match:
        return catalogue_match.group(1), None, False
    if path.startswith("/n1/pub/"):
        if path.lower().endswith(".pdf"):
            return None, url.partition("#")[0], True
        return None, pages.with_lang(url, lang), False
    raise InvalidInput(
        say(
            f"{_context(tool)}: {text} is not a publication page (/n1/pub/...) or a "
            "catalogue page (/n1/en/catalogue/...).",
            f"{_context(tool)} : {text} n'est ni une page de publication (/n1/pub/...) ni "
            "une page du catalogue (/n1/fr/catalogue/...).",
        )
    )


def _from_edition(
    catalogue: pages.CataloguePage, chosen: pages.Edition, lang: str, cached: bool, url: str | None
) -> _Resolved:
    if chosen.format == "pdf":
        return _Resolved(catalogue, chosen, chosen.url, None, True, cached, url)
    return _Resolved(catalogue, chosen, pages.with_lang(chosen.url, lang), None, False, cached, url)


async def _resolve(publication: str, edition: str | None, lang: str, tool: str) -> _Resolved:
    """A catalogue number or StatCan URL to the edition to read."""
    number, page_url, is_pdf = _parse_publication(publication.strip(), lang, tool)
    if page_url is not None and is_pdf:
        return _Resolved(None, None, page_url, None, True, False)
    if page_url is not None:
        edition_url = pages.edition_of(page_url.partition("#")[0])
        focus = None if _same_page(page_url, edition_url) else page_url
        catalogue = None
        cached = True
        # The catalogue page gives the edition's title, number and the other
        # editions. An article has a number of its own, not its folder's: skipped.
        if "/article/" not in edition_url:
            folder = urlparse(edition_url).path.split("/")[3]
            try:
                catalogue, _, cached = await _catalogue(folder.upper(), lang, tool)
            except (NotFound, UpstreamError):
                catalogue = None
        if catalogue is not None and edition:
            return _from_edition(
                catalogue, _pick_edition(catalogue, edition, tool), lang, cached, None
            )
        chosen = None
        if catalogue is not None:
            chosen = next((e for e in catalogue.editions if _same_page(e.url, edition_url)), None)
        return _Resolved(catalogue, chosen, edition_url, focus, False, cached)
    assert number is not None
    catalogue, catalogue_url, cached = await _catalogue(number, lang, tool)
    return _from_edition(
        catalogue, _pick_edition(catalogue, edition, tool), lang, cached, catalogue_url
    )


async def _page(url: str, edition_url: str, tool: str) -> tuple[pages.Page, bool]:
    data, cached = await _fetch(
        url,
        tool,
        ttl=constants.PAGE_CACHE_TTL_SECONDS,
        missing=say(
            f"{_context(tool)}: StatCan has no page {url}. List the publication's pages "
            "with statcan_reference_get_publication.",
            f"{_context(tool)} : Statistique Canada n'a pas de page {url}. Listez les pages "
            "de la publication avec statcan_reference_get_publication.",
        ),
    )
    return pages.parse_page(data["html"], url, pages.edition_scope(edition_url)), cached


# The id of the edition's main page as a whole (its page key is "").
MAIN_PAGE_ID = "main"


def _page_id(page: pages.Page, edition_url: str) -> str:
    return pages.page_key(page.url, edition_url) or MAIN_PAGE_ID


def _heading_id(page: pages.Page, heading: pages.Heading, edition_url: str) -> str:
    key = pages.page_key(page.url, edition_url)
    index = next(i for i, h in enumerate(page.headings) if h.position == heading.position)
    anchor = heading.anchor or f"h{index + 1}"
    return f"{key}#{anchor}" if key else anchor


def _heading_url(page: pages.Page, heading: pages.Heading) -> str:
    if heading.href:
        return heading.href
    return f"{page.url}#{heading.anchor}" if heading.anchor else page.url


def _top_level(page: pages.Page) -> int:
    levels = [h.level for h in page.headings]
    return min(levels) if levels else 2


def _toc(page: pages.Page, edition_url: str, *, depth: int = 2) -> list[PublicationSection]:
    """The page's own headings (two levels), then the edition pages it links."""
    top = _top_level(page)
    entries = [
        PublicationSection(
            id=_heading_id(page, heading, edition_url),
            title=heading.title,
            level=heading.level - top + 1,
            url=_heading_url(page, heading),
        )
        for heading in page.headings
        if heading.level - top < depth
    ]
    entries.extend(
        PublicationSection(
            id=pages.page_key(link.url, edition_url), title=link.title, level=1, url=link.url
        )
        for link in page.links
    )
    return entries


def _as_of(day: date | None) -> datetime | None:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) if day else None


async def _pdf(url: str, tool: str, lang: str) -> tuple[pdf.PdfText, bool]:
    """A PDF edition's text (pdf.py), downloaded under PDF_MAX_BYTES and cached. On
    a bilingual two-column page, only the column in `lang` is kept, so the text is
    cached per language."""

    async def fetch() -> pdf.PdfText:
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host in constants.ALLOWED_HOSTS,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.PDF_MAX_BYTES,
            context=_context(tool),
        )
        try:
            return await run_parse(
                pdf.extract,
                downloaded.body,
                url,
                max_pages=constants.PDF_MAX_PAGES,
                max_chars=constants.PDF_MAX_CHARS,
                seconds=constants.PDF_EXTRACT_SECONDS,
                lang=lang,
            )
        except pdf.PdfUnreadable as exc:
            raise UpstreamError(
                say(
                    f"{_context(tool)}: {url} could not be read as a PDF ({exc}). Open "
                    "the link, or pass another edition (edition=) that has HTML.",
                    f"{_context(tool)} : {url} n'a pas pu être lu comme un PDF ({exc}). "
                    "Ouvrez le lien, ou passez une autre édition (edition=) offerte en HTML.",
                )
            ) from exc

    return await cached_fetch(
        f"statcan-reference:pdf:{lang}:{url}", constants.PAGE_CACHE_TTL_SECONDS, fetch
    )


def _pdf_note(document: pdf.PdfText) -> str:
    """What a caller should know about text taken from a PDF."""
    url = document.page.url
    notes = [
        say(
            f"This edition is published as PDF only ({url}); its text was extracted from "
            f"the PDF ({document.page_count} pages), so line breaks, columns and tables may "
            "come out imperfect: check a figure against the PDF page cited (each section's "
            "url ends in #page=N).",
            f"Cette édition n'existe qu'en PDF ({url}) ; son texte a été extrait du PDF "
            f"({document.page_count} pages) : les retours à la ligne, les colonnes et les "
            "tableaux peuvent être imparfaits. Vérifiez un chiffre sur la page du PDF citée "
            "(l'url de chaque section se termine par #page=N).",
        )
    ]
    if document.bilingual_pages:
        notes.append(
            say(
                f"{document.bilingual_pages} pages print English and French side by side: "
                "only the English column was kept (lang='fr' reads the French one).",
                f"{document.bilingual_pages} pages présentent l'anglais et le français "
                "côte à côte : seule la colonne française a été gardée (lang='en' lit "
                "la colonne anglaise).",
            )
        )
    if document.two_column_pages:
        notes.append(
            say(
                f"{document.two_column_pages} pages in two columns were read a column at "
                "a time; '[Left column]' and '[Right column]' mark the columns where "
                "their language could not be told.",
                f"{document.two_column_pages} pages en deux colonnes ont été lues une "
                "colonne à la fois ; « [Left column] » et « [Right column] » marquent les "
                "colonnes dont la langue n'a pu être déterminée.",
            )
        )
    if document.pages_read < document.page_count:
        notes.append(
            say(
                f"Only its first {document.pages_read} pages were read (size or time "
                "limit); open the PDF for the rest.",
                f"Seules ses {document.pages_read} premières pages ont été lues (limite de "
                "taille ou de temps) ; ouvrez le PDF pour la suite.",
            )
        )
    return " ".join(notes)


def _pdf_toc(document: pdf.PdfText, edition_url: str) -> list[PublicationSection]:
    """A PDF's bookmarks (two levels) when it has them, else one entry per page."""
    page = document.page
    if document.has_outline:
        return [
            entry
            for entry, heading in zip(_toc(page, edition_url, depth=6), page.headings, strict=True)
            if heading.anchor is None and entry.level <= 2
        ]
    return [
        entry
        for entry, heading in zip(_toc(page, edition_url, depth=6), page.headings, strict=True)
        if heading.anchor is not None
    ]


_PDF_PAGE_REF = re.compile(r"^(?:p|pp|page|pages?)?\.?\s*=?\s*(\d{1,4})$", re.IGNORECASE)


def _pdf_section(section: str) -> str:
    """'12', 'p12', 'page 12' and 'page=12' all name page 12 of a PDF."""
    match = _PDF_PAGE_REF.match(section.strip())
    return pdf.page_anchor(int(match.group(1))) if match else section


def _query_hints(query: str, catalogue_number: str | None) -> list[str]:
    """Pointers to where a concept is defined, for concepts that are not where a
    caller would look (constants.QUERY_HINTS)."""
    folded = pages.fold(query)
    number = (catalogue_number or "").upper()
    return [
        say(hint.en, hint.fr)
        for hint in constants.QUERY_HINTS
        if re.search(hint.pattern, folded) and number not in hint.skip
    ]


def _older_note(resolved: _Resolved) -> str | None:
    catalogue = resolved.catalogue
    latest = catalogue.editions[0] if catalogue and catalogue.editions else None
    if resolved.edition is not None and latest is not None and resolved.edition is not latest:
        return say(
            f"Not the latest edition: the latest is {latest.title} ({latest.release_date}).",
            f"Ce n'est pas la dernière édition : la dernière est {latest.title} "
            f"({latest.release_date}).",
        )
    return None


def _check_text_args(tool: str, max_chars: int, start_char: int, limit: int) -> None:
    if not 200 <= max_chars <= constants.TEXT_MAX_CHARS_MAX:
        raise InvalidInput(
            say(
                f"{_context(tool)}: max_chars must be between 200 and "
                f"{constants.TEXT_MAX_CHARS_MAX}, got {max_chars}.",
                f"{_context(tool)} : max_chars doit être entre 200 et "
                f"{constants.TEXT_MAX_CHARS_MAX}, reçu {max_chars}.",
            )
        )
    if start_char < 0:
        raise InvalidInput(
            say(
                f"{_context(tool)}: start_char must be >= 0, got {start_char}.",
                f"{_context(tool)} : start_char doit être >= 0, reçu {start_char}.",
            )
        )
    if not 1 <= limit <= constants.QUERY_MATCHES_MAX:
        raise InvalidInput(
            say(
                f"{_context(tool)}: limit must be between 1 and {constants.QUERY_MATCHES_MAX}, "
                f"got {limit}.",
                f"{_context(tool)} : limit doit être entre 1 et {constants.QUERY_MATCHES_MAX}, "
                f"reçu {limit}.",
            )
        )


def _editions(catalogue: pages.CataloguePage | None) -> list[PublicationEdition]:
    editions = catalogue.editions if catalogue else []
    return [
        PublicationEdition(
            title=e.title,
            url=e.url,
            release_date=e.release_date,
            catalogue_number=e.catalogue_number,
            issue=e.issue,
            format="pdf" if e.format == "pdf" else "html",
            archived=e.archived,
        )
        for e in editions[: constants.EDITIONS_LISTED_MAX]
    ]


async def get_publication(
    publication: str, *, edition: str | None = None, lang: str = "en"
) -> Publication:
    """A publication's latest (or chosen) edition: title, date, sections and editions."""
    use_lang(lang)
    tool = "get_publication"
    resolved = await _resolve(publication, edition, lang, tool)
    catalogue = resolved.catalogue
    chosen = resolved.edition
    editions_total = len(catalogue.editions) if catalogue else 0
    listed = _editions(catalogue)
    common: dict[str, Any] = {
        "catalogue_number": catalogue.catalogue_number if catalogue else None,
        "product_type": catalogue.product_type if catalogue else None,
        "description": catalogue.description if catalogue else None,
        "editions": listed,
        "editions_total": editions_total,
    }
    if resolved.pdf_only:
        document, cached = await _pdf(resolved.edition_url, tool, lang)
        sections = _pdf_toc(document, resolved.edition_url)
        notes = [_pdf_note(document)]
        if len(sections) > constants.SECTIONS_LISTED_MAX:
            notes.append(
                say(
                    f"First {constants.SECTIONS_LISTED_MAX} of {len(sections)} pages listed.",
                    f"Les {constants.SECTIONS_LISTED_MAX} premières de {len(sections)} pages.",
                )
            )
            sections = sections[: constants.SECTIONS_LISTED_MAX]
        notes.append(
            say(
                "Read a page or bookmark with statcan_reference_get_section_text("
                "publication, section=<id>, edition=...) ('page=12', or a bookmark's id or "
                "title), or search the whole PDF with query=<words>.",
                "Lisez une page ou un signet avec statcan_reference_get_section_text("
                "publication, section=<id>, edition=...) ('page=12', ou l'id ou le titre "
                "d'un signet), ou cherchez dans tout le PDF avec query=<mots>.",
            )
        )
        older = _older_note(resolved)
        if older:
            notes.append(older)
        return Publication(
            **common,
            title=(catalogue.title if catalogue else None)
            or (chosen.title if chosen else None)
            or document.page.title
            or "PDF",
            edition_title=(chosen.title if chosen else None) or document.page.title or None,
            issue=chosen.issue if chosen else None,
            release_date=chosen.release_date if chosen else None,
            archived=chosen.archived if chosen else False,
            format="pdf",
            url=resolved.edition_url,
            pdf_url=resolved.edition_url,
            sections=sections,
            provenance=make_provenance(
                source=constants.RATE_LIMIT_SOURCE,
                url=resolved.edition_url,
                cached=cached and resolved.cached,
                as_of=_as_of(chosen.release_date if chosen else None),
                limits=" ".join(notes),
                schema_name="statcan_reference.Publication",
                lang=current_lang(),
            ),
        )

    page, cached = await _page(resolved.edition_url, resolved.edition_url, tool)
    sections = _toc(page, resolved.edition_url)
    notes: list[str] = []
    if len(sections) > constants.SECTIONS_LISTED_MAX:
        notes.append(
            say(
                f"First {constants.SECTIONS_LISTED_MAX} of {len(sections)} sections listed.",
                f"Les {constants.SECTIONS_LISTED_MAX} premières de {len(sections)} sections.",
            )
        )
        sections = sections[: constants.SECTIONS_LISTED_MAX]
    if editions_total > len(listed):
        notes.append(
            say(
                f"Newest {len(listed)} of {editions_total} editions listed.",
                f"Les {len(listed)} plus récentes de {editions_total} éditions.",
            )
        )
    older = _older_note(resolved)
    if older:
        notes.append(older)
    notes.append(
        say(
            "Read a section with statcan_reference_get_section_text(publication, "
            "section=<id>), or search the whole edition with query=<words>. Pages listed "
            "at level 1 may hold sections of their own.",
            "Lisez une section avec statcan_reference_get_section_text(publication, "
            "section=<id>), ou cherchez dans toute l'édition avec query=<mots>. Les pages "
            "de niveau 1 peuvent contenir leurs propres sections.",
        )
    )
    release = page.release_date or (chosen.release_date if chosen else None)
    return Publication(
        **common,
        title=(catalogue.title if catalogue else None) or page.title,
        edition_title=page.title or (chosen.title if chosen else None),
        issue=(chosen.issue if chosen else None) or pages.edition_issue(resolved.edition_url),
        release_date=release,
        archived=page.archived or (chosen.archived if chosen else False),
        format="html",
        url=resolved.edition_url,
        pdf_url=page.pdf_url,
        sections=sections,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=resolved.edition_url,
            cached=cached and resolved.cached,
            as_of=_as_of(release),
            limits=" ".join(notes),
            schema_name="statcan_reference.Publication",
            lang=current_lang(),
        ),
    )


@dataclass
class _Crawl:
    pages: list[pages.Page]
    cached: bool  # every page came from the cache
    cut_short: bool  # pages were left unread at the page cap
    stopped_early: bool  # pages were left unread because enough sections matched


def _title_hits(terms: list[str], title: str) -> int:
    """How many query terms a link's title holds."""
    words = re.findall(r"[a-z0-9]+", pages.fold(title))
    return sum(1 for term in terms if any(w.startswith(term) for w in words))


def _strong(terms: list[str], page: pages.Page) -> int:
    """Pieces of `page` (see _matches) that hold every query term, about three times
    each or in their title: on 13-017-X, "provincial allocation" is answered by
    6.4 "Estimation methods - provincial and territorial estimates", not by the
    paragraphs of chapter 3 that name each word once."""
    return sum(
        1
        for distinct, score, *_ in _matches(terms, [page])
        if distinct == len(terms) and score >= 3 * len(terms)
    )


async def _crawl(
    first: pages.Page,
    edition_url: str,
    tool: str,
    *,
    terms: list[str] | None = None,
    wanted: int = 0,
) -> _Crawl:
    """The edition's pages from `first`, up to CRAWL_MAX_PAGES and CRAWL_MAX_DEPTH.

    Links whose titles hold more query terms are read first, then shallower ones,
    in the order the pages list them. With `terms`, the crawl stops once `wanted`
    pieces hold every term and no unread page has every term in its title: on
    the CPI Reference Paper, "owned accommodation" is answered by chapter 10's
    page and the chapters before it are not fetched. Pages are fetched
    CRAWL_CONCURRENCY at a time, through the rate limiter, as soon as a slot frees
    (no waiting for a whole level).
    """
    terms = terms or []
    found: list[tuple[int, pages.Page]] = [(-1, first)]  # (order queued, page)
    seen = {urlparse(first.url).path, urlparse(edition_url).path}
    queue: list[tuple[int, int, int, str]] = []  # (-title hits, depth, order, url)
    order = itertools.count()

    def enqueue(page: pages.Page, depth: int) -> None:
        for link in page.links:
            path = urlparse(link.url).path
            if path in seen:
                continue
            seen.add(path)
            heapq.heappush(queue, (-_title_hits(terms, link.title), depth, next(order), link.url))

    async def load(url: str) -> tuple[pages.Page, bool] | None:
        try:
            return await _page(url, edition_url, tool)
        except NotFound:
            return None  # a broken link inside the publication

    enqueue(first, 1)
    strong = _strong(terms, first) if terms else 0
    all_cached = True
    running: dict[asyncio.Task[tuple[pages.Page, bool] | None], tuple[int, int]] = {}

    def enough() -> bool:
        if not terms or strong < wanted:
            return False
        return not queue or -queue[0][0] < len(terms)

    # The LFS guide is one long page: its own sections may already be enough.
    stopped_early = enough()
    try:
        while True:
            while (
                queue
                and len(running) < constants.CRAWL_CONCURRENCY
                and len(found) + len(running) < constants.CRAWL_MAX_PAGES
                and not stopped_early
            ):
                _, depth, queued, url = heapq.heappop(queue)
                running[asyncio.ensure_future(load(url))] = (depth, queued)
            if not running:
                break
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                depth, queued = running.pop(task)
                result = task.result()
                if result is None:
                    continue
                page, cached = result
                all_cached &= cached
                found.append((queued, page))
                if depth < constants.CRAWL_MAX_DEPTH:
                    enqueue(page, depth + 1)
                if terms:
                    strong += _strong(terms, page)
            # Pages already requested are still read; no new ones are started.
            stopped_early = stopped_early or enough()
    finally:
        for task in running:
            task.cancel()
    unread = bool(queue)
    # In the order the pages were queued, not the order they answered, so ties
    # between equal matches always break the same way.
    read = [page for _, page in sorted(found, key=lambda item: item[0])]
    return _Crawl(read, all_cached, unread and not stopped_early, unread and stopped_early)


def _section_text(page: pages.Page, heading: pages.Heading | None) -> tuple[str, list[int]]:
    """A section's text and the offset where each of its blocks starts."""
    blocks = pages.section_blocks(page, heading)
    top = heading.level if heading else _top_level(page)
    offsets: list[int] = []
    position = 0
    for block in blocks:
        offsets.append(position)
        position += len(pages.render([block], top)) + 2
    return pages.render(blocks, top), offsets


def _subsections(
    page: pages.Page, heading: pages.Heading | None, edition_url: str
) -> list[PublicationSection]:
    if heading is None:
        return _toc(page, edition_url)
    end = len(page.blocks)
    for other in page.headings:
        if other.position > heading.position and other.level <= heading.level:
            end = other.position
            break
    return [
        PublicationSection(
            id=_heading_id(page, other, edition_url),
            title=other.title,
            level=other.level - heading.level,
            url=_heading_url(page, other),
        )
        for other in page.headings
        if heading.position < other.position < end and other.level - heading.level <= 2
    ]


def _find_heading(page: pages.Page, anchor: str) -> pages.Heading | None:
    for index, heading in enumerate(page.headings):
        if anchor in (heading.anchor, f"h{index + 1}"):
            return heading
    return None


def _terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", pages.fold(query))
    terms = [w for w in words if w not in _STOPWORDS and len(w) > 1] or words
    # A plural matches its singular: "rates" finds "rate", "rates" and "rated".
    stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in terms]
    return list(dict.fromkeys(stems))


def _score(terms: list[str], title: str, text: str) -> tuple[int, float]:
    """(distinct terms found, score) of a piece of text for the query terms."""
    words = re.findall(r"[a-z0-9]+", pages.fold(text))
    title_words = re.findall(r"[a-z0-9]+", pages.fold(title))
    distinct = 0
    score = 0.0
    for term in terms:
        hits = sum(1 for w in words if w.startswith(term))
        in_title = sum(1 for w in title_words if w.startswith(term))
        if hits or in_title:
            distinct += 1
        score += min(hits, 20) + 8 * in_title
    if len(terms) > 1:
        # The terms are stems ("gross" is "gros"), so the phrase matches each as a
        # word's start. Counted five times at most: a table that repeats "gross
        # output" in every row is not five times the answer.
        phrase = re.compile(r"\b" + r"\w*\s+".join(map(re.escape, terms)) + r"\w*")
        score += 15 * min(5, len(phrase.findall(" ".join(words))))
        if phrase.search(" ".join(title_words)):
            score += 30
    return distinct, score


def _matches(
    terms: list[str], crawled: list[pages.Page]
) -> list[tuple[int, float, pages.Page, pages.Heading | None, int]]:
    """Every piece of text with a query word: (distinct words, score, page, heading,
    index of its best block), best first.

    A piece is the text between one heading and the next of any level (or before a
    page's first heading), so a long chapter with many subsections is scored by
    each subsection, not as one block that matches everything.
    """
    candidates: list[tuple[int, float, pages.Page, pages.Heading | None, int]] = []
    for page in crawled:
        bounds: list[tuple[pages.Heading | None, int]] = [(None, 0)]
        bounds.extend((h, h.position) for h in page.headings)
        for index, (heading, begin) in enumerate(bounds):
            stop = bounds[index + 1][1] if index + 1 < len(bounds) else len(page.blocks)
            body = [i for i in range(begin, stop) if page.blocks[i].kind == "text"]
            if not body:
                continue
            label = heading.title if heading else page.title
            text = "\n".join(page.blocks[i].text for i in body)
            distinct, score = _score(terms, label, text)
            if not distinct:
                continue
            best = max(body, key=lambda i: _score(terms, "", page.blocks[i].text))
            candidates.append((distinct, score, page, heading, best))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates


def _section_result(
    page: pages.Page,
    heading: pages.Heading | None,
    edition_url: str,
    *,
    start: int,
    limit: int,
    score: float | None = None,
) -> tuple[SectionText, str]:
    text, _ = _section_text(page, heading)
    piece, end, more = pages.cut(text, start, limit)
    result = SectionText(
        id=_heading_id(page, heading, edition_url) if heading else _page_id(page, edition_url),
        title=heading.title if heading else page.title,
        url=_heading_url(page, heading) if heading else page.url,
        text=piece,
        start_char=start,
        next_start_char=end if more else None,
        total_chars=len(text),
        score=score,
    )
    return result, text


def _word_text(page: pages.Page) -> str:
    """A page's text as its folded words, one space apart, for finding a passage."""
    return " ".join(re.findall(r"[a-z0-9]+", pages.fold(" ".join(b.text for b in page.blocks))))


def _read_already(text: str, read: list[str]) -> bool:
    """The first ten words of `text` (a PDF paragraph) are on one of the pages `read`
    (_word_text): its HTML page was searched already."""
    words = re.findall(r"[a-z0-9]+", pages.fold(text))[:10]
    if len(words) < 5:
        return False
    passage = " " + " ".join(words) + " "
    return any(passage in f" {page} " for page in read)


async def get_section_text(
    publication: str,
    *,
    section: str | None = None,
    query: str | None = None,
    edition: str | None = None,
    start_char: int = 0,
    max_chars: int = constants.TEXT_MAX_CHARS_DEFAULT,
    limit: int = constants.QUERY_MATCHES_DEFAULT,
    lang: str = "en",
) -> PublicationText:
    """The text of one section of a publication, or of the sections matching a query."""
    use_lang(lang)
    tool = "get_section_text"
    _check_text_args(tool, max_chars, start_char, limit)
    section = section.strip() if section and section.strip() else None
    query = query.strip() if query and query.strip() else None
    if section and query:
        raise InvalidInput(
            say(
                f"{_context(tool)}: pass section (one section) or query (search the "
                "edition), not both.",
                f"{_context(tool)} : passez section (une section) ou query (recherche dans "
                "l'édition), pas les deux.",
            )
        )
    resolved = await _resolve(publication, edition, lang, tool)
    catalogue = resolved.catalogue
    chosen = resolved.edition
    common: dict[str, Any] = {
        "catalogue_number": catalogue.catalogue_number if catalogue else None,
        "issue": (chosen.issue if chosen else None) or pages.edition_issue(resolved.edition_url),
        "edition_url": resolved.edition_url,
        "query": query,
    }
    edition_url = resolved.edition_url
    document: pdf.PdfText | None = None
    if resolved.pdf_only:
        document, all_cached = await _pdf(edition_url, tool, lang)
        main = document.page
        if section is not None:
            section = _pdf_section(section)
    else:
        main, all_cached = await _page(edition_url, edition_url, tool)
    all_cached &= resolved.cached
    release = main.release_date or (chosen.release_date if chosen else None)
    results: list[SectionText] = []
    subsections: list[PublicationSection] = []
    notes: list[str] = []
    pages_read = 1

    if query is None:
        target, heading = main, None
        if section is not None:
            target, heading, cached, read = await _locate(section, main, edition_url, lang, tool)
            all_cached &= cached
            pages_read += read
        elif resolved.focus_url and document is None:
            page_url, _, anchor = resolved.focus_url.partition("#")
            target, cached = await _page(page_url, edition_url, tool)
            all_cached &= cached
            pages_read += 1
            heading = _find_heading(target, anchor) if anchor else None
        result, text = _section_result(
            target, heading, edition_url, start=start_char, limit=max_chars
        )
        results.append(result)
        if document is not None and heading is None:
            subsections = _pdf_toc(document, edition_url)[: constants.SECTIONS_LISTED_MAX]
        else:
            subsections = _subsections(target, heading, edition_url)
        if result.next_start_char is not None:
            notes.append(
                say(
                    f"Text cut at {max_chars} characters of {len(text)}: pass "
                    f"start_char={result.next_start_char} to read on.",
                    f"Texte coupé à {max_chars} caractères sur {len(text)} : passez "
                    f"start_char={result.next_start_char} pour lire la suite.",
                )
            )
    else:
        terms = _terms(query)
        fallback: pdf.PdfText | None = None  # the whole-edition PDF, when searched too
        if document is not None:
            crawled = [main]
        else:
            whole_url = main.pdf_url if (main.pdf_url or "").lower().endswith(".pdf") else None
            crawl = await _crawl(main, edition_url, tool, terms=terms, wanted=limit)
            crawled = crawl.pages
            all_cached &= crawl.cached
            pages_read = len(crawled)
            if crawl.cut_short and whole_url:
                # 13-017-X's 2008 edition has 146 pages, past CRAWL_MAX_PAGES, and one
                # PDF of all of them (3.3 MB, 297 pages): one download searches every
                # page. Pieces of the PDF whose text is on a page already read give
                # way to that page's own piece, so citations stay HTML-first.
                whole: pdf.PdfText | None = None
                try:
                    whole, whole_cached = await _pdf(whole_url, tool, lang)
                    all_cached &= whole_cached
                except (NotFound, UpstreamError, UpstreamUnavailable):
                    whole = None
                if whole is not None:
                    fallback = whole
                    notes.append(
                        say(
                            f"The edition has more pages than the {len(crawled)} read: its "
                            f"whole PDF ({main.pdf_url}, {whole.page_count} pages) was "
                            "searched too. Matches from it cite the PDF page "
                            "(#page=N): read on with publication=<that PDF>, "
                            "section='page=N'.",
                            f"L'édition a plus de pages que les {len(crawled)} lues : son PDF "
                            f"complet ({main.pdf_url}, {whole.page_count} pages) a aussi été "
                            "parcouru. Les résultats qui en viennent citent la page du PDF "
                            "(#page=N) : lisez la suite avec publication=<ce PDF>, "
                            "section='page=N'.",
                        )
                    )
            if crawl.cut_short and fallback is None:
                notes.append(
                    say(
                        f"Searched {len(crawled)} pages of the edition (those whose titles "
                        "hold the query's words first); more exist.",
                        f"Recherche dans {len(crawled)} pages de l'édition (d'abord celles "
                        "dont le titre contient les mots cherchés) ; il y en a d'autres.",
                    )
                )
                if main.pdf_url:
                    notes.append(
                        say(
                            f"To search every page, pass the edition's PDF as publication "
                            f"({main.pdf_url}).",
                            f"Pour chercher dans toutes les pages, passez le PDF de "
                            f"l'édition comme publication ({main.pdf_url}).",
                        )
                    )
            elif crawl.stopped_early:
                notes.append(
                    say(
                        f"Searched {len(crawled)} pages of the edition: the pages whose "
                        "titles hold the query's words were read first, and the search "
                        f"stopped once {limit} sections held every word. Ask for a section "
                        "by title, or use other words, to look elsewhere.",
                        f"Recherche dans {len(crawled)} pages de l'édition : celles dont le "
                        "titre contient les mots cherchés ont été lues d'abord, et la "
                        f"recherche s'est arrêtée dès que {limit} sections contenaient tous "
                        "les mots. Demandez une section par son titre, ou d'autres mots, "
                        "pour chercher ailleurs.",
                    )
                )
        budget = max(200, max_chars // limit)
        searched = crawled + ([fallback.page] if fallback else [])
        read_text = [_word_text(page) for page in crawled] if fallback else []
        for distinct, score, page, heading, best in _matches(terms, searched):
            if len(results) == limit:
                break
            in_pdf = fallback is not None and page is fallback.page
            if in_pdf and _read_already(page.blocks[best].text, read_text):
                continue  # the same text on an HTML page read: that piece stands for it
            _, offsets = _section_text(page, heading)
            first = heading.position if heading else 0
            begin = offsets[best - first] if 0 <= best - first < len(offsets) else 0
            result, _ = _section_result(
                page,
                heading,
                page.url if in_pdf else edition_url,
                start=begin,
                limit=budget,
                score=round(score + 100 * distinct, 1),
            )
            results.append(result)
        if not results:
            notes.append(
                say(
                    f"No section of this edition contains {query!r}. Try other or fewer "
                    "words, or list its sections with statcan_reference_get_publication.",
                    f"Aucune section de cette édition ne contient {query!r}. Essayez d'autres "
                    "mots ou moins de mots, ou listez ses sections avec "
                    "statcan_reference_get_publication.",
                )
            )
        else:
            notes.append(
                say(
                    "Each match is an excerpt starting at its best paragraph: pass its id "
                    "as section= (with start_char=next_start_char) to read on, or "
                    "start_char=0 for the section from its heading.",
                    "Chaque résultat est un extrait qui commence au meilleur paragraphe : "
                    "passez son id dans section= (avec start_char=next_start_char) pour lire "
                    "la suite, ou start_char=0 pour la section depuis son titre.",
                )
            )
    if query is not None:
        notes[0:0] = _query_hints(query, common["catalogue_number"])
    if document is not None:
        notes.insert(0, _pdf_note(document))
        pages_read = document.pages_read
    older = _older_note(resolved)
    if older:
        notes.append(older)
    return PublicationText(
        **common,
        title=(catalogue.title if catalogue else None) or main.title or "PDF",
        release_date=release,
        archived=main.archived or (chosen.archived if chosen else False),
        format="pdf" if document is not None else "html",
        pdf_url=main.pdf_url,
        sections=results,
        subsections=subsections,
        pages_read=pages_read,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=results[0].url if results else edition_url,
            cached=all_cached,
            as_of=_as_of(release),
            limits=" ".join(notes) or None,
            schema_name="statcan_reference.PublicationText",
            lang=current_lang(),
        ),
    )


_PAGE_KEY = re.compile(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)*", re.IGNORECASE)


async def _locate(
    section: str, main: pages.Page, edition_url: str, lang: str, tool: str
) -> tuple[pages.Page, pages.Heading | None, bool, int]:
    """The page and heading a `section` argument names: (page, heading, cached, pages read).

    Tried in order: a URL; an id from get_publication ('a3', 'chap-10', 'chap-10#a2');
    a title on the main page, then on every page of the edition (exact, then a part).
    """
    if re.match(r"^(https?://|www)", section, re.IGNORECASE):
        url = pages.with_lang(_checked_url(section, tool), lang)
        page_url, _, anchor = url.partition("#")
        if _same_page(page_url, edition_url):
            return main, _find_heading(main, anchor) if anchor else None, True, 0
        page, cached = await _page(page_url, edition_url, tool)
        return page, _find_heading(page, anchor) if anchor else None, cached, 1

    if section.lower() == MAIN_PAGE_ID:
        return main, None, True, 0
    key, has_anchor, anchor = section.partition("#")
    if has_anchor:
        page, cached, read = main, True, 0
        if key:
            page, cached = await _page(pages.page_url_for_key(key, edition_url), edition_url, tool)
            read = 1
        heading = _find_heading(page, anchor)
        if heading is not None:
            return page, heading, cached, read
    else:
        heading = _find_heading(main, section)
        if heading is not None:
            return main, heading, True, 0
        for link in main.links:
            if pages.page_key(link.url, edition_url) == section:
                page, cached = await _page(link.url, edition_url, tool)
                return page, None, cached, 1

    wanted = pages.fold(section)

    def by_title(candidates: list[pages.Page]) -> tuple[pages.Page, pages.Heading | None] | None:
        for exact in (True, False):
            for page in candidates:
                for heading in page.headings:
                    title = pages.fold(heading.title)
                    if (title == wanted) if exact else (wanted in title):
                        return page, heading
                if page is not candidates[0] and (
                    (pages.fold(page.title) == wanted)
                    if exact
                    else (wanted in pages.fold(page.title))
                ):
                    return page, None
        return None

    found = by_title([main])
    if found is not None and pages.fold(found[1].title if found[1] else "") == wanted:
        return found[0], found[1], True, 0
    # A chapter's own page ("Chapter 8 – Weights and Basket Updates") before a
    # heading elsewhere that only contains the words.
    for exact in (True, False):
        for link in main.links:
            title = pages.fold(link.title)
            if (title == wanted) if exact else (wanted in title):
                page, cached = await _page(link.url, edition_url, tool)
                return page, None, cached, 1
    if found is not None:
        return found[0], found[1], True, 0
    # A page id from a query's results ("178", "themes/ch02/5213339"), deeper
    # than the main page's own links.
    if (
        not has_anchor
        and not edition_url.lower().endswith(".pdf")
        and _PAGE_KEY.fullmatch(section)
        and re.search(r"[\d/]", section)
    ):
        try:
            page, cached = await _page(
                pages.page_url_for_key(section, edition_url), edition_url, tool
            )
        except (NotFound, UpstreamError):
            pass
        else:
            return page, None, cached, 1
    crawl = await _crawl(main, edition_url, tool)
    found = by_title(crawl.pages)
    if found is not None:
        return found[0], found[1], crawl.cached, len(crawl.pages) - 1
    ids = ", ".join(entry.id for entry in _toc(main, edition_url)[:20])
    raise NotFound(
        say(
            f"{_context(tool)}: no section {section!r} in {edition_url}. Its sections: {ids}. "
            "Or search the text with query=.",
            f"{_context(tool)} : aucune section {section!r} dans {edition_url}. Ses sections : "
            f"{ids}. Ou cherchez dans le texte avec query=.",
        )
    )
