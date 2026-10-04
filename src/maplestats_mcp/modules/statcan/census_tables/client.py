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
from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    CloudflareChallenge,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import get_raw, new_client, send_with_retry
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
# Download links 302-redirect to the ZIP; HEAD needs redirects followed.
_HEAD_CLIENT = new_client(timeout=60.0, follow_redirects=True)
_PID = re.compile(r"PID=(\d+)")
# Theme pages fetched at once. Fetching every theme in parallel made
# www12 drop connections (2026-09-25: a 2006 search failed while each
# page answered alone in under a second).
_PAGE_SLOTS = asyncio.Semaphore(4)
_PAGE_ATTEMPTS = 2


def _release(key: str, lang: str = "en") -> constants.Release:
    if key not in constants.RELEASES:
        raise InvalidInput(
            say(
                f"release must be one of {sorted(constants.RELEASES)}, got {key!r}.",
                f"release doit être l'une des valeurs {sorted(constants.RELEASES)}, reçu {key!r}.",
                lang,
            )
        )
    return constants.RELEASES[key]


async def _page(url: str, lang: str = "en") -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except CloudflareChallenge as exc:
        # The shared challenge text is English; the French note says the same.
        raise CloudflareChallenge(
            say(
                f"census tables: {exc} {constants.BLOCKED_NOTE}",
                f"tableaux du recensement : {constants.BLOCKED_NOTE_FR}",
                lang,
            )
        ) from exc
    except httpx.HTTPStatusError as exc:
        # StatCan answers retired pages with a 302 to its "page not found"
        # notice (the 2011 Census tabulations since 2026-09, checked 2026-09-25).
        if "srvmsg404" in exc.response.headers.get("location", ""):
            raise NotFound(
                say(
                    f"census tables: StatCan answers {url} with its 'page not found' notice. "
                    "The 2011 Census tabulations have been retired this way (2011 NHS tables "
                    "remain); for other releases it may be a short outage, so retry later. "
                    "Copies of retired tables are on Borealis: use borealis_search_ivt "
                    "(e.g. 'census 2011 language').",
                    f"tableaux du recensement : Statistique Canada répond à {url} par son avis "
                    "« page introuvable ». Les totalisations du Recensement de 2011 ont été "
                    "retirées de cette façon (les tableaux de l'ENM de 2011 restent) ; pour les "
                    "autres diffusions, il peut s'agir d'une brève panne, alors réessayez plus "
                    "tard. Des copies des tableaux retirés sont dans Borealis : utilisez "
                    "borealis_search_ivt (p. ex. « census 2011 language »).",
                    lang,
                )
            ) from exc
        status = exc.response.status_code
        if status == 403:
            raise UpstreamUnavailable(
                say(
                    f"census tables: {url} was refused (HTTP 403). {constants.BLOCKED_NOTE}",
                    f"tableaux du recensement : {url} a été refusé (HTTP 403). "
                    f"{constants.BLOCKED_NOTE_FR}",
                    lang,
                )
            ) from exc
        if status == 429 or status >= 500:
            raise UpstreamUnavailable(
                say(
                    f"census tables: {url} returned HTTP {status}. Try again shortly.",
                    f"tableaux du recensement : {url} a renvoyé HTTP {status}. Réessayez sous peu.",
                    lang,
                )
            ) from exc
        raise UpstreamError(
            say(
                f"census tables: {url} returned HTTP {status}.",
                f"tableaux du recensement : {url} a renvoyé HTTP {status}.",
                lang,
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(
                f"census tables: {url} could not be reached.",
                f"tableaux du recensement : {url} est injoignable.",
                lang,
            )
        ) from exc
    return response.text


async def _fetch_page(url: str, lang: str = "en") -> str:
    """A theme page, retried once, a few at a time."""
    async with _PAGE_SLOTS:
        for attempt in range(1, _PAGE_ATTEMPTS + 1):
            try:
                return await _page(url, lang)
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


async def _catalogue(key: str, lang: str = "en") -> tuple[list[CensusTable], list[str], bool]:
    release = _release(key, lang)
    base = f"{constants.HOST}{release.path}"

    async def walk_pages() -> tuple[list[CensusTable], list[str]]:
        themes = theme_urls(await _page(f"{base}index-eng.cfm", lang), base)
        if not themes:
            raise UpstreamError(
                say(
                    f"census tables: no themes found for {release.label}; layout changed?",
                    f"tableaux du recensement : aucun thème trouvé pour {release.label} ; "
                    "la mise en page a-t-elle changé ?",
                    lang,
                )
            )

        async def one_theme(name: str, url: str) -> list[CensusTable] | None:
            found: list[CensusTable] = []
            next_url: str | None = url
            try:
                for _ in range(constants.MAX_PAGES_PER_THEME):
                    if next_url is None:
                        break
                    rows, next_url = parse_list_page(
                        await _fetch_page(next_url, lang), key, name, next_url
                    )
                    found.extend(rows)
            except UpstreamUnavailable:
                return None  # reported as a skipped theme, not a failed search
            return found

        results = await asyncio.gather(*(one_theme(n, u) for n, u in themes.items()))
        skipped = [name for name, batch in zip(themes, results, strict=True) if batch is None]
        if len(skipped) == len(themes):
            raise UpstreamUnavailable(
                say(
                    f"census tables: no {release.label} theme page answered.",
                    f"tableaux du recensement : aucune page de thème de {release.label} "
                    "n'a répondu.",
                    lang,
                )
            )
        unique: dict[str, CensusTable] = {}
        for table in (t for batch in results if batch for t in batch):
            unique.setdefault(table.pid, table)
        return list(unique.values()), skipped

    cache_key = f"census_tables:{key}"
    (tables, skipped), cached = await cached_fetch(
        cache_key, constants.CATALOGUE_TTL_SECONDS, walk_pages
    )
    if skipped:
        # A partial walk is not kept, so the next call retries the gaps.
        cache_module.forget(cache_key)
    return tables, skipped, cached


async def search(
    query: str = "",
    *,
    release: str = "2016",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> CensusTableSearch:
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
                f"limit doit être entre 1 et {constants.SEARCH_LIMIT_MAX}, reçu {limit}.",
                lang,
            )
        )
    tables, skipped, cached = await _catalogue(release, lang)
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
            url=f"{constants.HOST}{_release(release, lang).path}index-eng.cfm",
            cached=cached,
            schema_name="census_tables.CensusTableSearch",
            freshness=say(
                "archived census releases; table list cached 7 days",
                "diffusions archivées du recensement ; liste des tableaux en cache 7 jours",
                lang,
            ),
            limits=say(
                "English titles; 2021 census tables are NDM tables, use wds_search_cubes",
                "titres offerts en anglais seulement ; les tableaux du Recensement de 2021 "
                "sont des tableaux de la base de données principale, utilisez wds_search_cubes",
                lang,
            ),
            coverage=(
                say(
                    f"themes that did not answer and were skipped: {', '.join(skipped)}",
                    f"thèmes qui n'ont pas répondu et ont été omis : {', '.join(skipped)}",
                    lang,
                )
                if skipped
                else None
            ),
            lang=lang,
        ),
    )


