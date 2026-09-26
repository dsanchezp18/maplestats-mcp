"""Client for the 2006-2016 census data tables, parsed from www12 HTML."""

from __future__ import annotations

import asyncio
import html
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.statcan.census_tables import constants
from maplestats_mcp.modules.statcan.census_tables.schemas import (
    CensusTable,
    CensusTableDownloads,
    CensusTableSearch,
    Download,
)
from maplestats_mcp.shared import cache as cache_module
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
# Download links 302-redirect to the ZIP; HEAD needs redirects followed.
_HEAD_CLIENT = new_client(timeout=60.0, follow_redirects=True)
_PID = re.compile(r"PID=(\d+)")
# Theme pages fetched at once. Crawling every theme in parallel made
# www12 drop connections (2026-09-25: a 2006 search failed while each
# page answered alone in under a second).
_CRAWL = asyncio.Semaphore(4)
_PAGE_ATTEMPTS = 2


def _release(key: str) -> constants.Release:
    if key not in constants.RELEASES:
        raise InvalidInput(f"release must be one of {sorted(constants.RELEASES)}, got {key!r}.")
    return constants.RELEASES[key]


async def _page(url: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        # StatCan answers retired pages with a 302 to its "page not found"
        # notice (the 2011 Census tabulations since 2026-09, checked 2026-09-25).
        if "srvmsg404" in exc.response.headers.get("location", ""):
            raise NotFound(
                f"census tables: StatCan answers {url} with its 'page not found' notice. "
                "The 2011 Census tabulations have been retired this way (2011 NHS tables "
                "remain); for other releases it may be a short outage, so retry later. "
                "Copies of retired tables are on Borealis: use borealis_search_ivt "
                "(e.g. 'census 2011 language')."
            ) from exc
        raise UpstreamError(
            f"census tables: {url} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"census tables: {url} could not be reached.") from exc
    return response.text


async def _crawl_page(url: str) -> str:
    """A theme page, retried once, a few at a time."""
    async with _CRAWL:
        for attempt in range(1, _PAGE_ATTEMPTS + 1):
            try:
                return await _page(url)
            except UpstreamUnavailable:
                if attempt == _PAGE_ATTEMPTS:
                    raise
        raise AssertionError("unreachable")


def theme_urls(index_html: str, base: str) -> dict[str, str]:
    """Theme name -> ungrouped list URL, from the index page's own links."""
    soup = BeautifulSoup(index_html, "html.parser")
    themes: dict[str, str] = {}
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        href = html.unescape(str(link["href"]))
        match = re.search(r"THEME=(\d+)", href)
        if "Lp-eng.cfm" not in href or not match or match.group(1) == "0":
            continue
        # GRP=0 lists every table as its own row instead of one group per page.
        href = re.sub(r"GRP=\d+", "GRP=0", href)
        themes.setdefault(" ".join(link.get_text(" ").split()), urljoin(base, href))
    if themes:
        return themes
    # 2006: the index's list links are per variable (THEME=0); the theme ids
    # appear on other links, so reuse a list link as the URL template.
    template = next(
        (
            html.unescape(str(a["href"]))
            for a in soup.find_all("a", href=True)
            if isinstance(a, Tag) and "Lp-eng.cfm" in str(a["href"])
        ),
        None,
    )
    if template is None:
        return themes
    template = re.sub(r"VNAME[EF]=[^&]*", lambda m: m.group(0).split("=")[0] + "=", template)
    # APATH=7 is the by-variable listing; APATH=3 lists a theme's tables.
    template = re.sub(r"GRP=\d+", "GRP=0", re.sub(r"APATH=\d+", "APATH=3", template))
    names = {
        m.group(1): " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())
        for m in re.finditer(r'THEME=(\d+)[^"]*"[^>]*>(.*?)</a>', index_html, re.DOTALL)
    }
    for theme_id in sorted(set(re.findall(r"THEME=(\d+)", index_html)) - {"0"}):
        name = html.unescape(names.get(theme_id) or f"Theme {theme_id}")
        themes[name] = urljoin(base, re.sub(r"THEME=\d+", f"THEME={theme_id}", template))
    return themes


def parse_list_page(
    page_html: str, release: str, theme: str, url: str
) -> tuple[list[CensusTable], str | None]:
    soup = BeautifulSoup(page_html, "html.parser")
    tables: list[CensusTable] = []
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        pid_match = _PID.search(str(row))
        if len(cells) < 4 or not pid_match:
            continue
        tables.append(
            CensusTable(
                release=release,
                pid=pid_match.group(1),
                catalogue_number=" ".join(cells[1].get_text(" ").split()),
                title=" ".join(cells[2].get_text(" ").split()),
                theme=theme,
                has_ivt="Download.cfm?PID=" in str(cells[3]),
                page_url=url,
            )
        )
    next_link = soup.find("a", href=re.compile(r"StartRow=\d+"), string=re.compile(r"Next|Suivant"))
    next_url = (
        urljoin(url, html.unescape(str(next_link["href"]))) if isinstance(next_link, Tag) else None
    )
    return tables, next_url


async def _catalogue(key: str) -> tuple[list[CensusTable], list[str], bool]:
    release = _release(key)
    base = f"{constants.HOST}{release.path}"

    async def crawl() -> tuple[list[CensusTable], list[str]]:
        themes = theme_urls(await _page(f"{base}index-eng.cfm"), base)
        if not themes:
            raise UpstreamError(
                f"census tables: no themes found for {release.label}; layout changed?"
            )

        async def one_theme(name: str, url: str) -> list[CensusTable] | None:
            found: list[CensusTable] = []
            next_url: str | None = url
            try:
                for _ in range(constants.MAX_PAGES_PER_THEME):
                    if next_url is None:
                        break
                    rows, next_url = parse_list_page(
                        await _crawl_page(next_url), key, name, next_url
                    )
                    found.extend(rows)
            except UpstreamUnavailable:
                return None  # reported as a skipped theme, not a failed search
            return found

        results = await asyncio.gather(*(one_theme(n, u) for n, u in themes.items()))
        skipped = [name for name, batch in zip(themes, results, strict=True) if batch is None]
        if len(skipped) == len(themes):
            raise UpstreamUnavailable(f"census tables: no {release.label} theme page answered.")
        unique: dict[str, CensusTable] = {}
        for table in (t for batch in results if batch for t in batch):
            unique.setdefault(table.pid, table)
        return list(unique.values()), skipped

    cache_key = f"census_tables:{key}"
    (tables, skipped), cached = await cached_fetch(
        cache_key, constants.CATALOGUE_TTL_SECONDS, crawl
    )
    if skipped:
        # A partial crawl is not kept, so the next call retries the gaps.
        cache_module.forget(cache_key)
    return tables, skipped, cached


async def search(
    query: str = "", *, release: str = "2016", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> CensusTableSearch:
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    tables, skipped, cached = await _catalogue(release)
    words = query.lower().split()
    matched = [
        t
        for t in tables
        if all(w in f"{t.title} {t.catalogue_number} {t.theme}".lower() for w in words)
    ]
    return CensusTableSearch(
        release=release,
        query=query,
        tables=matched[:limit],
        total_matched=len(matched),
        total_tables=len(tables),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.HOST}{_release(release).path}index-eng.cfm",
            cached=cached,
            schema_name="census_tables.CensusTableSearch",
            freshness="archived census releases; table list cached 7 days",
            limits="English titles; 2021 census tables are NDM tables, use wds_search_cubes",
            coverage=(
                f"themes that did not answer and were skipped: {', '.join(skipped)}"
                if skipped
                else None
            ),
        ),
    )


async def _head(url: str) -> tuple[bool, int | None, bool]:
    """(available, size, service offline) for one download link."""
    await _LIMITER.acquire()
    try:
        response = await _HEAD_CLIENT.head(url)
    except httpx.TooManyRedirects:
        return False, None, True
    except httpx.HTTPError:
        return False, None, False
    # Seen 2026-09-24 evening: every download link, including ones that had
    # worked hours earlier, redirected in a loop or to srvmsg404.html ("the
    # page is temporarily offline for updating"). That is an outage, not a
    # missing table.
    offline = "/srvmsg/" in str(response.url)
    # CSV/SDMX come back as ZIPs; the IVT link serves the raw .ivt file as
    # application/x-beyond2020 and reports Content-Length 0 to HEAD.
    content_type = response.headers.get("content-type", "")
    ok = response.status_code == 200 and ("zip" in content_type or "beyond2020" in content_type)
    length = int(response.headers.get("content-length") or 0)
    return ok, (length or None) if ok else None, offline


async def get_downloads(pid: str, *, release: str = "2016") -> CensusTableDownloads:
    if not pid.strip().isdigit():
        raise InvalidInput(f"pid must be digits, got {pid!r}.")
    base = f"{constants.HOST}{_release(release).path}"
    urls = {
        "csv": f"{base}CompDataDownload.cfm?LANG=E&PID={pid}&OFT=CSV",
        "sdmx": f"{base}OpenDataDownload.cfm?PID={pid}",
        "ivt": f"{base}Download.cfm?PID={pid}",
    }
    checks = await asyncio.gather(*(_head(u) for u in urls.values()))
    downloads = [
        Download(format=fmt, url=url, available=ok, size_bytes=size)
        for (fmt, url), (ok, size, _) in zip(urls.items(), checks, strict=True)
    ]
    if not any(d.available for d in downloads):
        # The 2011 Census tabulations answer this way for good (checked
        # 2026-09-25 while 2006, 2011 NHS and 2016 downloads worked).
        if release == "2011" and any(offline for _, _, offline in checks):
            raise NotFound(
                f"StatCan has retired the 2011 Census tabulations, including PID {pid}. "
                "Copies are on Borealis: use borealis_search_ivt (e.g. 'census 2011 language')."
            )
        if any(offline for _, _, offline in checks):
            raise UpstreamUnavailable(
                "StatCan's census download service is temporarily offline (it redirects to its "
                "'temporarily offline for updating' page). Try again later."
            )
        raise NotFound(f"No downloads found for PID {pid} in the {release} release.")
    by_format = {d.format: d.available for d in downloads}
    ivt_only = by_format["ivt"] and not (by_format["csv"] or by_format["sdmx"])
    note = None
    if ivt_only:
        note = (
            "Only a Beyond 20/20 IVT file exists. Read it in R with mountainMath's canivt "
            '(remotes::install_github("mountainMath/canivt")): '
            f'download.file("{urls["ivt"]}", "table_{pid}.ivt", mode = "wb"); '
            f'tab <- canivt::read_ivt("table_{pid}.ivt"); '
            "canivt::ivt_tidy(tab)"
        )
    return CensusTableDownloads(
        release=release,
        pid=pid,
        downloads=downloads,
        ivt_only=ivt_only,
        ivt_note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=urls["csv"],
            cached=False,
            schema_name="census_tables.CensusTableDownloads",
            limits="availability checked with HEAD requests; files are ZIPs",
        ),
    )
