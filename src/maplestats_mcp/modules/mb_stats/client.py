"""Manitoba Bureau of Statistics: indicators, file catalogue and Excel tables.

The Bureau has no API. Its pages read two CSV files in the browser (the
indicator tiles and the file catalogue); this module reads the same files and
the Excel data tables they list, sheet by sheet, as published text.
"""

from __future__ import annotations

import csv
import html
import io
import re
from typing import Literal, NoReturn
from urllib.parse import urlparse

from maplestats_mcp.modules.mb_stats import constants
from maplestats_mcp.modules.mb_stats.schemas import (
    FileData,
    FileEntry,
    FileKind,
    FileList,
    Indicator,
    IndicatorList,
    SheetInfo,
)
from maplestats_mcp.shared import file_download, xlsx_sheets
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
KindChoice = Literal["data_table", "document", "link", "any"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TAGS = re.compile(r"<[^>]+>")
_NO = frozenset({"", "NO", "N/A"})
# Fields of a quick-facts row read from the front and from the back; the
# summary between them holds unquoted commas (live 2026-11-24).
_HEAD = (
    "id",
    "title",
    "category",
    "reference_period",
    "value",
    "data_type",
    "change",
    "direction",
    "change_context",
    "powerbi",
)
_TAIL = ("subcategory", "category_order", "subcategory_order", "tile_order", "key")


def _fail(cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(cls, f"mb_stats: {en}", f"mb_stats : {fr}", lang)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(html.unescape(_TAGS.sub(" ", value)).replace("\xa0", " ").split())
    text = text.strip(' "')
    return None if text.upper() in _NO else text


async def _download(url: str, max_bytes: int, ttl: int, lang: Lang) -> tuple[bytes, bool]:
    async def fetch() -> file_download.Downloaded:
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host == constants.DOMAIN,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=max_bytes,
            context="mb_stats",
            timeout=120.0,
        )
        # A web page in place of the file is an outage or error page served with
        # HTTP 200, not proof that the file does not exist (it was called NotFound,
        # which sent callers looking for a missing file), so it is an upstream error.
        # It is refused here, before cached_download stores it: stored, it was
        # rejected on every call for the whole cache window, after the site had
        # recovered.
        if downloaded.body[:256].lstrip()[:5].lower() in (b"<!doc", b"<html"):
            _fail(
                UpstreamError,
                f"{url} returned a web page, not a file.",
                f"{url} a renvoyé une page Web, pas un fichier.",
                lang,
            )
        return downloaded

    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), ttl, fetch
    )
    return downloaded.body, cached


def parse_quick_facts(text: str) -> list[dict[str, str]]:
    """Indicator rows from manitoba_quick_facts.csv, mended where the summary split them."""
    records: list[list[str]] = []
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0].strip().isdigit():
            records.append(row)
        elif records and row[0] != "Id":
            # A summary broken across lines: the rest of the previous record.
            records[-1].extend(row)
    parsed: list[dict[str, str]] = []
    for row in records:
        if len(row) < len(_HEAD) + len(_TAIL):
            continue
        record: dict[str, str] = dict(zip(_HEAD, row[: len(_HEAD)], strict=True))
        record.update(zip(_TAIL, row[-len(_TAIL) :], strict=True))
        record["summary"] = ",".join(row[len(_HEAD) : -len(_TAIL)])
        parsed.append(record)
    return parsed


def parse_reports(text: str) -> list[dict[str, str]]:
    return [
        {k.strip(): (v or "").strip() for k, v in row.items() if k}
        for row in csv.DictReader(io.StringIO(text))
    ]


async def _quick_facts(lang: Lang) -> tuple[list[dict[str, str]], bool]:
    async def fetch() -> list[dict[str, str]]:
        body, _ = await _download(
            constants.QUICK_FACTS_URL,
            constants.MAX_LIST_BYTES,
            constants.CACHE_TTL_LIST_SECONDS,
            lang,
        )
        rows = parse_quick_facts(body.decode("utf-8", errors="replace"))
        if not rows:
            _fail(
                UpstreamError,
                f"{constants.QUICK_FACTS_URL} has no indicator rows; its layout may have changed.",
                f"{constants.QUICK_FACTS_URL} ne contient aucun indicateur ; sa mise en page a "
                "peut-être changé.",
                lang,
            )
        return rows

    return await cached_fetch("mb_stats:quick_facts", constants.CACHE_TTL_LIST_SECONDS, fetch)


