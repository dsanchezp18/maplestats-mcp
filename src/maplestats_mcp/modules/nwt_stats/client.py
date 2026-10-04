"""NWT Bureau of Statistics: Excel files listed from statsnwt.ca topic pages.

The Bureau has no API. Each topic page links its Excel tables with the
agency's own titles, grouped under headings (a release date, a survey, a
quarter) and sometimes inside collapsible blocks opened by a
`javascript:toggle('id')` link whose text names the block. Community
profiles sit one page deeper, one page per community. Files are read with
the shared Excel reader (shared/file_tables.py): the real format comes from
the bytes, the header row is guessed (and can be overridden), and a
multi-sheet workbook follows the same sheet policy as the other file
readers.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Literal
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.nwt_stats import constants
from maplestats_mcp.modules.nwt_stats.schemas import (
    FileEntry,
    FileList,
    FileRows,
    SheetSize,
    TopicInfo,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared import file_tables as tables
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_EXCEL_SUFFIXES = (".xlsx", ".xls")
_TOGGLE = re.compile(r"toggle\('([^']+)'\)")
# Link texts that say nothing about the table ("(Excel)", "downloaded (excel)",
# "2018 Volunteering - XLS" is kept): the surrounding text is used instead.
_GENERIC_LINK = re.compile(r"^(?:downloaded|download|here|click|excel|xlsx?|file|table|data|\W)*$")
# "( Excel )", "(Excel File)" after a title taken from the text around a link.
_EXCEL_NOTE = re.compile(r"\s*\(\s*excel(?: file)?\s*\)", re.IGNORECASE)
_HEADINGS = ("h2", "h3", "h4", "h5", "strong", "b")
# Characters kept as-is when a link is percent-encoded; '%' keeps an already
# encoded link unchanged.
_PATH_SAFE = "/%:@&=+$,;~-._!'()"


def _words(text: str) -> str:
    return " ".join(text.split())


def _fold(text: str) -> str:
    """Casefolded and without accents, so 'ndilo' finds 'Ndilǫ'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def topic_title(topic: str, lang: Lang) -> str:
    _, en, fr = constants.TOPICS[topic]
    return en if lang == "en" else fr


def topic_url(topic: str) -> str:
    return constants.SITE + constants.TOPICS[topic][0]


