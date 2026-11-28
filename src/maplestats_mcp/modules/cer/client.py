"""Client for Canada Energy Regulator open data.

Discovery reuses the federal CKAN client (the CER's own catalogue is
open.canada.ca's `cer-rec` organization); rows come straight from the
CER's CSV files, restricted to CER hosts. See constants.py for the
encoding and error-page quirks confirmed live.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import NoReturn
from urllib.parse import urlparse

from maplestats_mcp.modules.cer import constants
from maplestats_mcp.modules.cer.schemas import CerDataset, CerDatasetList, CerFile, CerRows
from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.shared import csv_files
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import fr_number, french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


# English files sit under /open/ and French ones under /ouvert/; a French
# call reading an English file is told where the French twin is.
_ENGLISH_FILE_FR = french_spacing(
    "Ce fichier est la version anglaise : ses colonnes et ses valeurs sont en anglais. "
    "La version française se trouve sous /ouvert/ (voir cer_list_datasets avec lang='fr')."
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English text unchanged; French goes through the typed-error template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


async def list_datasets(query: str = "", *, limit: int = 10, lang: str = "en") -> CerDatasetList:
    """CER datasets with CSV files, each file in the requested language."""
    if limit < 1 or limit > 25:
        _raise(
            InvalidInput,
            f"limit must be between 1 and 25, got {limit}.",
            f"limit doit être compris entre 1 et 25, reçu {limit}.",
            lang,
        )
    found = await ckan.search_datasets(
        "federal",
        query,
        fq=f"organization:{constants.CATALOGUE_ORG} AND res_format:CSV",
        rows=limit,
        lang=lang,
    )
    datasets: list[CerDataset] = []
    for package in found.packages:
        detail = await ckan.get_dataset("federal", package.id, lang)
        files = [
            CerFile(name=r.name, url=r.url or "", language=r.language[0] if r.language else None)
            for r in detail.resources
            if (r.format or "").upper() == "CSV"
            and r.url
            and (not r.language or lang in r.language)
        ]
        if files:
            datasets.append(CerDataset(id=detail.id, title=detail.title, files=files))
    return CerDatasetList(
        datasets=datasets,
        total_count=found.total_count,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=found.provenance.url,
            cached=found.provenance.cached,
            schema_name="cer.CerDatasetList",
            coverage=(
                f"{len(datasets)} of {found.total_count} CER datasets with CSV files"
                if lang != "fr"
                else f"{len(datasets)} jeux de données de la Régie de l'énergie du Canada "
                f"avec fichiers CSV, sur {found.total_count}"
            ),
            lang=lang,
        ),
    )


async def _download(url: str, lang: str = "en") -> tuple[list[dict[str, str]], bool]:
    # The shared CSV helpers word their errors in English only; a French call
    # checks the URL here first and rewords a missing-file answer itself.
    if lang == "fr":
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in constants.ALLOWED_HOSTS:
            raise_typed(
                InvalidInput,
                f"cer : url doit être un lien https sur {sorted(constants.ALLOWED_HOSTS)}.",
                "fr",
            )
        if not parsed.path.lower().endswith(".csv"):
            raise_typed(InvalidInput, "cer : url doit pointer vers un fichier .csv.", "fr")
    csv_files.check_url(url, constants.ALLOWED_HOSTS, "cer")
    try:
        return await csv_files.fetch_rows(
            url,
            limiter=_LIMITER,
            ttl=constants.CACHE_TTL_FILE_SECONDS,
            context="cer",
            allowed_hosts=constants.ALLOWED_HOSTS,
        )
    except NotFound:
        if lang != "fr":
            raise
        raise_typed(
            NotFound,
            f"cer : aucun fichier CSV à {url} (adresse introuvable, ou page web renvoyée au "
            "lieu d'un CSV).",
            "fr",
        )


def _row_date(value: str) -> date | None:
    value = value.strip()
    try:
        if len(value) == 4 and value.isdigit():
            return date(int(value), 1, 1)
        if len(value) == 7 and value[4] == "-":
            return date(int(value[:4]), int(value[5:7]), 1)
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_QUARTER = re.compile(
    r"(?:(?P<year1>\d{4})[\s/-]*[QT](?P<q1>[1-4])|[QT](?P<q2>[1-4])[\s/-]*(?P<year2>\d{4}))",
    re.IGNORECASE,
)
_YEAR_FIRST = re.compile(r"(\d{4})[/.-](\d{1,2})(?:[/.-](\d{1,2}))?")
_YEAR_LAST = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")


def _month_span(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _row_span(value: str) -> tuple[date, date] | None:
    """The first and last day a row's date cell stands for; None when it cannot be read.

    A year or a month covers its whole period, so "2024" is 2024-01-01 to 2024-12-31 and
    is compared with start and end as that span. Read as its first day, it fell before
    start="2024-06" and a file whose only date column is a year lost every 2024 row.
    Besides the ISO forms, quarters ("2024-Q1", "Q1 2024", "T1 2024"), "2024/01/31" and a
    day-month-year or month-day-year with a four-digit year are read; the last is read only
    when one order is possible (31/01/2024, 01/31/2024), never guessed for 07/08/2024.
    """
    value = value.strip()
    try:
        first = _row_date(value)
        if first is not None:
            if len(value) == 4:
                return date(first.year, 1, 1), date(first.year, 12, 31)
            if len(value) == 7 and value[4] == "-":
                return _month_span(first.year, first.month)
            return first, first
        quarter = _QUARTER.fullmatch(value)
        if quarter:
            year = int(quarter["year1"] or quarter["year2"])
            first_month = 3 * (int(quarter["q1"] or quarter["q2"]) - 1) + 1
            return date(year, first_month, 1), _month_span(year, first_month + 2)[1]
        year_first = _YEAR_FIRST.fullmatch(value)
        if year_first:
            year, month = int(year_first[1]), int(year_first[2])
            if year_first[3] is None:
                return _month_span(year, month)
            day = date(year, month, int(year_first[3]))
            return day, day
        year_last = _YEAR_LAST.fullmatch(value)
        if year_last:
            a, b, year = int(year_last[1]), int(year_last[2]), int(year_last[3])
            if a > 12 >= b or (a == b and a <= 12):
                day = date(year, b, a)
            elif b > 12 >= a:
                day = date(year, a, b)
            else:
                return None
            return day, day
    except ValueError:
        return None
    return None


def _unreadable_dates_note(count: int, example: str, bounded: bool, lang: str) -> str | None:
    """Says how many rows had a date cell that could not be read, instead of dropping or
    sorting them without a word."""
    if not count:
        return None
    many = count > 1
    if lang == "fr":
        shown = f" (par exemple {example!r})" if example else " (cellule vide)"
        outcome = (
            f"{'elles sont exclues' if many else 'elle est exclue'} de la plage start/end."
            if bounded
            else f"{'elles sont classées' if many else 'elle est classée'} avant la ligne "
            "datée la plus ancienne, donc `limit` les écarte en premier."
        )
        return french_spacing(
            f"{fr_number(count)} {'lignes retenues' if many else 'ligne retenue'} par les filtres "
            f"{'ont' if many else 'a'} une date que MapleStats ne sait pas lire{shown} ; "
            f"{outcome}"
        )
    shown = f" (for example {example!r})" if example else " (a blank cell)"
    outcome = (
        f"{'they are' if many else 'it is'} left out of the start/end range."
        if bounded
        else f"{'they sort' if many else 'it sorts'} before the oldest dated row, so `limit` "
        "drops them first."
    )
    return (
        f"{count:,} {'rows' if many else 'row'} passing the filters "
        f"{'have' if many else 'has'} a date MapleStats cannot read{shown}; {outcome}"
    )


def _parse_bound(
    value: str | None, name: str, *, is_end: bool = False, lang: str = "en"
) -> date | None:
    """A start or end bound; a year or month `end` covers the whole period.

    end="2024" used to mean 2024-01-01, so a query for 2024 kept only
    January (live 2026-10-03: 3 Keystone rows instead of 36).
    """
    if not value:
        return None
    value = value.strip()
    parsed = _row_date(value)
    if parsed is None:
        _raise(
            InvalidInput,
            f"{name} must be YYYY, YYYY-MM or YYYY-MM-DD, got {value!r}.",
            f"{name} doit être au format AAAA, AAAA-MM ou AAAA-MM-JJ, reçu {value!r}.",
            lang,
        )
    if is_end and len(value) == 4:
        return date(parsed.year, 12, 31)
    if is_end and len(value) == 7:
        days = calendar.monthrange(parsed.year, parsed.month)[1]
        return date(parsed.year, parsed.month, days)
    return parsed


async def query_file(
    url: str,
    filters: dict[str, str] | None = None,
    *,
    columns: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> CerRows:
    """Filter a CER CSV by exact (case-insensitive) column values and dates.

    Returns the most recent `limit` matching rows when the file has a
    date or year column, otherwise the first `limit`.
    """
    if limit < 1 or limit > constants.ROWS_MAX:
        _raise(
            InvalidInput,
            f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.ROWS_MAX}, reçu {limit}.",
            lang,
        )
    start_date = _parse_bound(start, "start", lang=lang)
    end_date = _parse_bound(end, "end", is_end=True, lang=lang)
    rows, cached = await _download(url, lang)
    columns_lookup = csv_files.Columns(rows)
    if lang == "fr":
        unknown = [n for n in [*(filters or {}), *(columns or [])] if columns_lookup.get(n) is None]
        if unknown:
            raise_typed(
                InvalidInput,
                f"colonne inconnue {unknown[0]!r} ; les colonnes sont {columns_lookup.names}.",
                "fr",
            )
    filtered = csv_files.exact_filter(rows, columns_lookup, filters)
    date_column = columns_lookup.first_of(constants.DATE_COLUMNS)
    if not date_column and (start_date or end_date):
        _raise(
            InvalidInput,
            "start and end need a date or year column, and this file has none "
            f"(columns: {columns_lookup.names}). Drop them or use filters.",
            "start et end exigent une colonne de date ou d'année, et ce fichier n'en a "
            f"aucune (colonnes : {columns_lookup.names}). Retirez-les ou utilisez filters.",
            lang,
        )

    unreadable_dates = 0
    unreadable_example = ""
    matching: list[dict[str, str]]
    if date_column:
        bounded = bool(start_date or end_date)
        dated: list[tuple[dict[str, str], date]] = []
        for row in filtered:
            span = _row_span(row.get(date_column) or "")
            if span is None:
                # Cannot be placed against start/end, so it is left out when a bound is
                # given, and sorts as the oldest otherwise; either way it is counted.
                unreadable_dates += 1
                unreadable_example = unreadable_example or (row.get(date_column) or "").strip()
                if not bounded:
                    dated.append((row, date.min))
                continue
            first, last = span
            if (start_date and last < start_date) or (end_date and first > end_date):
                continue
            dated.append((row, first))
        dated.sort(key=lambda pair: pair[1])
        matching = [row for row, _ in dated]
        kept = matching[-limit:]
    else:
        bounded = False
        matching = filtered
        kept = matching[:limit]
    selected, selected_rows = csv_files.select(kept, columns_lookup, columns)
    return CerRows(
        url=url,
        columns=selected,
        rows=selected_rows,
        total_rows=len(rows),
        matching_rows=len(matching),
        returned_count=len(kept),
        date_column=date_column,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="cer.CerRows",
            coverage=(
                f"{len(kept)} of {len(matching)} matching rows"
                if lang != "fr"
                else f"{len(kept)} lignes correspondantes sur {len(matching)}"
            ),
            limits=" ".join(
                note
                for note in (
                    _ENGLISH_FILE_FR if lang == "fr" and "/open/" in url else None,
                    _unreadable_dates_note(unreadable_dates, unreadable_example, bounded, lang),
                )
                if note
            )
            or None,
            lang=lang,
        ),
    )