async def _reports(lang: Lang) -> tuple[list[dict[str, str]], bool]:
    async def fetch() -> list[dict[str, str]]:
        body, _ = await _download(
            constants.REPORTS_URL, constants.MAX_LIST_BYTES, constants.CACHE_TTL_LIST_SECONDS, lang
        )
        rows = parse_reports(body.decode("utf-8", errors="replace"))
        if not rows or "FileName" not in rows[0]:
            _fail(
                UpstreamError,
                f"{constants.REPORTS_URL} has no FileName column; its layout may have changed.",
                f"{constants.REPORTS_URL} n'a pas de colonne FileName ; sa mise en page a "
                "peut-être changé.",
                lang,
            )
        return rows

    return await cached_fetch("mb_stats:reports", constants.CACHE_TTL_LIST_SECONDS, fetch)


def _kind(name: str) -> FileKind:
    if name.lower().startswith(("http://", "https://")):
        return "link"
    return "data_table" if name.lower().endswith((".xlsx", ".xls")) else "document"


def _file_url(name: str) -> str:
    return name if _kind(name) == "link" else constants.PUBLICATIONS_URL + name


def catalogue(rows: list[dict[str, str]]) -> list[FileEntry]:
    """One entry per file, newest first, with every indicator it is listed under."""
    files: dict[str, FileEntry] = {}
    for row in rows:
        name = row.get("FileName", "")
        if not name:
            continue
        indicator = row.get("Related_indicatorId", "")
        entry = files.get(name)
        if entry is None:
            entry = FileEntry(
                title=" ".join(row.get("displayName", "").split()) or name,
                released=row.get("Date Released") or None,
                report_type=row.get("ReportType") or "",
                kind=_kind(name),
                indicators=[],
                url=_file_url(name),
            )
            files[name] = entry
        if indicator.isdigit() and int(indicator) not in entry.indicators:
            entry.indicators.append(int(indicator))
    return sorted(files.values(), key=lambda f: f.released or "", reverse=True)


