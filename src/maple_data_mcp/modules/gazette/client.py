"""Client for the Canada Gazette RSS feeds and issue pages."""

from __future__ import annotations

from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from defusedxml import ElementTree

from maple_data_mcp.modules.gazette import constants
from maple_data_mcp.modules.gazette.schemas import (
    Issue,
    IssueList,
    IssueNotices,
    Notice,
    NoticeText,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TEXT_TAGS = ("h3", "h4", "h5", "p", "li", "td", "th", "dd", "dt")


def _lang(lang: str) -> str:
    return "fra" if lang == "fr" else "eng"


def _part(part: int) -> int:
    if part not in (1, 2):
        raise InvalidInput(f"part must be 1 or 2, got {part}.")
    return part


async def _fetch(url: str, ttl: int) -> bytes:
    async def fetch() -> bytes:
        await _LIMITER.acquire()
        try:
            return (await get_raw(url, timeout=60.0)).content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"gazette: nothing published at {url}.") from exc
            raise UpstreamError(
                f"gazette: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"gazette: {url} did not respond in time.") from exc

    body, _ = await cached_fetch(f"gazette:{url}", ttl, fetch)
    return body


def _clean(text: str) -> str:
    return " ".join(text.split())


def _issue_date(link: str) -> date | None:
    for segment in urlparse(link).path.split("/"):
        try:
            return date.fromisoformat(segment)
        except ValueError:
            continue
    return None


async def list_issues(
    part: int = 1, *, limit: int = constants.ISSUES_DEFAULT, lang: str = "en"
) -> IssueList:
    _part(part)
    if limit < 1 or limit > constants.ISSUES_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ISSUES_MAX}, got {limit}.")
    url = constants.FEED_URL.format(part=part, lang=_lang(lang))
    root = ElementTree.fromstring(await _fetch(url, constants.CACHE_TTL_FEED_SECONDS))
    issues: list[Issue] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        issued = _issue_date(link)
        if issued is None:
            published = item.findtext("pubDate")
            issued = parsedate_to_datetime(published).date() if published else None
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
            cached=False,
            schema_name="gazette.IssueList",
            freshness="Part I every Saturday; Part II every second Wednesday",
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
    _part(part)
    if issue_date:
        try:
            when = date.fromisoformat(issue_date)
        except ValueError as exc:
            raise InvalidInput(f"issue_date must be YYYY-MM-DD, got {issue_date!r}.") from exc
    else:
        latest = await list_issues(part, limit=1, lang=lang)
        if not latest.issues:
            raise NotFound(f"gazette: no Part {part} issues in the feed.")
        when = latest.issues[0].date
    url = constants.ISSUE_URL.format(
        part=part, year=when.year, date=when.isoformat(), lang=_lang(lang)
    )
    html = (await _fetch(url, constants.CACHE_TTL_PAGE_SECONDS)).decode("utf-8-sig", "replace")
    return IssueNotices(
        part=part,
        date=when,
        url=url,
        notices=_parse_issue(html, url),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="gazette.IssueNotices",
        ),
    )


def _notice_text(soup: BeautifulSoup, fragment: str) -> tuple[str | None, str]:
    if not fragment:
        main = soup.find("main") or soup
        heading = main.find("h1")
        return (
            _clean(heading.get_text()) if isinstance(heading, Tag) else None,
            "\n".join(t for el in main.find_all(_TEXT_TAGS) if (t := _clean(el.get_text()))),
        )
    anchor = soup.find(id=fragment)
    if not isinstance(anchor, Tag):
        raise NotFound(f"gazette: no notice #{fragment} on the page.")
    lines: list[str] = []
    for el in anchor.find_all_next():
        if el is not anchor and el.get("id") and el.name in ("h2", "h3") and lines:
            break
        text = _clean(el.get_text()) if el.name in _TEXT_TAGS else ""
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return _clean(anchor.get_text()) or None, "\n".join(lines)


async def get_notice(url: str, lang: str = "en") -> NoticeText:
    del lang
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in constants.ALLOWED_HOSTS:
        raise InvalidInput("url must be a gazette.gc.ca link from gazette_get_issue.")
    page, fragment = urldefrag(url)
    html = (await _fetch(page, constants.CACHE_TTL_PAGE_SECONDS)).decode("utf-8-sig", "replace")
    title, text = _notice_text(BeautifulSoup(html, "html.parser"), fragment)
    truncated = len(text) > constants.NOTICE_TEXT_MAX
    return NoticeText(
        url=url,
        title=title,
        text=text[: constants.NOTICE_TEXT_MAX],
        truncated=truncated,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="gazette.NoticeText",
            limits="unofficial text extract; the published Gazette is authoritative",
        ),
    )
