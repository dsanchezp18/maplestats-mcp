"""Client for Finance Canada's publication feed and the Fiscal Reference Tables.

Checked live 2026-10-03 against the 2019, 2021 and 2025 workbooks in
English and French:

1. The publications pages are empty until a script fills them from
   /content/dam/fin/documents/publications/pub-rep/json.json (252 entries
   with type, English and French title and link, date). It lists the five
   newest Fiscal Reference Tables editions (2021-2025) and every Fiscal
   Monitor since January 2021. The 2019 and 2020 workbooks are still on
   canada.ca at the same path pattern; 2014-2018 answer a redirect to an
   error page.
2. canada.ca refuses a TLS handshake that offers HTTP/1.1 only, as StatCan
   does, so the shared HTTP/2-capable client is required.
3. Each table is a sheet whose column A holds "Table 3" ("Tableau 3"),
   then one to three title rows, then up to six header rows in which a
   column's name is split over several rows ("Personal" / "income" /
   "tax", "Non-" / "resident"), a units row like "(millions of dollars)"
   (column A or the first value column, sometimes one per column group),
   the data rows labelled in column A ("1966-67", "2024-25 Interim",
   "1991", "    Currency and deposits") and notes ("Sources: ...", "(1)
   ..."). Balance-sheet tables put years across the header and items down
   column A, with section rows ("Liabilities") that have no numbers.
4. The 2019 edition puts two tables on one sheet ("18-19 NFLD+PEI", the
   second marker written twice); later editions use one sheet per table.
5. Cells are numbers with float noise (-347.4000000000001) or "-" for
   none; a French sheet declares 16,384 columns, so reads are capped.
6. Divider sheets ("Fed - PA", "Prov - PA", "NA", "Int"; "Fed - CP",
   "Prov - CP", "CEN", "Int" in French) open each part of the workbook.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.finance_canada import constants
from maplestats_mcp.modules.finance_canada.schemas import (
    FrtEdition,
    FrtTable,
    FrtTableInfo,
    FrtTableList,
    Value,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import check_deadline, run_parse
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_MARKER = re.compile(r"^\s*(?:Table|Tableau)\s+(\d+)\s*$", re.IGNORECASE)
_UNIT = re.compile(r"^\(.*\)$")
_NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?$")
_EMPTY_VALUES = {"-", "–", "—", "..", "...", "n/a", "s.o."}


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _say(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


async def fetch(url: str, max_bytes: int, lang: str = "en") -> httpx.Response:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (301, 302, 404, 410):
            _raise(
                NotFound,
                f"finance_canada: nothing at {url} (HTTP {status}).",
                f"finance_canada : rien à {url} (HTTP {status}).",
                lang,
            )
        _raise(
            UpstreamError,
            f"finance_canada: {url} returned HTTP {status}.",
            f"finance_canada : {url} a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        _raise(
            UpstreamUnavailable,
            f"finance_canada: {url} did not respond in time.",
            f"finance_canada : {url} n'a pas répondu à temps.",
            lang,
        )
    if len(response.content) > max_bytes:
        _raise(
            UpstreamError,
            f"finance_canada: {url} is much larger than expected.",
            f"finance_canada : {url} est beaucoup plus volumineux que prévu.",
            lang,
        )
    return response


async def feed(lang: str = "en") -> tuple[list[dict[str, Any]], bool]:
    """Every entry of the Finance publications feed."""

    async def load() -> list[dict[str, Any]]:
        body = (await fetch(constants.FEED_URL, constants.FEED_MAX_BYTES, lang)).content
        try:
            entries = json.loads(body.decode("utf-8-sig"))["data"]
        except (ValueError, KeyError, TypeError):
            _raise(
                UpstreamError,
                "finance_canada: the publications feed is not the expected JSON.",
                "finance_canada : le fil des publications n'est pas le JSON attendu.",
                lang,
            )
        if not isinstance(entries, list) or not entries:
            _raise(
                UpstreamError,
                "finance_canada: the publications feed is empty.",
                "finance_canada : le fil des publications est vide.",
                lang,
            )
        return [e for e in entries if isinstance(e, dict)]

    return await cached_fetch("finance_canada:feed", constants.FEED_TTL_SECONDS, load)


def _workbook_url(year: int, lang: str) -> str:
    return constants.FRT_WORKBOOK.format(
        year=year, yy=year % 100, suffix=constants.WORKBOOK_SUFFIX[lang]
    )


def frt_editions(entries: list[dict[str, Any]], lang: str) -> list[FrtEdition]:
    """Editions in the feed, plus older ones still on canada.ca, newest first."""
    found: dict[int, FrtEdition] = {}
    for entry in entries:
        if entry.get("pub-type") != "Fiscal Reference Tables":
            continue
        link = str(entry.get("link-fr" if lang == "fr" else "link") or "")
        match = re.search(r"/(\d{4})\.html$", link)
        if not match:
            continue
        year = int(match.group(1))
        found[year] = FrtEdition(
            edition=year,
            title=str(entry.get("title-fr" if lang == "fr" else "title") or ""),
            published=str(entry.get("pub-date") or "") or None,
            page_url=link,
            workbook_url=_workbook_url(year, lang),
        )
    if found:
        for year in range(constants.FIRST_FRT_EDITION, min(found)):
            title = (
                "Tableaux de référence financiers" if lang == "fr" else "Fiscal Reference Tables"
            )
            found[year] = FrtEdition(
                edition=year,
                title=f"{title} {year}",
                page_url=constants.FRT_PAGE[lang].format(year=year),
                workbook_url=_workbook_url(year, lang),
            )
    return sorted(found.values(), key=lambda e: -e.edition)


# ------------------------------------------------------------- workbook


@dataclass
class ParsedTable:
    info: FrtTableInfo
    rows: list[dict[str, Value]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return " ".join(str(value).split())


def _number(value: Any) -> Value:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        rounded = round(float(value), 6)
        return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded
    text = " ".join(str(value).split())
    if not text or text.casefold() in _EMPTY_VALUES:
        return None
    cleaned = text.replace(",", "")
    if _NUMERIC.match(cleaned):
        return _number(float(cleaned))
    return text


def _is_value(value: Any) -> bool:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return True
    text = _text(value)
    return bool(text) and (text in _EMPTY_VALUES or bool(_NUMERIC.match(text.replace(",", ""))))


def _join(parts: list[str]) -> str:
    name = ""
    for part in parts:
        if not name:
            name = part
        elif name.endswith("-"):
            name += part
        else:
            name += " " + part
    return name.strip()


def parse_block(
    grid: list[list[Any]], number: int, sheet: str, part: str | None
) -> ParsedTable | None:
    """One table: the rows after its 'Table N' marker row."""
    width = max((len(r) for r in grid), default=0)
    rows = [list(r) + [None] * (width - len(r)) for r in grid]

    def filled(row: list[Any]) -> list[int]:
        return [i for i, v in enumerate(row) if _text(v)]

    is_data = [
        bool(_text(r[0])) and not _UNIT.match(_text(r[0])) and any(_is_value(v) for v in r[1:])
        for r in rows
    ]
    if not any(is_data):
        return None
    first_data = is_data.index(True)
    last_data = len(is_data) - 1 - is_data[::-1].index(True)

    title: list[str] = []
    header_rows: list[list[Any]] = []
    units: dict[int, str] = {}
    sections_before: str | None = None
    for row in rows[:first_data]:
        cells = filled(row)
        if not cells:
            continue
        texts = [_text(row[i]) for i in cells]
        if all(_UNIT.match(t) for t in texts):
            for i in cells:
                units[i] = _text(row[i])
            continue
        if cells == [0]:
            if header_rows:
                sections_before = texts[0]
            elif not _MARKER.match(texts[0]):
                title.append(texts[0])
            continue
        header_rows.append(row)

    columns: list[str] = []
    for c in range(width):
        parts = [_text(r[c]) for r in header_rows if _text(r[c])]
        name = _join(parts) or ("row" if c == 0 else "")
        columns.append(name)
    # Units carry right until the next unit cell; one in column A covers all.
    unit_list = [units[k] for k in sorted(units)]
    used = [0] + [
        c
        for c in range(1, width)
        if columns[c] or any(_text(r[c]) for r in rows[first_data : last_data + 1])
    ]
    names: list[str] = []
    for c in used:
        base = columns[c] or f"column {c + 1}"
        name, n = base, 2
        while name in names:
            name = f"{base} ({n})"
            n += 1
        names.append(name)

    data: list[dict[str, Value]] = []
    section = sections_before
    notes: list[str] = []
    for index, row in enumerate(rows[first_data:], start=first_data):
        check_deadline()
        label = _text(row[0])
        if is_data[index]:
            record: dict[str, Value] = {names[0]: label}
            for name, c in zip(names[1:], used[1:], strict=True):
                record[name] = _number(row[c])
            if section:
                record["section"] = section
            data.append(record)
        elif label and filled(row) == [0]:
            if index < last_data:
                section = label
            else:
                notes.append(label)
    info = FrtTableInfo(
        number=number,
        title=" ".join(title) or sheet,
        part=part,
        sheet=sheet,
        columns=names,
        units=unit_list,
        row_count=len(data),
        first_row=str(data[0][names[0]]) if data else None,
        last_row=str(data[-1][names[0]]) if data else None,
    )
    return ParsedTable(info=info, rows=data, notes=notes)


def parse_workbook(body: bytes, lang: str) -> list[ParsedTable]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        tables: list[ParsedTable] = []
        part: str | None = None
        for sheet in workbook.worksheets:
            divider = constants.PARTS.get(sheet.title.strip().casefold())
            if divider:
                part = divider[1] if lang == "fr" else divider[0]
                continue
            grid = [
                list(r)
                for r in sheet.iter_rows(
                    max_row=constants.MAX_SHEET_ROWS,
                    max_col=constants.MAX_SHEET_COLUMNS,
                    values_only=True,
                )
            ]
            markers: list[tuple[int, int]] = []
            for i, row in enumerate(grid):
                match = _MARKER.match(_text(row[0]) if row else "")
                # The 2019 two-table sheets write the second marker twice.
                if match and not (markers and markers[-1][1] == int(match.group(1))):
                    markers.append((i, int(match.group(1))))
            for k, (start, number) in enumerate(markers):
                end = markers[k + 1][0] if k + 1 < len(markers) else len(grid)
                block = [
                    r for r in grid[start + 1 : end] if not _MARKER.match(_text(r[0]) if r else "")
                ]
                parsed = parse_block(block, number, sheet.title, part)
                if parsed is not None:
                    tables.append(parsed)
        return tables
    finally:
        workbook.close()


async def _edition(edition: int | None, lang: str) -> FrtEdition:
    entries, _ = await feed(lang)
    editions = frt_editions(entries, lang)
    if not editions:
        _raise(
            UpstreamError,
            "finance_canada: the feed lists no Fiscal Reference Tables.",
            "finance_canada : le fil ne liste aucun Tableau de référence financier.",
            lang,
        )
    if edition is None:
        return editions[0]
    for item in editions:
        if item.edition == edition:
            return item
    known = [e.edition for e in editions]
    _raise(
        NotFound,
        f"finance_canada: no Fiscal Reference Tables workbook for {edition}; editions are "
        f"{known} (earlier ones are PDF only).",
        f"finance_canada : aucun classeur des Tableaux de référence financiers pour {edition} ; "
        f"les éditions sont {known} (les plus anciennes n'existent qu'en PDF).",
        lang,
    )


async def _tables(edition: FrtEdition, lang: str) -> tuple[list[ParsedTable], bool]:
    async def load() -> list[ParsedTable]:
        response = await fetch(edition.workbook_url, constants.MAX_WORKBOOK_BYTES, lang)
        if not response.content.startswith(b"PK"):
            _raise(
                UpstreamError,
                f"finance_canada: {edition.workbook_url} is not an Excel file.",
                f"finance_canada : {edition.workbook_url} n'est pas un fichier Excel.",
                lang,
            )
        tables = await run_parse(parse_workbook, response.content, lang)
        if len(tables) < 20:
            _raise(
                UpstreamError,
                f"finance_canada: only {len(tables)} tables read from the {edition.edition} "
                "workbook; its layout changed.",
                f"finance_canada : seulement {len(tables)} tableaux lus dans le classeur "
                f"{edition.edition} ; sa structure a changé.",
                lang,
            )
        return tables

    return await cached_fetch(
        f"finance_canada:frt:{edition.edition}:{lang}", constants.WORKBOOK_TTL_SECONDS, load
    )


def _provenance(url: str, cached: bool, schema: str, lang: str, coverage: str | None) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"finance_canada.{schema}",
        freshness=_say(
            "one edition a year (autumn), after the Annual Financial Report",
            "une édition par année (à l'automne), après le Rapport financier annuel",
            lang,
        ),
        coverage=coverage,
        licence=_say(constants.TERMS, constants.TERMS_FR, lang),
        lang=lang,
    )


async def list_frt_tables(
    edition: int | None = None, *, query: str = "", lang: str = "en"
) -> FrtTableList:
    """The editions, and the tables of one edition matching `query`."""
    chosen = await _edition(edition, lang)
    entries, _ = await feed(lang)
    tables, cached = await _tables(chosen, lang)
    words = fold(query).split()
    found = [
        t.info
        for t in tables
        if all(
            w in fold(" ".join([t.info.title, t.info.part or "", t.info.sheet, *t.info.columns]))
            for w in words
        )
    ]
    return FrtTableList(
        editions=frt_editions(entries, lang),
        edition=chosen.edition,
        tables=found,
        total_matched=len(found),
        provenance=_provenance(
            chosen.workbook_url,
            cached,
            "FrtTableList",
            lang,
            _say(f"{len(tables)} tables", f"{len(tables)} tableaux", lang),
        ),
    )


async def get_frt_table(
    table: int,
    *,
    edition: int | None = None,
    last: int | None = None,
    lang: str = "en",
) -> FrtTable:
    """One table of an edition by number, optionally only its last `last` rows."""
    if last is not None and last < 1:
        _raise(
            InvalidInput,
            "finance_canada: last must be 1 or more.",
            "finance_canada : last doit valoir 1 ou plus.",
            lang,
        )
    chosen = await _edition(edition, lang)
    tables, cached = await _tables(chosen, lang)
    for parsed in tables:
        if parsed.info.number == table:
            rows = parsed.rows[-last:] if last else parsed.rows
            return FrtTable(
                edition=chosen,
                info=parsed.info,
                rows=rows,
                notes=parsed.notes,
                provenance=_provenance(
                    chosen.workbook_url,
                    cached,
                    "FrtTable",
                    lang,
                    _say(
                        f"last {len(rows)} of {parsed.info.row_count} rows",
                        f"les {len(rows)} dernières lignes sur {parsed.info.row_count}",
                        lang,
                    )
                    if last
                    else None,
                ),
            )
    numbers = sorted(t.info.number for t in tables)
    _raise(
        NotFound,
        f"finance_canada: no table {table} in the {chosen.edition} edition; tables are "
        f"{numbers[0]}-{numbers[-1]} (see finance_frt_list_tables).",
        f"finance_canada : aucun tableau {table} dans l'édition {chosen.edition} ; les "
        f"tableaux vont de {numbers[0]} à {numbers[-1]} (voir finance_frt_list_tables).",
        lang,
    )