def normalize_url(url: str) -> str:
    """The canonical https link on www.statsnwt.ca with the path percent-encoded."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "") not in constants.HOSTS:
        raise InvalidInput(
            f"nwt_stats: url must be a link on {constants.DOMAIN} (see nwt_stats_list_files); "
            f"got {url!r}."
        )
    path = quote(unquote(parsed.path), safe=_PATH_SAFE)
    return parsed._replace(scheme="https", netloc=constants.DOMAIN, path=path).geturl()


def _is_excel(url: str) -> bool:
    return unquote(urlparse(url).path).lower().endswith(_EXCEL_SUFFIXES)


def _own_text(element: Tag) -> str:
    """Text of an element without its nested lists (a census item nests sub-items)."""
    parts: list[str] = []
    for child in element.contents:
        if isinstance(child, Tag):
            if child.name in ("ul", "ol", "li"):
                continue
            parts.append(child.get_text(" "))
        else:
            parts.append(str(child))
    return _words(" ".join(parts))


def _container_text(link: Tag) -> str:
    """The list item, cell or paragraph around a link, when it holds only that file."""
    holder = link.find_parent(["li", "p", "td"])
    if holder is None:
        return ""
    excel_links = [a for a in holder.find_all("a", href=True) if _is_excel(str(a["href"]))]
    if holder.name != "li" and len(excel_links) > 1:
        return ""
    return _own_text(holder)[: constants.TITLE_MAX_CHARS]


def _toggle_groups(soup: BeautifulSoup) -> dict[str, str]:
    """Block id -> the text of the link that opens it."""
    groups: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        match = _TOGGLE.search(str(anchor["href"]))
        text = _words(anchor.get_text(" "))
        if match and text:
            groups.setdefault(match.group(1), text)
    return groups


def _section(link: Tag, groups: dict[str, str], page_name: str | None) -> str | None:
    parts: list[str] = [page_name] if page_name else []
    for parent in link.parents:
        block = parent.get("id") if isinstance(parent, Tag) else None
        if isinstance(block, str) and block in groups:
            parts.append(groups[block])
            break
    heading = link.find_previous(_HEADINGS)
    if heading is not None:
        text = _words(heading.get_text(" ")).rstrip(":").strip()
        if text and len(text) <= 150:
            parts.append(text)
    unique: list[str] = []
    for part in parts:
        if part and (not unique or _fold(unique[-1]) != _fold(part)):
            unique.append(part)
    return " > ".join(unique) or None


def parse_page(
    html: str, page_url: str, topic: str, page_name: str | None = None
) -> list[FileEntry]:
    """The Excel links on one agency page, with the agency's titles and headings."""
    soup = BeautifulSoup(html, "html.parser")
    groups = _toggle_groups(soup)
    files: list[FileEntry] = []
    seen: set[tuple[str, str]] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        if not _is_excel(href):
            continue
        full = urljoin(page_url, href)
        if (urlparse(full).hostname or "") not in constants.HOSTS:
            continue
        url = normalize_url(full)
        text = _words(link.get_text(" "))
        around = _container_text(link)
        if _GENERIC_LINK.match(text.casefold()):
            title = _words(_EXCEL_NOTE.sub("", around)) or text
        else:
            title = text
        if not title:
            title = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        title = title[: constants.TITLE_MAX_CHARS]
        if (url, title) in seen:
            continue
        seen.add((url, title))
        plain = _words(_EXCEL_NOTE.sub("", around))
        context = around if plain and _fold(plain) != _fold(title) else None
        files.append(
            FileEntry(
                topic=topic,
                section=_section(link, groups, page_name),
                title=title,
                context=context,
                url=url,
                format=unquote(urlparse(url).path).lower().rsplit(".", 1)[1],
                page_url=page_url,
            )
        )
    return files


def subpage_links(html: str, page_url: str, prefix: str) -> list[str]:
    """Links to the deeper pages of a topic (one per community), in page order."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for link in soup.find_all("a", href=True):
        full = urljoin(page_url, str(link["href"]).strip()).split("#")[0]
        parsed = urlparse(full)
        if (parsed.hostname or "") not in constants.HOSTS:
            continue
        path = unquote(parsed.path)
        if path.startswith(prefix) and path.lower().endswith((".html", ".php")):
            url = normalize_url(full)
            if url not in found:
                found.append(url)
    return found


def page_name(html: str) -> str | None:
    """A subpage's name from its <title> ('NWT Bureau of Statistics | Aklavik')."""
    soup = BeautifulSoup(html, "html.parser")
    title = _words(soup.title.get_text(" ")) if soup.title else ""
    name = title.rsplit("|", 1)[-1].strip()
    return name or None


async def _page(url: str) -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"nwt_stats: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"nwt_stats: {url} did not respond in time.") from exc
        return response.text

    return await cached_fetch(f"nwt_stats:page:{url}", constants.CACHE_TTL_PAGE_SECONDS, fetch)


async def _topic_files(topic: str) -> tuple[list[FileEntry], bool]:
    url = topic_url(topic)
    html, cached = await _page(url)
    files = parse_page(html, url, topic)
    prefix = constants.SUBPAGE_PREFIXES.get(topic)
    if prefix:
        subpages = subpage_links(html, url, prefix)
        loaded = await asyncio.gather(*(_page(u) for u in subpages))
        known = {f.url for f in files}
        for sub_url, (sub_html, sub_cached) in zip(subpages, loaded, strict=True):
            cached &= sub_cached
            for entry in parse_page(sub_html, sub_url, topic, page_name(sub_html)):
                # The Yellowknife page also links a spending table listed on its own topic.
                if entry.url not in known:
                    known.add(entry.url)
                    files.append(entry)
    return files, cached