async def _head(url: str) -> tuple[bool, int | None, bool]:
    """(available, size, service offline) for one download link."""
    await _LIMITER.acquire()
    try:
        response = await send_with_retry(_HEAD_CLIENT, "HEAD", url, timeout=60.0)
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


async def get_downloads(
    pid: str, *, release: str = "2016", lang: str = "en"
) -> CensusTableDownloads:
    if not pid.strip().isdigit():
        raise InvalidInput(
            say(
                f"pid must be digits, got {pid!r}.",
                f"pid doit contenir seulement des chiffres, reçu {pid!r}.",
                lang,
            )
        )
    base = f"{constants.HOST}{_release(release, lang).path}"
    urls = {
        "csv": f"{base}CompDataDownload.cfm?LANG=E&PID={pid}&OFT=CSV",
        "sdmx": f"{base}OpenDataDownload.cfm?PID={pid}",
        "ivt": f"{base}Download.cfm?PID={pid}",
    }
    try:
        checks = await asyncio.gather(*(_head(u) for u in urls.values()))
    except CloudflareChallenge as exc:
        raise CloudflareChallenge(
            say(f"{exc} {constants.BLOCKED_NOTE}", constants.BLOCKED_NOTE_FR, lang)
        ) from exc
    downloads = [
        Download(format=fmt, url=url, available=ok, size_bytes=size)
        for (fmt, url), (ok, size, _) in zip(urls.items(), checks, strict=True)
    ]
    if not any(d.available for d in downloads):
        # The 2011 Census tabulations answer this way for good (checked
        # 2026-09-25 while 2006, 2011 NHS and 2016 downloads worked).
        if release == "2011" and any(offline for _, _, offline in checks):
            raise NotFound(
                say(
                    f"StatCan has retired the 2011 Census tabulations, including PID {pid}. "
                    "Copies are on Borealis: use borealis_search_ivt "
                    "(e.g. 'census 2011 language').",
                    "Statistique Canada a retiré les totalisations du Recensement de 2011, "
                    f"dont le PID {pid}. Des copies sont dans Borealis : utilisez "
                    "borealis_search_ivt (p. ex. « census 2011 language »).",
                    lang,
                )
            )
        if any(offline for _, _, offline in checks):
            raise UpstreamUnavailable(
                say(
                    "StatCan's census download service is temporarily offline (it redirects "
                    "to its 'temporarily offline for updating' page). Try again later.",
                    "Le service de téléchargement du recensement de Statistique Canada est "
                    "temporairement hors ligne (il redirige vers sa page « temporairement hors "
                    "ligne pour mise à jour »). Réessayez plus tard.",
                    lang,
                )
            )
        raise NotFound(
            say(
                f"No downloads found for PID {pid} in the {release} release.",
                f"Aucun téléchargement trouvé pour le PID {pid} dans la diffusion {release}.",
                lang,
            )
        )
    by_format = {d.format: d.available for d in downloads}
    ivt_only = by_format["ivt"] and not (by_format["csv"] or by_format["sdmx"])
    note = None
    if ivt_only:
        code = (
            f'download.file("{urls["ivt"]}", "table_{pid}.ivt", mode = "wb"); '
            f'tab <- canivt::read_ivt("table_{pid}.ivt"); '
            "canivt::ivt_tidy(tab)"
        )
        # The R code goes after say(), so French spacing never touches it.
        note = (
            say(
                "Only a Beyond 20/20 IVT file exists. Read it in R with mountainMath's canivt "
                '(remotes::install_github("mountainMath/canivt")): ',
                "Seul un fichier IVT Beyond 20/20 existe. Lisez-le dans R avec canivt, de "
                'mountainMath (remotes::install_github("mountainMath/canivt")) : ',
                lang,
            )
            + code
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
            limits=say(
                "availability checked with HEAD requests; files are ZIPs",
                "disponibilité vérifiée par des requêtes HEAD ; les fichiers sont des ZIP",
                lang,
            ),
            lang=lang,
        ),
    )