def _provenance(url: str, cached: bool, schema: str, coverage: str, limits: str | None, lang: Lang):
    return make_provenance(
        source=constants.PROVENANCE_SOURCE,
        url=url,
        cached=cached,
        schema_name=schema,
        freshness=pick(
            lang,
            "As published by the Manitoba Bureau of Statistics; files update with each release.",
            "Tel que publié par le Bureau des statistiques du Manitoba ; les fichiers changent "
            "à chaque diffusion.",
        ),
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


async def list_indicators(
    category: str | None = None, query: str | None = None, lang: Lang = "en"
) -> IndicatorList:
    facts, cached = await _quick_facts(lang)
    reports, _ = await _reports(lang)
    counts: dict[int, int] = {}
    for file in catalogue(reports):
        for ident in file.indicators:
            counts[ident] = counts.get(ident, 0) + 1
    indicators: list[Indicator] = []
    for row in facts:
        ident = int(row["id"])
        summary = _clean(row.get("summary"))
        indicators.append(
            Indicator(
                id=ident,
                title=_clean(row["title"]) or str(ident),
                category=_clean(row["category"]) or "",
                subcategory=_clean(row.get("subcategory")),
                reference_period=_clean(row.get("reference_period")),
                value=_clean(row.get("value")),
                data_type=_clean(row.get("data_type")),
                change=_clean(row.get("change")),
                change_context=_clean(row.get("change_context")),
                key_indicator=(row.get("key") or "").strip().upper() == "TRUE",
                summary=summary[: constants.SUMMARY_CHARS] if summary else None,
                files=counts.get(ident, 0),
                page_url=constants.INDICATOR_PAGE_URL.format(id=ident),
            )
        )
    categories = sorted({i.category for i in indicators})
    if category:
        wanted = category.casefold()
        indicators = [i for i in indicators if wanted in i.category.casefold()]
    if query:
        words = query.casefold().split()
        indicators = [
            i
            for i in indicators
            if all(w in f"{i.title} {i.category} {i.subcategory or ''}".casefold() for w in words)
        ]
    return IndicatorList(
        indicators=indicators,
        categories=categories,
        provenance=_provenance(
            constants.QUICK_FACTS_URL,
            cached,
            "mb_stats.IndicatorList",
            pick(
                lang,
                "The Bureau's indicator tiles (gov.mb.ca/mbs): latest value and change as "
                "shown on its home page; the 'Archives' category holds discontinued series with "
                "no value.",
                "Les tuiles d'indicateurs du Bureau (gov.mb.ca/mbs) : dernière valeur et "
                "variation affichées sur sa page d'accueil ; la catégorie « Archives » regroupe "
                "des séries abandonnées sans valeur. Textes en anglais seulement.",
            ),
            None,
            lang,
        ),
    )


async def list_files(
    query: str | None = None,
    indicator: int | None = None,
    kind: KindChoice = "data_table",
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    if not 1 <= limit <= constants.FILES_LIMIT_MAX:
        _fail(
            InvalidInput,
            f"limit must be 1 to {constants.FILES_LIMIT_MAX}.",
            f"limit doit être entre 1 et {constants.FILES_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        _fail(InvalidInput, "offset must be 0 or more.", "offset doit être 0 ou plus.", lang)
    reports, cached = await _reports(lang)
    files = catalogue(reports)
    if kind != "any":
        files = [f for f in files if f.kind == kind]
    if indicator is not None:
        files = [f for f in files if indicator in f.indicators]
    if query:
        words = query.casefold().split()
        files = [
            f
            for f in files
            if all(w in f"{f.title} {f.report_type} {f.url}".casefold() for w in words)
        ]
    total = len(files)
    page = files[offset : offset + limit]
    more = offset + len(page) < total
    return FileList(
        files=page,
        total_files=total,
        offset=offset,
        truncated=more,
        provenance=_provenance(
            constants.REPORTS_URL,
            cached,
            "mb_stats.FileList",
            pick(
                lang,
                "The Bureau's file catalogue (mbs_report.csv), newest first: Excel data tables, "
                "PDF bulletins, reports, infographics and electoral division profiles, and "
                "links to Statistics Canada tables.",
                "Le catalogue de fichiers du Bureau (mbs_report.csv), du plus récent au plus "
                "ancien : tableaux Excel, bulletins, rapports, infographies et profils des "
                "circonscriptions en PDF, et liens vers des tableaux de Statistique Canada. "
                "Titres en anglais seulement.",
            ),
            pick(
                lang,
                f"files {offset + 1} to {offset + len(page)} of {total}; pass offset="
                f"{offset + len(page)} for more",
                f"fichiers {offset + 1} à {offset + len(page)} sur {total} ; passez offset="
                f"{offset + len(page)} pour la suite",
            )
            if more
            else None,
            lang,
        ),
    )


def check_file_url(url: str, lang: Lang = "en") -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != constants.DOMAIN
        or not parsed.path.startswith(constants.PUBLICATIONS_PATH)
        or not parsed.path.lower().endswith(".xlsx")
    ):
        _fail(
            InvalidInput,
            f"url must be an https .xlsx link under {constants.PUBLICATIONS_URL} (see "
            "mb_stats_list_files).",
            f"url doit être un lien https vers un fichier .xlsx sous {constants.PUBLICATIONS_URL} "
            "(voir mb_stats_list_files).",
            lang,
        )


async def read_file(
    url: str,
    sheet: str | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileData:
    check_file_url(url, lang)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        _fail(
            InvalidInput,
            f"limit must be 1 to {constants.ROWS_LIMIT_MAX}.",
            f"limit doit être entre 1 et {constants.ROWS_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        _fail(InvalidInput, "offset must be 0 or more.", "offset doit être 0 ou plus.", lang)
    if header_row is not None and header_row < 1:
        _fail(
            InvalidInput,
            "header_row is 1-based (1 or more).",
            "header_row compte à partir de 1 (1 ou plus).",
            lang,
        )
    if not 1 <= header_rows <= constants.HEADER_ROWS_MAX:
        _fail(
            InvalidInput,
            f"header_rows must be 1 to {constants.HEADER_ROWS_MAX}.",
            f"header_rows doit être entre 1 et {constants.HEADER_ROWS_MAX}.",
            lang,
        )
    reports, _ = await _reports(lang)
    listed = next((f for f in catalogue(reports) if f.url == url), None)
    if listed is None:
        _fail(
            NotFound,
            f"{url} is not in the Bureau's file catalogue (see mb_stats_list_files).",
            f"{url} ne figure pas au catalogue du Bureau (voir mb_stats_list_files).",
            lang,
        )

    body, cached = await _download(
        url, constants.MAX_FILE_BYTES, constants.CACHE_TTL_FILE_SECONDS, lang
    )

    async def dims() -> list[tuple[str, int | None, int | None]]:
        return await run_parse(xlsx_sheets.sheet_dimensions, body)

    try:
        sizes, _ = await cached_fetch(
            f"mb_stats:sheets:{url}", constants.CACHE_TTL_FILE_SECONDS, dims
        )
    except UpstreamError:
        raise
    except Exception as exc:  # noqa: BLE001 (re-raised as UpstreamError)
        _fail(
            UpstreamError, f"could not read {url}: {exc}", f"impossible de lire {url} : {exc}", lang
        )
    names = [name for name, _r, _c in sizes]
    if not names:
        _fail(UpstreamError, f"{url} has no sheets.", f"{url} ne contient aucune feuille.", lang)
    if sheet is None:
        chosen = names[0]
    else:
        matches = [n for n in names if n.casefold() == sheet.strip().casefold()]
        if not matches:
            _fail(
                InvalidInput,
                f"no sheet {sheet!r}; sheets are {names}.",
                f"aucune feuille {sheet!r} ; les feuilles sont {names}.",
                lang,
            )
        chosen = matches[0]

    async def rows_of() -> tuple[list[list[str]], bool]:
        return await run_parse(xlsx_sheets.read_sheet, body, chosen, constants.MAX_ROWS_PER_SHEET)

    try:
        (rows, capped), _ = await cached_fetch(
            f"mb_stats:rows:{url}:{chosen}", constants.CACHE_TTL_FILE_SECONDS, rows_of
        )
    except (UpstreamError, InvalidInput):
        raise
    except Exception as exc:  # noqa: BLE001 (re-raised as UpstreamError)
        _fail(
            UpstreamError, f"could not read {url}: {exc}", f"impossible de lire {url} : {exc}", lang
        )
    if header_row is not None:
        if header_row > len(rows):
            _fail(
                InvalidInput,
                f"sheet {chosen!r} has only {len(rows)} rows.",
                f"la feuille {chosen!r} n'a que {len(rows)} lignes.",
                lang,
            )
        header_index: int | None = header_row - 1
    else:
        header_index = xlsx_sheets.guess_header(rows)
    if header_index is None:
        header: list[str] = []
        table = rows
    else:
        # A header spread over rows (month above year above units) is joined per
        # column; nothing is carried across columns.
        block = rows[header_index : header_index + header_rows]
        width = len(rows[0]) if rows else 0
        header = [" ".join(r[i] for r in block if i < len(r) and r[i]) for i in range(width)]
        table = rows[header_index + header_rows :]
    table = [r for r in table if any(r)]
    if contains:
        wanted = contains.casefold()
        table = [r for r in table if any(wanted in cell.casefold() for cell in r)]
    total = len(table)
    more = offset + limit < total
    notes: list[str] = []
    if sheet is None and len(names) > 1:
        notes.append(
            pick(
                lang,
                f"no sheet was requested, so the first of {len(names)} ({chosen!r}) was read",
                f"aucune feuille demandée : la première des {len(names)} ({chosen!r}) a été lue",
            )
        )
    if capped:
        notes.append(
            pick(
                lang,
                f"the sheet was read only up to {constants.MAX_ROWS_PER_SHEET} rows",
                f"la feuille n'a été lue que jusqu'à {constants.MAX_ROWS_PER_SHEET} lignes",
            )
        )
    if more:
        notes.append(
            pick(
                lang,
                f"showing rows {offset + 1} to {offset + limit} of {total}",
                f"lignes {offset + 1} à {offset + limit} sur {total}",
            )
        )
    width = len(rows[0]) if rows else 0
    return FileData(
        url=url,
        title=listed.title,
        sheets=[
            SheetInfo(name=n, rows=len(rows), columns=width)
            if n == chosen
            else SheetInfo(name=n, rows=r, columns=c)
            for n, r, c in sizes
        ],
        sheet=chosen,
        header_row=None if header_index is None else header_index + 1,
        header_rows=header_rows if header_index is not None else 0,
        header=header,
        rows=table[offset : offset + limit],
        total_rows=total,
        offset=offset,
        truncated=more or capped,
        provenance=_provenance(
            url,
            cached,
            "mb_stats.FileData",
            pick(
                lang,
                f"{listed.title} (released {listed.released}), sheet {chosen!r} of {len(names)}.",
                f"{listed.title} (diffusé le {listed.released}), feuille {chosen!r} sur "
                f"{len(names)}. Contenu en anglais seulement.",
            ),
            pick(lang, "; ", " ; ").join(notes) or None,
            lang,
        ),
    )