def _topics(lang: Lang) -> list[TopicInfo]:
    return [
        TopicInfo(topic=name, title=topic_title(name, lang), page_url=topic_url(name))
        for name in constants.TOPICS
    ]


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= constants.FILES_LIMIT_MAX:
        raise InvalidInput(f"nwt_stats: limit must be 1 to {constants.FILES_LIMIT_MAX}.")


def _check_topic(topic: str) -> str:
    key = topic.strip().lower()
    if key not in constants.TOPICS:
        raise InvalidInput(f"nwt_stats: topic must be one of {list(constants.TOPICS)}.")
    return key


def _file_list(
    files: list[FileEntry],
    limit: int,
    offset: int,
    cached: bool,
    lang: Lang,
    url: str,
    coverage: str,
    notes: list[str],
) -> FileList:
    total = len(files)
    page = files[offset : offset + limit]
    more = offset + limit < total
    if more or offset:
        notes.append(f"showing files {offset + 1} to {offset + len(page)} of {total}")
    return FileList(
        topics=_topics(lang),
        files=page,
        total_files=total,
        truncated=more,
        licence=constants.LICENCE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="nwt_stats.FileList",
            freshness="Pages cached up to 6 hours; the Bureau updates tables monthly, "
            "quarterly or yearly as each release comes out.",
            coverage=coverage,
            limits="; ".join(notes) or None,
            licence=constants.LICENCE[lang],
            lang=lang,
        ),
    )


