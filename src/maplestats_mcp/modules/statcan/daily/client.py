"""Client for The Daily's official Atom feeds.

Confirmed live 2026-09-20. Two real quirks handled:

1. `<title>` and `<summary>` are `type="xhtml"`, holding a nested
   `<div>` that can itself contain inline markup (e.g. a
   `<span class="refper">` wrapping a reference period inside the
   title, confirmed live: "Employer pension plans ...,
   <span class="refper">first quarter 2026</span>"). This client joins
   all text content within the div (`itertext()`) rather than reading
   only the div's direct text, which would silently drop that inline
   text.
2. Some entries are not data releases but simple "new product"
   announcements pointing at a catalogue-number resolver
   (`cgi-bin/IPS/display?cat_num=...`) rather than a
   `daily-quotidien/...` article page -- both are returned as-is via
   `url`; this client does not try to distinguish release articles
   from product announcements, since both are genuine Daily entries.

`search_archive` covers the full release history instead of the Atom
feeds' 100-day window, via a JSON file the release-schedule calendar
page loads client-side (found by reading that page's raw HTML for its
inline `eventsjson:` config, not from any documented API) -- one 3.7 MB
array, 18,222 entries confirmed live from 2012-03-14 onward, no
pagination. Its own `date` field carries an artificial time-of-day
(e.g. "00:00:01", "00:00:02", ...) used only to order same-day entries,
not a real timestamp, so this client keeps only the date component.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from maplestats_mcp.modules.statcan.daily import constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveEntry,
    DailyArchiveSearchResult,
    DailyArticle,
    DailyRelease,
    DailyReleaseList,
    ReleaseCalendarEntry,
    ReleaseCalendarResult,
)
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _xhtml_text(entry: ElementTree.Element, tag: str) -> str | None:
    element = entry.find(f"atom:{tag}", constants.ATOM_NS)
    if element is None:
        return None
    div = element.find("xhtml:div", constants.ATOM_NS)
    text = "".join((div if div is not None else element).itertext())
    text = " ".join(text.split())
    return text or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _release_from_entry(entry: ElementTree.Element) -> DailyRelease:
    link = entry.find("atom:link", constants.ATOM_NS)
    updated = entry.find("atom:updated", constants.ATOM_NS)
    return DailyRelease(
        title=_xhtml_text(entry, "title") or "",
        url=(link.get("href") if link is not None else None) or "",
        published_at=_parse_datetime(updated.text if updated is not None else None),
        summary=_xhtml_text(entry, "summary"),
    )


async def get_releases(
    subject: str = "all", *, lang: str = "en", limit: int = constants.RELEASES_LIMIT_DEFAULT
) -> DailyReleaseList:
    """Fetch recent releases from The Daily for one subject (or "all")."""
    use_lang(lang)
    code = constants.SUBJECT_TO_CODE.get(subject)
    if code is None:
        raise InvalidInput(
            say(
                f"statcan_daily:get_releases: subject must be one of "
                f"{sorted(constants.SUBJECT_TO_CODE)}, got {subject!r}.",
                f"statcan_daily:get_releases : subject doit être l'une des valeurs {sorted(constants.SUBJECT_TO_CODE)}, reçu {subject!r}.",
            )
        )
    if limit < 1 or limit > constants.RELEASES_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:get_releases: limit must be between 1 and "
                f"{constants.RELEASES_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:get_releases : limit doit être entre 1 et {constants.RELEASES_LIMIT_MAX}, reçu {limit}.",
            )
        )
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = f"{constants.BASE_URL}/{code}-{suffix}.atom"

    async def fetch() -> bytes:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
            return response.content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_daily:get_releases returned HTTP {status} for subject {subject!r}.",
                    f"statcan_daily:get_releases a renvoyé HTTP {status} pour le sujet {subject!r}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:get_releases did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:get_releases n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-daily:releases:{code}:{suffix}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)

    try:
        root = DefusedET.fromstring(body)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise UpstreamError(
            say(
                f"statcan_daily:get_releases: response for subject {subject!r} was not valid XML.",
                f"statcan_daily:get_releases : la réponse pour le sujet {subject!r} n'était pas du XML valide.",
            )
        ) from exc

    all_entries = root.findall("atom:entry", constants.ATOM_NS)
    releases = [_release_from_entry(entry) for entry in all_entries[:limit]]
    in_feed = len(all_entries)
    return DailyReleaseList(
        subject=subject,
        releases=releases,
        returned_count=len(releases),
        total_in_feed=in_feed,
        truncated=in_feed > len(releases),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyReleaseList",
            limits=say(
                f"Returned the first {len(releases)} of {in_feed} releases in the feed; "
                f"raise limit (up to {constants.RELEASES_LIMIT_MAX}) for more.",
                f"Les {len(releases)} premières diffusions sur {in_feed} dans le fil ; "
                f"augmentez limit (jusqu'à {constants.RELEASES_LIMIT_MAX}) pour en voir plus.",
            )
            if in_feed > len(releases)
            else None,
            lang=lang,
        ),
    )


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(
            say(
                f"statcan_daily:search_archive: expected a YYYY-MM-DD date, got {value!r}.",
                f"statcan_daily:search_archive : date attendue au format AAAA-MM-JJ, reçu {value!r}.",
            )
        ) from exc


def _parse_archive_entry_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_ARCHIVE_HOST = "https://www150.statcan.gc.ca"


async def search_archive(
    query: str = "",
    *,
    lang: str = "en",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ARCHIVE_SEARCH_LIMIT_DEFAULT,
) -> DailyArchiveSearchResult:
    """Search the full Daily release archive (2012-03-14 onward) by title/period and date range."""
    use_lang(lang)
    if limit < 1 or limit > constants.ARCHIVE_SEARCH_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:search_archive: limit must be between 1 and "
                f"{constants.ARCHIVE_SEARCH_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:search_archive : limit doit être entre 1 et {constants.ARCHIVE_SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
        )
    parsed_start = _parse_iso_date(start_date) if start_date else None
    parsed_end = _parse_iso_date(end_date) if end_date else None

    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.FULL_ARCHIVE_URL.format(suffix=suffix)
    # Same reference timezone as the release calendar: a release dated today
    # in Toronto is still "scheduled" until its article exists.
    today = datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).date()

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_daily:search_archive returned HTTP {status}.",
                    f"statcan_daily:search_archive a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:search_archive did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:search_archive n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-daily:archive:{suffix}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ARCHIVE_SECONDS, fetch)
    if not isinstance(payload, list):
        raise UpstreamError(
            say(
                "statcan_daily:search_archive: expected a JSON array from the archive.",
                "statcan_daily:search_archive : tableau JSON attendu de l'archive.",
            )
        )

    query_lower = query.strip().lower()
    matched: list[DailyArchiveEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        entry_date = _parse_archive_entry_date(item.get("date"))
        if entry_date is None:
            continue
        if parsed_start is not None and entry_date < parsed_start:
            continue
        if parsed_end is not None and entry_date > parsed_end:
            continue
        title = item.get("title") or ""
        reference_period = item.get("description") or None
        if (
            query_lower
            and query_lower not in title.lower()
            and (not reference_period or query_lower not in reference_period.lower())
        ):
            continue
        # Upcoming "meeting" entries carry url == "": no article yet, so no link
        # (prefixing the host would yield the bare home page).
        relative_url = item.get("url") or ""
        matched.append(
            DailyArchiveEntry(
                release_date=entry_date,
                title=title,
                reference_period=reference_period,
                scheduled=entry_date >= today,
                url=f"{_ARCHIVE_HOST}{relative_url}" if relative_url else None,
            )
        )

    matched.sort(key=lambda entry: entry.release_date, reverse=True)
    page = matched[:limit]
    return DailyArchiveSearchResult(
        query=query,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyArchiveSearchResult",
            lang=lang,
        ),
    )


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'Enquete' finds 'Enquête'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("œ", "oe"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


async def _fetch_schedule(url: str, label: str) -> tuple[list[Any], bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_daily:release_calendar returned HTTP {status}.",
                    f"statcan_daily:release_calendar a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:release_calendar did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:release_calendar n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    payload, was_cached = await cached_fetch(
        f"statcan-daily:calendar:{label}", constants.CACHE_TTL_ARCHIVE_SECONDS, fetch
    )
    if not isinstance(payload, list):
        raise UpstreamError(
            say(
                f"statcan_daily:release_calendar: expected a JSON array from the {label} schedule.",
                f"statcan_daily:release_calendar : tableau JSON attendu du calendrier {label}.",
            )
        )
    return payload, was_cached


def _calendar_entries(
    payload: list[Any], kind: str, today: date, host_prefix: str
) -> list[ReleaseCalendarEntry]:
    entries: list[ReleaseCalendarEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # Products carry a clean release_date; indicators only the "date" with
        # an artificial time-of-day (00:00:01, 00:00:02) that orders same-day rows.
        release_date = _parse_archive_entry_date(item.get("release_date") or item.get("date"))
        if release_date is None:
            continue
        relative_url = item.get("url") or ""
        description = item.get("description") or None
        entries.append(
            ReleaseCalendarEntry(
                release_date=release_date,
                kind=kind,
                title=item.get("title") or "",
                reference_period=description if kind == "key_indicator" else None,
                catalogue_number=item.get("pid") or None,
                scheduled=release_date >= today,
                # Future indicator rows have url == "": the article does not exist yet.
                url=f"{host_prefix}{relative_url}" if relative_url else None,
            )
        )
    return entries


async def get_release_calendar(
    query: str = "",
    *,
    lang: str = "en",
    kind: str = "key_indicators",
    upcoming_only: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.CALENDAR_LIMIT_DEFAULT,
) -> ReleaseCalendarResult:
    """Release calendar: scheduled Daily indicator releases and catalogue product releases."""
    use_lang(lang)
    if kind not in ("key_indicators", "products", "all"):
        raise InvalidInput(
            say(
                "statcan_daily:get_release_calendar: kind must be one of "
                f"('key_indicators', 'products', 'all'), got {kind!r}.",
                f"statcan_daily:get_release_calendar : kind doit être l'une des valeurs ('key_indicators', 'products', 'all'), reçu {kind!r}.",
            )
        )
    if limit < 1 or limit > constants.CALENDAR_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:get_release_calendar: limit must be between 1 and "
                f"{constants.CALENDAR_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:get_release_calendar : limit doit être entre 1 et {constants.CALENDAR_LIMIT_MAX}, reçu {limit}.",
            )
        )
    parsed_start = _parse_iso_date(start_date) if start_date else None
    parsed_end = _parse_iso_date(end_date) if end_date else None
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    today = datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).date()
    host = "https://www150.statcan.gc.ca"

    entries: list[ReleaseCalendarEntry] = []
    all_cached = True
    urls: list[str] = []
    if kind in ("key_indicators", "all"):
        url = constants.KEY_INDICATORS_URL.format(suffix=suffix)
        payload, was_cached = await _fetch_schedule(url, f"indicators:{suffix}")
        entries += _calendar_entries(payload, "key_indicator", today, host)
        all_cached &= was_cached
        urls.append(url)
    if kind in ("products", "all"):
        url = constants.PRODUCTS_URL.format(suffix=suffix)
        payload, was_cached = await _fetch_schedule(url, f"products:{suffix}")
        entries += _calendar_entries(payload, "product", today, host)
        all_cached &= was_cached
        urls.append(url)

    latest_scheduled = max((e.release_date for e in entries), default=None)
    words = re.findall(r"\w+", _fold(query))
    matched: list[ReleaseCalendarEntry] = []
    for entry in entries:
        if upcoming_only and not entry.scheduled:
            continue
        if parsed_start is not None and entry.release_date < parsed_start:
            continue
        if parsed_end is not None and entry.release_date > parsed_end:
            continue
        haystack = _fold(
            f"{entry.title} {entry.reference_period or ''} {entry.catalogue_number or ''}"
        )
        if all(word in haystack for word in words):
            matched.append(entry)

    # Soonest first when asking about the future, newest first for history.
    matched.sort(key=lambda entry: entry.release_date, reverse=not upcoming_only)
    page = matched[:limit]
    return ReleaseCalendarResult(
        query=query,
        kind=kind,
        upcoming_only=upcoming_only,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        today=today,
        latest_scheduled_date=latest_scheduled,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=urls[0],
            cached=all_cached,
            schema_name="statcan_daily.ReleaseCalendarResult",
            limits=say(
                "Dates are StatCan's planned schedule and can change. The products file "
                "lists catalogue releases up to today only; future dates come from the "
                "key-indicators file.",
                "Les dates sont le calendrier prévu par Statistique Canada et peuvent changer. "
                "Le fichier des produits liste les diffusions au catalogue jusqu'à aujourd'hui "
                "seulement ; les dates futures viennent du fichier des indicateurs clés.",
            ),
            lang=lang,
        ),
    )


# An article id is "dq" + the release day (YYMMDD) + one or more letters, the letter
# telling apart the day's articles (dq261104a, dq261104b, ...). The feeds and the archive
# give full URLs on www.statcan.gc.ca or www150.statcan.gc.ca; either form, or the bare
# id, is accepted, and the page is always read in the language asked for.
_ARTICLE_ID = re.compile(r"\b(dq(\d{6})[a-z]+)(?:-(?:eng|fra))?(?:\.htm)?", re.IGNORECASE)
_PID = re.compile(r"[?&]pid=(\d{8})\d{2}")


def _article_url(article: str, lang: str) -> tuple[str, str]:
    match = _ARTICLE_ID.search(article.strip())
    if match is None:
        raise InvalidInput(
            say(
                "statcan_daily:get_article: give a Daily article URL or id such as "
                f"'dq261104a' (from statcan_daily_get_releases), got {article!r}.",
                "statcan_daily:get_article : donnez l'adresse ou l'identifiant d'un article du "
                "Quotidien, par exemple 'dq261104a' (voir statcan_daily_get_releases), "
                f"reçu {article!r}.",
            )
        )
    article_id = match.group(1).lower()
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.ARTICLE_URL_TEMPLATE.format(
        day=match.group(2), article_id=article_id, suffix=suffix
    )
    return article_id, url


def _clean(text: str) -> str:
    return " ".join(text.split())


def _table_id(digits: str) -> str:
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:8]}-01"


# Links in an article are root-relative ("/daily-quotidien/...", "/en/catalogue/...");
# on www150 those answer 301 to the same path under /n1/ (checked 2026-11-04 from the
# Azure server), so they are given in that final form.
_N1_PREFIXES = ("/daily-quotidien/", "/dai-quo/", "/en/", "/fr/")


def _absolute(url: str, href: str) -> str:
    absolute = urljoin(url, href)
    host = "https://www150.statcan.gc.ca"
    if absolute.startswith(host) and absolute[len(host) :].startswith(_N1_PREFIXES):
        return f"{host}/n1{absolute[len(host) :]}"
    return absolute


def _article_section(main: Tag) -> Tag | None:
    """The <section> holding the release nav and the text.

    Checked 2026-11-04 on articles from 2013, 2017, 2021 and 2024: an article that is
    no longer current carries an "Archived Content" notice first, as
    <section id="archived"> and <section id="archived-bnr">, and only then the article's
    own <section>; a current one has that section alone after the <h1>.
    """
    for section in main.find_all("section"):
        if section.find("div", class_="release_nav") or section.find("p", class_="sd-release-date"):
            return section
    return None


def _parse_article(html: str, url: str) -> dict[str, Any]:
    """Pull the article out of a Daily page (layout described in constants.py)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    heading = main.find("h1") if isinstance(main, Tag) else None
    body = _article_section(main) if isinstance(main, Tag) else None
    if not isinstance(main, Tag) or not isinstance(heading, Tag) or not isinstance(body, Tag):
        raise UpstreamError(
            say(
                f"statcan_daily:get_article: {url} has no article (no <h1> and <section> "
                "in <main>); StatCan may have changed the page layout.",
                f"statcan_daily:get_article : {url} ne contient pas d'article (pas de <h1> ni "
                "de <section> dans <main>) ; Statistique Canada a peut-être changé la page.",
            )
        )

    def meta(name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        value = tag.get("content") if isinstance(tag, Tag) else None
        return _clean(str(value)) if value else None

    nav: dict[str, str] = {}
    release_nav = body.find("div", class_="release_nav")
    if isinstance(release_nav, Tag):
        for link in release_nav.find_all("a", href=True):
            href = _absolute(url, str(link["href"]))
            if href.endswith(".pdf"):
                nav["pdf"] = href
            elif "-cansim-" in href:
                nav["tables"] = href
            elif "-info-" in href:
                nav["info"] = href
            elif "/dai-quo/cal" in href:
                nav["schedule"] = href
            elif "/daily-quotidien/" in href and href.split("?")[0] != url:
                nav["previous"] = href

    sections: list[dict[str, Any]] = [{"heading": None, "parts": []}]
    charts: list[str] = []

    def add_text(element: Tag) -> None:
        if element.name in ("ul", "ol"):
            items = [_clean(item.get_text(" ")) for item in element.find_all("li")]
            text = "\n".join(f"- {item}" for item in items if item)
        else:
            text = _clean(element.get_text(" "))
        if text:
            sections[-1]["parts"].append(text)

    for child in body.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class") or []
        if child.name == "h2" and "chartt" not in classes:
            sections.append({"heading": _clean(child.get_text(" ")), "parts": []})
        elif child.name in ("p", "ul", "ol") and "sd-release-date" not in classes:
            add_text(child)
        elif child.name == "div" and "sd-noteuser" in classes:
            title = child.find(["h2", "h3"])
            note = _clean(title.get_text(" ")) if isinstance(title, Tag) else "Note to readers"
            sections.append({"heading": note, "parts": []})
            panel = child.find("div", class_="panel-body")
            for element in (panel if isinstance(panel, Tag) else child).find_all(
                ["p", "h3", "h4", "ul", "ol"], recursive=False
            ):
                if element.name in ("h3", "h4"):
                    sub = _clean(element.get_text(" "))
                    sections.append({"heading": f"{note}: {sub}", "parts": []})
                else:
                    add_text(element)
        elif child.name == "div":
            chart = child.find("h2", class_="chartt")
            if isinstance(chart, Tag):
                charts.append(_clean(chart.get_text(" ")))

    tables: dict[int, str] = {}
    links: dict[str, str] = {}
    nav_urls = set(nav.values())
    for link in body.find_all("a", href=True):
        href = str(link["href"])
        if href.startswith(("#", "mailto:")):
            continue
        absolute = _absolute(url, href)
        pid = _PID.search(absolute)
        if pid:
            tables.setdefault(int(pid.group(1)), _table_id(pid.group(1)))
            continue
        text = _clean(link.get_text(" "))
        # Chart thumbnails (cg-a001-eng.htm) carry no text; their titles are in `charts`.
        if not text or absolute in nav_urls or absolute.split("?")[0] == url:
            continue
        links.setdefault(absolute, text)

    issued = meta("dcterms.issued")
    try:
        release_date = date.fromisoformat(issued) if issued else None
    except ValueError:
        release_date = None
    built = [
        {"heading": section["heading"], "text": "\n\n".join(section["parts"])}
        for section in sections
        if section["parts"]
    ]
    return {
        "title": _clean(heading.get_text(" ")),
        "release_date": release_date,
        "archived": main.find("section", id="archived") is not None,
        "summary": meta("dcterms.description") or meta("description"),
        "sections": built,
        "charts": charts,
        "tables": [
            {"table_id": table_id, "product_id": product_id}
            for product_id, table_id in tables.items()
        ],
        "pdf_url": nav.get("pdf"),
        "tables_page_url": nav.get("tables"),
        "related_info_url": nav.get("info"),
        "previous_release_url": nav.get("previous"),
        "links": [{"text": text, "url": href} for href, text in links.items()],
        "word_count": sum(len(section["text"].split()) for section in built),
    }


async def get_article(article: str, *, lang: str = "en") -> DailyArticle:
    """Read one Daily article in full: its sections, tables, charts and PDF link."""
    use_lang(lang)
    article_id, url = _article_url(article, lang)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise NotFound(
                    say(
                        f"statcan_daily:get_article: StatCan has no Daily article {article_id} "
                        f"({url}). Take the id from statcan_daily_get_releases or "
                        "statcan_daily_search_archive.",
                        "statcan_daily:get_article : Statistique Canada n'a pas d'article "
                        f"{article_id} dans Le Quotidien ({url}). Prenez l'identifiant dans "
                        "statcan_daily_get_releases ou statcan_daily_search_archive.",
                    )
                ) from exc
            raise UpstreamError(
                say(
                    f"statcan_daily:get_article returned HTTP {status} for {url}.",
                    f"statcan_daily:get_article a renvoyé HTTP {status} pour {url}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:get_article did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:get_article n'a pas répondu à temps (nouvelles tentatives "
                    "déjà faites). Réessayez sous peu.",
                )
            ) from exc
        return response.text

    html, was_cached = await cached_fetch(
        f"statcan-daily:article:{article_id}:{lang}", constants.CACHE_TTL_ARTICLE_SECONDS, fetch
    )
    parsed = _parse_article(html, url)
    return DailyArticle(
        url=url,
        article_id=article_id,
        **parsed,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyArticle",
            limits=say(
                "Text only: charts and the release's own tables are listed by title and "
                "link, not reproduced. Read figures from the tables (wds_ tools) and cite them.",
                "Texte seulement : les graphiques et les tableaux du communiqué sont donnés par "
                "titre et lien, sans leur contenu. Lisez les chiffres dans les tableaux (outils "
                "wds_) et citez-les.",
            ),
            lang=lang,
        ),
    )
