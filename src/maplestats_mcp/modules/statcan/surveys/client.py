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

import re
import unicodedata

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.statcan.surveys import constants
from maplestats_mcp.modules.statcan.surveys.schemas import (
    RdcHolding,
    RdcSearchResult,
    RtraDataset,
    RtraSearchResult,
    SurveyLink,
    SurveyListing,
    SurveyListResult,
    SurveyMetadata,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

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
    response = await _client.get(_list_url(lang))
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
            response = await _client.get(url)
            response.raise_for_status()
            if _has_survey_links(response.text):
                return response.text

            # An empty directory means the session cookie expired (the page
            # renders no links without one): re-warm once rather than cache
            # "no surveys" for the whole TTL.
            await _warm_up_list(lang, force=True)
            response = await _client.get(url)
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
            return await _client.get(url)
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


# --- Microdata holdings: Research Data Centres (RDC) and RTRA ---------------
#
# Checked live 2026-10-02. Both pages are server-rendered tables:
# - RDC: one table, 352 rows (record number | survey, with its cycles as a
#   list | acronym). 194 distinct record numbers: 8006 is a generic bucket
#   shared by about a hundred holdings, a cell can hold several numbers
#   separated by <br> and some hold "N/A"; the acronym cell is a <p> in some
#   rows and a <ul> in others; 84 rows have no link at all; the link case
#   varies (p2SV.pl and p2sv.pl).
# - RTRA: 70 <details> blocks (one per survey, under h2 sections such as
#   "Social data"), each with a "Survey details" link list and one table per
#   dataset, captioned with the cycle. 332 tables, 357 dataset rows. Links
#   use either SDDS= (a survey record) or Id= (one cycle's instance id).


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("œ", "oe"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _matches(words: list[str], haystack: str) -> bool:
    folded = _fold(haystack)
    return all(word in folded for word in words)


def _check_lang_and_limit(tool: str, lang: str, limit: int) -> None:
    if lang not in ("en", "fr"):
        raise InvalidInput(
            f"statcan_surveys:{tool}: lang must be one of ('en', 'fr'), got {lang!r}."
        )
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_surveys:{tool}: limit must be between 1 and "
            f"{constants.SEARCH_LIMIT_MAX}, got {limit}."
        )


async def _fetch_page(url: str, tool: str, cache_key: str) -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(f"statcan_surveys:{tool} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"statcan_surveys:{tool} did not respond in time. Try again shortly."
            ) from exc
        return response.content.decode("utf-8", errors="replace")

    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_HOLDINGS_SECONDS, fetch)
    return html, was_cached


def _record_numbers(cell: Tag) -> list[int]:
    # <br>-separated numbers in one <p>; "N/A" entries are skipped.
    tokens = cell.get_text("|", strip=True).split("|")
    return [int(token) for token in tokens if token.isdecimal()]


def _parse_rdc(html: str) -> list[RdcHolding]:
    soup = BeautifulSoup(html, "html.parser")
    holdings: list[RdcHolding] = []
    for row in soup.find_all("tr"):
        record_cell = row.find("th", attrs={"scope": "row"})
        cells = row.find_all("td", recursive=False)
        if not isinstance(record_cell, Tag) or len(cells) < 2:
            continue
        name_paragraph = cells[0].find("p")
        if not isinstance(name_paragraph, Tag):
            continue
        link = name_paragraph.find("a")
        href = link.get("href") if isinstance(link, Tag) else None
        acronym = _clean(cells[1].get_text(" ", strip=True))
        holdings.append(
            RdcHolding(
                record_numbers=_record_numbers(record_cell),
                name=_clean(name_paragraph.get_text(" ", strip=True)),
                acronym=acronym or None,
                cycles=[_clean(li.get_text(" ", strip=True)) for li in cells[0].find_all("li")],
                detail_url=href if isinstance(href, str) else None,
            )
        )
    return holdings


