"""Newfoundland and Labrador Statistics Agency: file listing and Excel reading.

The agency has no API. Its topic pages list the Excel files with a
description, and each file is read sheet by sheet (`.xlsx` with openpyxl,
legacy `.xls` with xlrd). Sheets keep the agency's layout, so rows come
back as published text with a guessed header row.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.nl_stats import constants
from maplestats_mcp.modules.nl_stats.schemas import (
    FileData,
    FileEntry,
    FileList,
    SheetInfo,
    TopicInfo,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

Lang = Literal["en", "fr"]

_EXCEL_SUFFIXES = (".xlsx", ".xls")


def topic_title(topic: str, lang: Lang) -> str:
    en, fr = constants.TOPICS[topic]
    return en if lang == "en" else fr


def _own_text(li: Tag) -> str:
    """The text of a list item before its first link or nested list."""
    parts: list[str] = []
    for child in li.contents:
        if isinstance(child, Tag) and child.name in ("a", "ul"):
            break
        parts.append(child.get_text() if isinstance(child, Tag) else str(child))
    return " ".join("".join(parts).split()).strip(" :|")


def _title_for(link: Tag) -> str:
    li = link.find_parent("li")
    if li is None:
        return " ".join(link.get_text().split())
    title = _own_text(li)
    parent_li = li.find_parent("li")
    if parent_li is not None:
        parent = _own_text(parent_li)
        title = f"{parent}: {title}" if parent and title else parent or title
    return title


def parse_topic_page(html: str, topic: str) -> list[FileEntry]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="ContentPlaceHolder1_links")
    if container is None:
        return []
    files: list[FileEntry] = []
    seen: set[tuple[str, str]] = set()
    for link in container.find_all("a", href=True):
        href = str(link["href"])
        if not href.lower().endswith(_EXCEL_SUFFIXES):
            continue
        url = urljoin(constants.SITE + "/Statistics/", href)
        title = _title_for(link)
        if (url, title) in seen:
            continue
        seen.add((url, title))
        heading = link.find_previous("h4")
        files.append(
            FileEntry(
                topic=topic,
                section=" ".join(heading.get_text().split()) if heading else None,
                title=title,
                url=url,
                format=url.lower().rsplit(".", 1)[1],
            )
        )
    return files


async def _topic_files(topic: str, lang: Lang = "en") -> tuple[list[FileEntry], bool]:
    url = constants.TOPIC_PAGE_URL.format(topic=topic)

    async def fetch() -> list[FileEntry]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise_localized(
                UpstreamError,
                f"nl_stats: {url} returned HTTP {status}.",
                f"nl_stats : {url} a renvoyé le code HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"nl_stats: {url} did not respond in time.",
                f"nl_stats : {url} n'a pas répondu à temps.",
                lang,
            )
        return parse_topic_page(response.text, topic)

    return await cached_fetch(f"nl_stats:topic:{topic}", constants.CACHE_TTL_PAGE_SECONDS, fetch)


async def list_files(
    topic: str | None = None,
    query: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    lang: Lang = "en",
    offset: int = 0,
) -> FileList:
    if topic is not None and topic not in constants.TOPICS:
        raise_localized(
            InvalidInput,
            f"nl_stats: topic must be one of {list(constants.TOPICS)}.",
            f"nl_stats : topic doit être l'un de {list(constants.TOPICS)}.",
            lang,
        )
    if not 1 <= limit <= constants.FILES_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"nl_stats: limit must be 1 to {constants.FILES_LIMIT_MAX}.",
            f"nl_stats : limit doit être entre 1 et {constants.FILES_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "nl_stats: offset must be 0 or more.",
            "nl_stats : offset doit être égal ou supérieur à 0.",
            lang,
        )
    chosen = [topic] if topic else list(constants.TOPICS)

    files: list[FileEntry] = []
    all_cached = True
    for name in chosen:
        entries, cached = await _topic_files(name, lang)
        files.extend(entries)
        all_cached &= cached

    if query:
        words = query.casefold().split()
        files = [
            f
            for f in files
            if all(w in f"{f.title} {f.section or ''} {f.url}".casefold() for w in words)
        ]
    total = len(files)
    page = files[offset : offset + limit]
    more = offset + len(page) < total
    shown = (
        pick(
            lang,
            f"Showing files {offset + 1}-{offset + len(page)} of {total}; pass offset="
            f"{offset + len(page)} for the next page, or a topic or query to narrow the list.",
            f"Fichiers {offset + 1} à {offset + len(page)} sur {total}; passez offset="
            f"{offset + len(page)} pour la page suivante, ou un topic ou une query pour "
            "restreindre la liste.",
        )
        if page and (more or offset)
        else (
            pick(
                lang,
                f"offset {offset} is past the {total} files.",
                f"offset {offset} dépasse les {total} fichiers.",
            )
            if not page and total
            else None
        )
    )
    return FileList(
        topics=[
            TopicInfo(
                topic=name,
                title=topic_title(name, lang),
                page_url=constants.TOPIC_PAGE_URL.format(topic=name),
            )
            for name in constants.TOPICS
        ],
        files=page,
        total_files=total,
        truncated=more,
        offset=offset,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=constants.SITE + "/Statistics/Statistics.aspx",
            cached=all_cached,
            schema_name="nl_stats.FileList",
            freshness=pick(
                lang,
                "The agency updates monthly, quarterly and annually by table.",
                "L'agence met ses tableaux à jour chaque mois, chaque trimestre ou chaque "
                "année, selon le tableau.",
            ),
            coverage=pick(
                lang,
                "Excel files only (each topic page also links PDFs); census, "
                "environment and justice topics publish no Excel files.",
                "Fichiers Excel seulement (chaque page thématique renvoie aussi à des PDF); "
                "les sujets recensement, environnement et justice ne publient aucun fichier "
                "Excel. Titres et descriptions des fichiers en anglais seulement, comme sur le "
                "site de l'agence.",
            ),
            limits=shown,
            lang=lang,
        ),
    )


def check_file_url(url: str, lang: Lang = "en") -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != constants.DOMAIN
        or not parsed.path.startswith(constants.FILE_PATH_PREFIX)
        or not parsed.path.lower().endswith(_EXCEL_SUFFIXES)
    ):
        raise_localized(
            InvalidInput,
            f"nl_stats: url must be an https .xlsx or .xls link under "
            f"{constants.SITE}{constants.FILE_PATH_PREFIX} (see nl_stats_list_files).",
            "nl_stats : url doit être un lien https vers un fichier .xlsx ou .xls sous "
            f"{constants.SITE}{constants.FILE_PATH_PREFIX} (voir nl_stats_list_files).",
            lang,
        )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ") if value.time() else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def _trim(rows: list[list[str]]) -> list[list[str]]:
    rows = rows[: constants.MAX_ROWS_PER_SHEET]
    while rows and not any(rows[-1]):
        rows.pop()
    width = max((max((i for i, c in enumerate(r) if c), default=-1) + 1 for r in rows), default=0)
    return [r[:width] + [""] * (width - len(r[:width])) for r in rows]


def _parse_xlsx(body: bytes) -> dict[str, list[list[str]]]:
    # openpyxl takes ~0.7 s to import, so it loads on first use.
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        return {
            sheet.title: _trim(
                [[_text(c) for c in row] for row in sheet.iter_rows(values_only=True)]
            )
            for sheet in workbook.worksheets
        }
    finally:
        workbook.close()


def _parse_xls(body: bytes) -> dict[str, list[list[str]]]:
    import xlrd

    book = xlrd.open_workbook(file_contents=body)
    sheets: dict[str, list[list[str]]] = {}
    for sheet in book.sheets():
        rows: list[list[str]] = []
        for r in range(min(sheet.nrows, constants.MAX_ROWS_PER_SHEET)):
            row: list[str] = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    serial = float(cell.value)
                    row.append(_text(xlrd.xldate.xldate_as_datetime(serial, book.datemode)))
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    row.append("")
                else:
                    row.append(_text(cell.value))
            rows.append(row)
        sheets[sheet.name] = _trim(rows)
    return sheets


async def _workbook(url: str, lang: Lang = "en") -> tuple[dict[str, list[list[str]]], bool]:
    async def fetch() -> dict[str, list[list[str]]]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=120.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise_localized(
                    NotFound,
                    f"nl_stats: no file at {url}.",
                    f"nl_stats : aucun fichier à {url}.",
                    lang,
                )
            raise_localized(
                UpstreamError,
                f"nl_stats: {url} returned HTTP {status}.",
                f"nl_stats : {url} a renvoyé le code HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"nl_stats: {url} did not respond in time.",
                f"nl_stats : {url} n'a pas répondu à temps.",
                lang,
            )
        body = response.content
        if len(body) > constants.MAX_FILE_BYTES:
            raise_localized(
                UpstreamError,
                f"nl_stats: {url} is larger than this tool reads.",
                f"nl_stats : {url} dépasse la taille que cet outil peut lire.",
                lang,
            )
        if body.lstrip()[:5].lower() in (b"<!doc", b"<html"):
            raise_localized(
                NotFound,
                f"nl_stats: {url} returned a web page, not an Excel file.",
                f"nl_stats : {url} a renvoyé une page Web, pas un fichier Excel.",
                lang,
            )
        parse = _parse_xlsx if url.lower().endswith(".xlsx") else _parse_xls
        try:
            return await run_parse(parse, body)
        except Exception as exc:  # openpyxl and xlrd raise several unrelated types
            raise_localized(
                UpstreamError,
                f"nl_stats: could not read {url}: {exc}",
                f"nl_stats : impossible de lire {url} ({exc})",
                lang,
            )

    return await cached_fetch(f"nl_stats:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch)


def guess_header(rows: list[list[str]]) -> int | None:
    """0-based index of the first row with at least three filled cells."""
    for index, row in enumerate(rows[:30]):
        if sum(1 for cell in row if cell) >= 3:
            return index
    return None


async def read_file(
    url: str,
    sheet: str | None = None,
    contains: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileData:
    check_file_url(url, lang)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"nl_stats: limit must be 1 to {constants.ROWS_LIMIT_MAX}.",
            f"nl_stats : limit doit être entre 1 et {constants.ROWS_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "nl_stats: offset must be 0 or more.",
            "nl_stats : offset doit être égal ou supérieur à 0.",
            lang,
        )

    sheets, cached = await _workbook(url, lang)
    if not sheets:
        raise_localized(
            UpstreamError,
            f"nl_stats: {url} has no sheets.",
            f"nl_stats : {url} ne contient aucune feuille.",
            lang,
        )
    if sheet is None:
        chosen = next(iter(sheets))
    else:
        matches = [name for name in sheets if name.casefold() == sheet.strip().casefold()]
        if not matches:
            raise_localized(
                InvalidInput,
                f"nl_stats: no sheet {sheet!r}; sheets are {list(sheets)}.",
                f"nl_stats : aucune feuille {sheet!r}; les feuilles sont {list(sheets)}.",
                lang,
            )
        chosen = matches[0]

    rows = sheets[chosen]
    header_index = guess_header(rows)
    header = rows[header_index] if header_index is not None else []
    body = rows[header_index + 1 :] if header_index is not None else rows
    body = [r for r in body if any(r)]
    if contains:
        wanted = contains.casefold()
        body = [r for r in body if any(wanted in cell.casefold() for cell in r)]
    total = len(body)
    return FileData(
        url=url,
        format=url.lower().rsplit(".", 1)[1],
        sheets=[
            SheetInfo(name=name, rows=len(r), columns=len(r[0]) if r else 0)
            for name, r in sheets.items()
        ],
        sheet=chosen,
        header_row=None if header_index is None else header_index + 1,
        header=header,
        rows=body[offset : offset + limit],
        total_rows=total,
        offset=offset,
        truncated=offset + limit < total,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="nl_stats.FileData",
            freshness=pick(
                lang,
                "As published by the NL Statistics Agency.",
                "Tel que publié par l'agence de la statistique de Terre-Neuve-et-Labrador "
                "(Newfoundland and Labrador Statistics Agency).",
            ),
            coverage=pick(
                lang,
                f"Sheet {chosen!r} of {len(sheets)}.",
                f"Feuille {chosen!r} sur {len(sheets)}. Contenu des feuilles en anglais "
                "seulement.",
            ),
            limits=(
                pick(
                    lang,
                    f"Sheets are read up to {constants.MAX_ROWS_PER_SHEET} rows; showing rows "
                    f"{offset + 1} to {offset + min(limit, total - offset)} of {total}.",
                    f"Les feuilles sont lues jusqu'à {constants.MAX_ROWS_PER_SHEET} lignes; "
                    f"lignes {offset + 1} à {offset + min(limit, total - offset)} sur {total}.",
                )
                if offset + limit < total
                else None
            ),
            lang=lang,
        ),
    )