async def list_files(
    topic: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    _check_limit(limit)
    if offset < 0:
        raise InvalidInput("nwt_stats: offset must be 0 or more.")
    if topic is None:
        return _file_list(
            [],
            limit,
            0,
            True,
            lang,
            constants.SITE + "/",
            f"{len(constants.TOPICS)} topics; name one as `topic` to list its Excel files, "
            "or search every topic with nwt_stats_search_files.",
            [],
        )
    key = _check_topic(topic)
    files, cached = await _topic_files(key)
    return _file_list(
        files,
        limit,
        offset,
        cached,
        lang,
        topic_url(key),
        f"Excel files linked from the {topic_title(key, 'en')} page "
        "(PDF releases on the page are not listed).",
        [],
    )


async def search_files(
    query: str,
    topic: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> FileList:
    _check_limit(limit)
    words = _fold(query).split()
    if not words:
        raise InvalidInput("nwt_stats: query must have at least one word.")
    chosen = [_check_topic(topic)] if topic else list(constants.TOPICS)
    loaded = await asyncio.gather(*(_topic_files(t) for t in chosen), return_exceptions=True)
    files: list[FileEntry] = []
    failed: list[str] = []
    cached = True
    for name, outcome in zip(chosen, loaded, strict=True):
        if isinstance(outcome, BaseException):
            if not isinstance(outcome, Exception):
                raise outcome
            failed.append(name)
            continue
        entries, was_cached = outcome
        cached &= was_cached
        files.extend(entries)
    if failed and len(failed) == len(chosen):
        first = next(o for o in loaded if isinstance(o, Exception))
        raise first
    seen: set[tuple[str, str]] = set()
    matches: list[FileEntry] = []
    for entry in files:
        haystack = _fold(
            " ".join(
                (
                    entry.title,
                    entry.context or "",
                    entry.section or "",
                    topic_title(entry.topic, "en"),
                    entry.topic,
                    unquote(urlparse(entry.url).path.rsplit("/", 1)[-1]),
                )
            )
        )
        key = (entry.url, entry.title)
        if key not in seen and all(w in haystack for w in words):
            seen.add(key)
            matches.append(entry)
    notes = [f"pages that did not answer and were skipped: {failed}"] if failed else []
    return _file_list(
        matches,
        limit,
        0,
        cached,
        lang,
        topic_url(chosen[0]) if topic else constants.SITE + "/",
        "Excel files whose title, surrounding text, heading, topic or file name contains "
        f"every word of {query!r}, across {len(chosen)} topic page(s).",
        notes,
    )


def _allowed(host: str) -> bool:
    return host.lower() in constants.HOSTS


async def _download(url: str) -> tuple[file_download.Downloaded, bool]:
    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=_allowed,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="nwt_stats_read_file",
        )

    return await file_download.cached_download(
        f"nwt_stats:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch
    )


def _validate(limit: int, offset: int, header_row: int | None, header_rows: int) -> None:
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"nwt_stats: limit must be 1 to {constants.ROWS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("nwt_stats: offset must be 0 or more.")
    if header_row is not None and header_row < 1:
        raise InvalidInput("nwt_stats: header_row is 1-based (1 or more).")
    if not 1 <= header_rows <= 5:
        raise InvalidInput("nwt_stats: header_rows must be 1 to 5.")


async def read_file(
    url: str,
    sheet: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    _validate(limit, offset, header_row, header_rows)
    url = normalize_url(url)
    if not _is_excel(url):
        raise InvalidInput(
            f"nwt_stats: url must be an .xlsx or .xls link (see nwt_stats_list_files); got {url!r}."
        )
    downloaded, cached = await _download(url)
    body = downloaded.body
    try:
        fmt = tables.detect_format(body, None)
    except UpstreamError as exc:
        raise UpstreamError(f"nwt_stats: {url}: {exc}") from exc
    sizes = await run_parse(tables.sheet_sizes, body, fmt)
    if not sizes:
        raise UpstreamError(f"nwt_stats: {url} has no sheets.")
    chosen, how = tables.choose_sheet(sizes, sheet, fmt, "nwt_stats")
    sheet_sizes = [SheetSize(name=n, rows=r, columns=c) for n, r, c in sizes]

    def provenance(limits: list[str], coverage: str) -> Provenance:
        return make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="nwt_stats.FileRows",
            freshness="As published by the NWT Bureau of Statistics; files cached up to 6 hours.",
            coverage=coverage,
            limits="; ".join(limits) or None,
            licence=constants.LICENCE[lang],
            lang=lang,
        )

    if chosen is None:
        return FileRows(
            url=url,
            format=fmt,
            sheets=sheet_sizes,
            sheet=None,
            sheet_chosen_by="none",
            header_row=None,
            header_row_candidates=[],
            all_columns=[],
            columns=[],
            rows=[],
            total_rows=0,
            offset=offset,
            truncated=False,
            licence=constants.LICENCE[lang],
            provenance=provenance(
                [
                    (
                        f"the workbook has {len(sizes)} sheets of similar size and none was "
                        "requested, so no rows were read: pick one from `sheets` and pass it "
                        "as `sheet`"
                    )
                ],
                f"Sheet list of a {len(sizes)}-sheet workbook.",
            ),
        )

    _, summaries = await run_parse(tables.describe, body, fmt, chosen)
    result = await run_parse(
        tables.scan,
        body,
        fmt,
        chosen,
        header_row=header_row,
        header_rows=header_rows,
        columns=columns,
        filters=filters,
        contains=contains,
        offset=offset,
        limit=limit,
    )
    candidates = summaries[0].header_candidates if summaries else []
    more = offset + limit < result.total_rows
    notes: list[str] = []
    if how == "largest":
        notes.append(
            f"the workbook has {len(sizes)} sheets and none was requested, so the largest "
            f"({chosen!r}) was read; pass sheet= for another"
        )
    if result.capped:
        notes.append(f"the sheet was scanned only up to {tables.MAX_SCAN_ROWS} rows")
    if more:
        notes.append(
            f"showing rows {offset + 1} to {offset + len(result.rows)} of {result.total_rows}"
        )
    return FileRows(
        url=url,
        format=fmt,
        sheets=sheet_sizes,
        sheet=chosen,
        sheet_chosen_by=how,
        header_row=result.header_row,
        header_row_candidates=[c for c in candidates if c != result.header_row],
        all_columns=result.all_columns,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        offset=offset,
        truncated=more or result.capped,
        licence=constants.LICENCE[lang],
        provenance=provenance(
            notes,
            f"Sheet {chosen!r} of {len(sizes)}, layout as published (title rows, years "
            "across columns, footnotes at the bottom).",
        ),
    )