async def search_rdc_holdings(
    query: str = "", *, lang: str = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> RdcSearchResult:
    """Search the datasets available at StatCan's Research Data Centres."""
    _check_lang_and_limit("search_rdc_holdings", lang, limit)
    url = constants.RDC_URL_FR if lang == "fr" else constants.RDC_URL_EN
    html, was_cached = await _fetch_page(url, "search_rdc_holdings", f"statcan-surveys:rdc:{lang}")
    holdings = _parse_rdc(html)
    if not holdings:
        raise UpstreamError(
            "statcan_surveys:search_rdc_holdings: the page rendered no table rows. "
            "Try again shortly."
        )
    words = re.findall(r"\w+", _fold(query))
    matched = [
        h
        for h in holdings
        if _matches(
            words,
            f"{h.name} {h.acronym or ''} {' '.join(h.cycles)} "
            f"{' '.join(str(n) for n in h.record_numbers)}",
        )
    ]
    page = matched[:limit]
    return RdcSearchResult(
        query=query,
        holdings=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_surveys.RdcSearchResult",
            limits=(
                "A holdings list, not data: RDC access needs an approved project and security "
                "clearance. Record number 8006 is a generic bucket, not one survey."
            ),
        ),
    )


def _survey_link(anchor: Tag) -> SurveyLink | None:
    href = anchor.get("href")
    if not isinstance(href, str):
        return None
    sdds = re.search(r"SDDS=(\d+)", href)
    instance = re.search(r"[?&]Id=(\d+)", href)
    return SurveyLink(
        name=_clean(anchor.get_text(" ", strip=True)),
        url=href,
        sdds_id=int(sdds.group(1)) if sdds else None,
        instance_id=int(instance.group(1)) if instance else None,
    )


def _parse_rtra(html: str) -> list[RtraDataset]:
    soup = BeautifulSoup(html, "html.parser")
    datasets: list[RtraDataset] = []
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not isinstance(summary, Tag):
            continue
        heading = details.find_previous("h2")
        category = _clean(heading.get_text(" ", strip=True)) if isinstance(heading, Tag) else None
        links: list[SurveyLink] = []
        link_list = details.find("ul")
        if isinstance(link_list, Tag):
            for anchor in link_list.find_all("a"):
                link = _survey_link(anchor)
                if link is not None:
                    links.append(link)
        for table in details.find_all("table"):
            caption = table.find("caption")
            label = _clean(caption.get_text(" ", strip=True)) if isinstance(caption, Tag) else None
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                # The header row has only <th> cells; data rows have <td>.
                if len(cells) < 5 or not row.find("td"):
                    continue
                texts = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
                datasets.append(
                    RtraDataset(
                        category=category,
                        survey=_clean(summary.get_text(" ", strip=True)),
                        table_label=label,
                        tag_name=texts[0],
                        dataset_name=texts[1] or None,
                        rounding_base=int(texts[2]) if texts[2].isdecimal() else None,
                        weight_name=texts[3] or None,
                        deleted_variables=texts[4].split(),
                        survey_links=links,
                    )
                )
    return datasets


async def search_rtra_datasets(
    query: str = "",
    *,
    lang: str = "en",
    deleted_variable: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> RtraSearchResult:
    """Search the datasets StatCan offers through Real Time Remote Access (RTRA)."""
    _check_lang_and_limit("search_rtra_datasets", lang, limit)
    url = constants.RTRA_URL_FR if lang == "fr" else constants.RTRA_URL_EN
    html, was_cached = await _fetch_page(
        url, "search_rtra_datasets", f"statcan-surveys:rtra:{lang}"
    )
    datasets = _parse_rtra(html)
    if not datasets:
        raise UpstreamError(
            "statcan_surveys:search_rtra_datasets: the page rendered no dataset tables. "
            "Try again shortly."
        )
    words = re.findall(r"\w+", _fold(query))
    wanted = deleted_variable.strip().upper() if deleted_variable else None
    matched = [
        d
        for d in datasets
        if _matches(
            words,
            f"{d.category or ''} {d.survey} {d.table_label or ''} {d.tag_name} "
            f"{d.dataset_name or ''} {d.weight_name or ''}",
        )
        and (wanted is None or wanted in (v.upper() for v in d.deleted_variables))
    ]
    page = matched[:limit]
    return RtraSearchResult(
        query=query,
        datasets=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_surveys.RtraSearchResult",
            limits=(
                "A list of RTRA datasets and their disclosure settings, not the data: RTRA "
                "runs on StatCan's server for registered users and returns rounded counts."
            ),
        ),
    )
