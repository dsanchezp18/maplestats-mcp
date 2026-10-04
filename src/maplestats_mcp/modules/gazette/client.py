"""Client for the Canada Gazette RSS feeds and issue pages."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree

from maplestats_mcp.modules.gazette import constants
from maplestats_mcp.modules.gazette.schemas import (
    Issue,
    IssueList,
    IssueNotices,
    Notice,
    NoticeText,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TEXT_TAGS = ("h3", "h4", "h5", "p", "li", "td", "th", "dd", "dt")
# An issue's table of contents: /rp-pr/p1/2026/2026-09-26/html/index-eng.html.
# The feeds also carry other items, such as the Consolidated Index of
# Statutory Instruments at /rp-pr/p2/2026/2026-06-30-c2/index-eng.html
# (live 2026-10-03), which are not issues and have no html/index page.
_ISSUE_LINK = re.compile(r"/rp-pr/p[12]/\d{4}/(\d{4}-\d{2}-\d{2})/html/index-(?:eng|fra)\.html$")
# gazette.gc.ca answers a missing page with HTTP 200 and the Canada.ca error
# template, titled "... (Erreur 404) ... / ... (Error 404) ..." (live 2026-10-03).
_SOFT_404 = re.compile(r"<title>[^<]*\((?:Error|Erreur) 404\)", re.IGNORECASE)


def _lang(lang: str) -> str:
    return "fra" if lang == "fr" else "eng"


def _part(part: int, lang: str = "en") -> int:
    if part not in (1, 2):
        raise lang_error(
            InvalidInput,
            lang,
            f"part must be 1 or 2, got {part}.",
            f"part doit valoir 1 ou 2 ; reçu {part}.",
        )
    return part


async def _fetch(url: str, ttl: int, lang: str = "en") -> tuple[bytes, bool]:
    async def fetch() -> bytes:
        await _LIMITER.acquire()
        try:
            content = (await get_raw(url, timeout=60.0)).content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise lang_error(
                    NotFound,
                    lang,
                    f"gazette: nothing published at {url}.",
                    f"gazette : rien n'est publié à {url}.",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"gazette: {url} returned HTTP {status}.",
                f"gazette : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"gazette: {url} did not respond in time.",
                f"gazette : {url} n'a pas répondu à temps.",
            ) from exc
        if _SOFT_404.search(content[:4000].decode("utf-8", "replace")):
            raise lang_error(
                NotFound,
                lang,
                f"gazette: nothing published at {url} (the site's not-found page).",
                f"gazette : rien n'est publié à {url} (page « introuvable » du site).",
            )
        return content

    return await cached_fetch(f"gazette:{url}", ttl, fetch)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _issue_date(link: str) -> date | None:
    match = _ISSUE_LINK.search(urlparse(link).path)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


async def list_issues(
    part: int = 1, *, limit: int = constants.ISSUES_DEFAULT, lang: str = "en"
) -> IssueList:
    _part(part, lang)
    if limit < 1 or limit > constants.ISSUES_MAX:
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and {constants.ISSUES_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.ISSUES_MAX} ; reçu {limit}.",
        )
    url = constants.FEED_URL.format(part=part, lang=_lang(lang))
    feed, cached = await _fetch(url, constants.CACHE_TTL_FEED_SECONDS, lang)
    root = ElementTree.fromstring(feed)
    issues: list[Issue] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        # Only issue tables of contents: the pubDate of a non-issue item (the
        # Consolidated Index) is not a publication day, and get_issue would
        # open a page that does not exist for it.
        issued = _issue_date(link)
        if issued is None:
            continue
        issues.append(
            Issue(part=part, date=issued, title=_clean(item.findtext("title") or ""), url=link)
        )
    issues.sort(key=lambda i: i.date, reverse=True)
    return IssueList(
        issues=issues[:limit],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="gazette.IssueList",
            freshness=fr_or_en(
                lang,
                "Part I every Saturday; Part II every second Wednesday",
                "Partie I chaque samedi ; Partie II un mercredi sur deux",
            ),
            lang=lang,
        ),
    )


def _parse_issue(html: str, base_url: str) -> list[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    notices: list[Notice] = []
    section = organization = act = None
    for el in main.find_all(["h2", "h3", "h4", "a"]):
        text = _clean(el.get_text())
        if el.name == "h2":
            section, organization, act = text or None, None, None
        elif el.name == "h3":
            organization, act = text or None, None
        elif el.name == "h4":
            act = text or None
        else:
            href = str(el.get("href") or "")
            target, fragment = urldefrag(href)
            # Section headers link to the whole section page; notices carry an anchor
            # (Part I) or point to a single instrument page (Part II).
            if not target.endswith(".html") or href.startswith("#"):
                continue
            if not fragment and text == section:
                continue
            notices.append(
                Notice(
                    title=text,
                    section=section,
                    organization=organization,
                    act=act,
                    url=urljoin(base_url, href),
                )
            )
    return notices


async def get_issue(part: int = 1, issue_date: str | None = None, lang: str = "en") -> IssueNotices:
    _part(part, lang)
    if issue_date:
        try:
            when = date.fromisoformat(issue_date)
        except ValueError as exc:
            raise lang_error(
                InvalidInput,
                lang,
                f"issue_date must be YYYY-MM-DD, got {issue_date!r}.",
                f"issue_date doit être au format AAAA-MM-JJ ; reçu {issue_date!r}.",
            ) from exc
    else:
        latest = await list_issues(part, limit=1, lang=lang)
        if not latest.issues:
            raise lang_error(
                NotFound,
                lang,
                f"gazette: no Part {part} issues in the feed.",
                f"gazette : aucun numéro de la Partie {part} dans le fil.",
            )
        when = latest.issues[0].date
    url = constants.ISSUE_URL.format(
        part=part, year=when.year, date=when.isoformat(), lang=_lang(lang)
    )
    page, cached = await _fetch(url, constants.CACHE_TTL_PAGE_SECONDS, lang)
    html = page.decode("utf-8-sig", "replace")
    return IssueNotices(
        part=part,
        date=when,
        url=url,
        notices=_parse_issue(html, url),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="gazette.IssueNotices",
            lang=lang,
        ),
    )


def _notice_text(soup: BeautifulSoup, fragment: str, lang: str = "en") -> tuple[str | None, str]:
    if not fragment:
        main = soup.find("main") or soup
        heading = main.find("h1")
        return (
            _clean(heading.get_text()) if isinstance(heading, Tag) else None,
            "\n".join(t for el in main.find_all(_TEXT_TAGS) if (t := _clean(el.get_text()))),
        )
    anchor = soup.find(id=fragment)
    if not isinstance(anchor, Tag):
        raise lang_error(
            NotFound,
            lang,
            f"gazette: no notice #{fragment} on the page.",
            f"gazette : aucun avis #{fragment} sur la page.",
        )
    lines: list[str] = []
    for el in anchor.find_all_next():
        if el is not anchor and el.get("id") and el.name in ("h2", "h3") and lines:
            break
        text = _clean(el.get_text()) if el.name in _TEXT_TAGS else ""
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return _clean(anchor.get_text()) or None, "\n".join(lines)


async def get_notice(url: str, lang: str = "en") -> NoticeText:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in constants.ALLOWED_HOSTS:
        raise lang_error(
            InvalidInput,
            lang,
            "url must be a gazette.gc.ca link from gazette_get_issue.",
            "url doit être un lien gazette.gc.ca tiré de gazette_get_issue.",
        )
    page, fragment = urldefrag(url)
    body, cached = await _fetch(page, constants.CACHE_TTL_PAGE_SECONDS, lang)
    html = body.decode("utf-8-sig", "replace")
    title, text = _notice_text(BeautifulSoup(html, "html.parser"), fragment, lang)
    truncated = len(text) > constants.NOTICE_TEXT_MAX
    return NoticeText(
        url=url,
        title=title,
        text=text[: constants.NOTICE_TEXT_MAX],
        truncated=truncated,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="gazette.NoticeText",
            # The text is in the language of the linked page, whatever lang is.
            limits=fr_or_en(
                lang,
                "unofficial text extract; the published Gazette is authoritative",
                "extrait non officiel du texte ; seule la Gazette publiée fait foi. Le texte est "
                "dans la langue de la page liée (-fra.html pour le français)",
            ),
            lang=lang,
        ),
    )
