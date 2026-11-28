"""Client for IRCC's "Monthly IRCC Updates" open data tables.

Checked live 2026-09-25 against all 96 CSV resources of the 12 datasets:

1. Despite the .csv extension, 94 files are tab-separated; two archived
   files (ODP-Afghan-AgeGroup, ODP-Syrian_Refugees-Admissions-SkillLevel)
   are comma-separated. The delimiter is read from the header line.
2. Tables are long: time columns (EN_YEAR, EN_QUARTER, EN_MONTH as
   'Jan'...'Dec'; some tables have only EN_YEAR or no time at all), then
   dimension columns in English/French pairs (EN_PROVINCE_TERRITORY
   followed by FR_PROVINCE_TERRITOIRE), and a count column named TOTAL
   (once 'Total'). It is usually last but sits right after the time
   columns in the study-permit DLI files.
3. Counts are integers rounded to 5; '--' marks a suppressed count.
4. Two archived files repeat every column as 'Copy of <name>'; those
   columns are ignored. The study-permit DLI name columns have no French
   pair (and one header misspells INSTITUTION).
5. ODP-PR-FRE_SP_IMMCAT.csv has no header row at all, so its columns
   cannot be named; it is reported as unreadable rather than guessed.
6. Rows are not in time order, so results are sorted here.
7. In the archived refugee settlement-by-CMA files, the English column
   lumps several rural zones under one label ('Other - Ontario') while the
   French column still names each zone, so one English value has several
   French ones. Those rows are distinct counts and are summed; their French
   label falls back to the English one rather than naming a single zone.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.ircc.monthly import constants
from maplestats_mcp.modules.ircc.monthly.schemas import (
    IrccDimension,
    IrccQueryResult,
    IrccRow,
    IrccTable,
    IrccTableCatalogue,
    IrccTableDescription,
    Period,
)
from maplestats_mcp.shared import csv_files, file_download
from maplestats_mcp.shared.arg_checks import check_range
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import fr_number, french_spacing
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """Raise with the French error template for lang='fr'; English stays as it was."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _fr(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


_TIME = {"EN_YEAR": "year", "EN_QUARTER": "quarter", "EN_MONTH": "month"}
_BRACKET = re.compile(r"^\s*\[[^\]]*\]\s*")


@dataclass
class _Dimension:
    key: str
    column: str
    column_fr: str | None
    fr: dict[str, str] = field(default_factory=dict)  # English label -> French


@dataclass
class _Row:
    year: int | None
    quarter: int | None
    month: int | None
    labels: tuple[str, ...]
    value: int | None
    # The first non-blank time cell that could not be read ('' when none), kept so a
    # query can quote it in the note about rows whose period is unreadable.
    unread_time: str = ""


@dataclass
class ParsedTable:
    dimensions: list[_Dimension]
    value_column: str
    periods: list[Period]
    rows: list[_Row]
    delimiter: str = "	"
    # TOTAL cells that were neither a count nor IRCC's "--" (for instance
    # "<5" or "n/a"): read as unknown, like a suppressed cell, and reported.
    unreadable_cells: int = 0
    unreadable_example: str | None = None


# ---------------------------------------------------------------- catalogue


def _table_title(resource: dict[str, Any], lang: str) -> str:
    names = resource.get("name_translated") or {}
    name = names.get(lang) or names.get("en") or resource.get("name") or ""
    return _BRACKET.sub("", " ".join(str(name).split()))


def _dataset_title(package: dict[str, Any], lang: str) -> str:
    titles = package.get("title_translated") or {}
    return str(titles.get(lang) or titles.get("en") or package.get("title") or "")


def table_id_of(url: str) -> str:
    return url.rsplit("/", 1)[-1].removesuffix(".csv")


async def _packages(lang: str = "en") -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> list[dict[str, Any]]:
        await _LIMITER.acquire()
        try:
            result = await api_get(
                constants.CKAN_SEARCH_URL,
                params={"q": constants.CKAN_QUERY, "rows": constants.CKAN_ROWS},
            )
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                "ircc_monthly: open.canada.ca did not return the dataset list.",
                "ircc_monthly : ouvert.canada.ca n'a pas renvoyé la liste des jeux de données.",
                lang,
            )
        packages = [
            p
            for p in list_or_empty(result.get("result") or {}, "results")
            if "Monthly IRCC Updates" in str(p.get("title") or "")
        ]
        if not packages:
            _raise(
                UpstreamError,
                "ircc_monthly: open.canada.ca lists no Monthly IRCC Updates.",
                "ircc_monthly : ouvert.canada.ca ne répertorie aucune « Mise à jour mensuelle "
                "d'IRCC ».",
                lang,
            )
        return packages

    return await cached_fetch("ircc-monthly:catalogue", constants.CATALOGUE_TTL_SECONDS, fetch)


def _tables(packages: list[dict[str, Any]], lang: str) -> list[IrccTable]:
    tables: dict[str, IrccTable] = {}
    for package in packages:
        dataset = _dataset_title(package, lang)
        for resource in list_or_empty(package, "resources"):
            url = str(resource.get("url") or "")
            if resource.get("format") != "CSV" or not url.startswith(constants.FILE_PREFIX):
                continue
            table_id = table_id_of(url)
            tables.setdefault(
                table_id.lower(),
                IrccTable(
                    table_id=table_id,
                    title=_table_title(resource, lang),
                    dataset=dataset,
                    dataset_id=str(package.get("id") or ""),
                    archived="ARCHIVED" in str(package.get("title") or "").upper(),
                    csv_url=url,
                ),
            )
    return sorted(tables.values(), key=lambda t: (t.archived, t.dataset, t.table_id))


async def list_tables(
    query: str = "", *, include_archived: bool = False, lang: str = "en"
) -> IrccTableCatalogue:
    """Monthly-update tables whose title, dataset or id contain every word of `query`."""
    packages, cached = await _packages(lang)
    everything = _tables(packages, lang)
    words = query.lower().split()
    matched = [
        t
        for t in everything
        if (include_archived or not t.archived)
        and all(w in f"{t.table_id} {t.title} {t.dataset}".lower() for w in words)
    ]
    return IrccTableCatalogue(
        tables=matched,
        returned_count=len(matched),
        total_tables=len(everything),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.CKAN_SEARCH_URL,
            cached=cached,
            schema_name="ircc_monthly.IrccTableCatalogue",
            freshness=_fr(constants.CATALOGUE_FRESHNESS, constants.CATALOGUE_FRESHNESS_FR, lang),
            coverage=None
            if include_archived
            else _fr(constants.ARCHIVED_LEFT_OUT, constants.ARCHIVED_LEFT_OUT_FR, lang),
            lang=lang,
        ),
    )


async def _find(table_id: str, lang: str) -> IrccTable:
    packages, _ = await _packages(lang)
    wanted = table_id.strip().removesuffix(".csv").lower()
    for table in _tables(packages, lang):
        if table.table_id.lower() == wanted:
            return table
    _raise(
        NotFound,
        f"ircc_monthly: no table {table_id!r}; list them with ircc_monthly_list_tables.",
        f"ircc_monthly : aucun tableau {table_id!r} ; consultez la liste avec "
        "ircc_monthly_list_tables.",
        lang,
    )


# ------------------------------------------------------------------ parsing


def _key(column: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", column.removeprefix("EN_").lower()).strip("_")


def _fold(text: str) -> str:
    """Lower case, accents and a trailing full stop removed: 'Févr.' -> 'fevr'."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip().rstrip(".")


def _month_of(text: str) -> int | None:
    """1-12 from 'Jan', 'January', 'janv.', 'août' or '7'; None when it is none of them."""
    key = _fold(text)
    if key.isdigit():
        return int(key) if 1 <= int(key) <= 12 else None
    # The old rule (first three letters, English) stays as the fallback, so a spelling that
    # was read before is still read.
    return constants.MONTH_LOOKUP.get(key) or constants.MONTHS.get(key[:3].title())


_QUARTER = re.compile(r"(?<![a-z0-9])(?:[qt]|quarter|trimestre)\s*([1-4])(?!\d)")


def _quarter_of(text: str) -> int | None:
    """1-4 from 'Q1', 'Q1 2024', '2024-Q1', 'T2' (French) or 'Quarter 3'."""
    found = _QUARTER.search(_fold(text))
    return int(found.group(1)) if found else None


def _count(cell: str) -> tuple[int | None, bool]:
    """(count, readable). A suppressed or blank cell is (None, True); a cell that is
    not a number is (None, False), so one odd cell does not fail a 30 MB table."""
    cell = cell.strip()
    if cell == constants.SUPPRESSED or not cell:
        return None, True
    try:
        return int(cell.replace(",", "")), True
    except ValueError:
        return None, False


def _unreadable_note(parsed: ParsedTable, lang: str) -> str:
    if not parsed.unreadable_cells:
        return ""
    return _fr(
        f" {parsed.unreadable_cells:,} TOTAL cells were not counts (for example "
        f"{parsed.unreadable_example!r}); they are read as unknown, like suppressed cells.",
        f" {fr_number(parsed.unreadable_cells)} cellules TOTAL n'étaient pas des nombres (par exemple "
        f"{parsed.unreadable_example!r}) ; elles sont lues comme inconnues, comme les cellules "
        "supprimées.",
        lang,
    )


def parse_table(body: bytes, lang: str = "en") -> ParsedTable:
    text = csv_files.decode(body)
    first_line = text.split("\n", 1)[0]
    delimiter = "\t" if "\t" in first_line else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip() for h in next(reader, [])]
    if not any(h.startswith("EN_") for h in header):
        _raise(
            UpstreamError,
            "ircc_monthly: IRCC published this file without a header row, so its "
            "columns cannot be named; use the dataset's XLSX version instead.",
            "ircc_monthly : IRCC a publié ce fichier sans ligne d'en-tête, ses colonnes "
            "ne peuvent donc pas être nommées ; utilisez plutôt la version XLSX du jeu "
            "de données.",
            lang,
        )

    time_index: dict[str, int] = {}
    dims: list[_Dimension] = []
    dim_index: list[tuple[int, int | None]] = []
    value_index: int | None = None
    for i, column in enumerate(header):
        if column.startswith("Copy of"):
            continue
        if column in _TIME:
            time_index[_TIME[column]] = i
        elif column.upper() == "TOTAL" and value_index is None:
            value_index = i
        elif column.startswith("EN_"):
            nxt = header[i + 1] if i + 1 < len(header) else ""
            fr_i = i + 1 if nxt.startswith("FR_") else None
            dims.append(_Dimension(_key(column), column, nxt if fr_i else None))
            dim_index.append((i, fr_i))
    if value_index is None:
        _raise(
            UpstreamError,
            "ircc_monthly: the file has no TOTAL column.",
            "ircc_monthly : le fichier n'a pas de colonne TOTAL.",
            lang,
        )

    rows: list[_Row] = []
    interned: dict[str, str] = {}
    unreadable: list[str] = []
    for cells in reader:
        if len(cells) <= value_index or not any(c.strip() for c in cells):
            continue

        def cell(i: int | None, cells: list[str] = cells) -> str:
            return cells[i].strip() if i is not None and i < len(cells) else ""

        labels = []
        for dim, (en_i, fr_i) in zip(dims, dim_index, strict=True):
            label = cell(en_i)
            label = interned.setdefault(label, label)
            labels.append(label)
            french = cell(fr_i) if fr_i is not None else ""
            if french and dim.fr.setdefault(label, french) != french:
                # One English label, several French ones: fall back to English.
                dim.fr[label] = label
        year_text = cell(time_index.get("year"))
        month_text = cell(time_index.get("month"))
        month = _month_of(month_text)
        quarter_text = cell(time_index.get("quarter"))
        quarter = _quarter_of(quarter_text)
        if quarter is None and month is not None:
            quarter = (month - 1) // 3 + 1
        # A cell that is there but unreadable is told apart from a blank one, because
        # both give a row with no period and only the first is a surprise.
        unread = ""
        if year_text and not year_text.isdigit():
            unread = year_text
        elif month_text and month is None:
            unread = month_text
        elif quarter_text and quarter is None:
            unread = quarter_text
        value, readable = _count(cells[value_index])
        if not readable:
            unreadable.append(cells[value_index].strip())
        rows.append(
            _Row(
                year=int(year_text) if year_text.isdigit() else None,
                quarter=quarter,
                month=month,
                labels=tuple(labels),
                value=value,
                unread_time=unread,
            )
        )

    periods: list[Period] = []
    if "month" in time_index:
        periods = ["month", "quarter", "year"]
    elif "quarter" in time_index:
        periods = ["quarter", "year"]
    elif "year" in time_index:
        periods = ["year"]
    return ParsedTable(
        dims,
        header[value_index],
        periods,
        rows,
        delimiter,
        unreadable_cells=len(unreadable),
        unreadable_example=unreadable[0] if unreadable else None,
    )


async def _load(table: IrccTable, lang: str = "en") -> tuple[ParsedTable, bool]:
    url = table.csv_url

    async def fetch() -> ParsedTable:
        # Streamed under MAX_FILE_BYTES and kept to IRCC's file host on every
        # redirect hop, so a grown file is refused before it fills memory.
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host == constants.FILE_HOST,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="ircc_monthly",
            timeout=180.0,
        )
        body = downloaded.body
        if body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            _raise(
                UpstreamError,
                f"ircc_monthly: {url} returned a web page, not data.",
                f"ircc_monthly : {url} a renvoyé une page Web, pas des données.",
                lang,
            )
        return parse_table(body, lang)

    return await cached_fetch(f"ircc-monthly:{table.table_id}", constants.TABLE_TTL_SECONDS, fetch)


# ------------------------------------------------------------------ queries


def _period_label(row: _Row, period: Period | None) -> str | None:
    if period is None or row.year is None:
        return None
    if period == "year":
        return str(row.year)
    if period == "quarter":
        return f"{row.year}-Q{row.quarter}" if row.quarter else None
    return f"{row.year}-{row.month:02d}" if row.month else None


def _period_sort(label: str | None) -> str:
    return label or ""


def _label(dim: _Dimension, english: str, lang: str) -> str:
    return (dim.fr.get(english) or english) if lang == "fr" else english


def _provenance(table: IrccTable, cached: bool, schema: str, lang: str, extra: str = "") -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=table.csv_url,
        cached=cached,
        schema_name=f"ircc_monthly.{schema}",
        freshness=_fr(constants.FRESHNESS, constants.FRESHNESS_FR, lang),
        limits=_fr(constants.ROUNDING_NOTE, constants.ROUNDING_NOTE_FR, lang) + extra,
        lang=lang,
    )


# How many finer units make up one coarser period.
_UNITS_IN = {("month", "year"): 12, ("month", "quarter"): 3, ("quarter", "year"): 4}
_PARTIAL_LISTED = 5


def _unit_name(finest: str, unit: int, lang: str) -> str:
    if finest == "month":
        return (constants.MONTH_ABBR_FR if lang == "fr" else constants.MONTH_ABBR_EN)[unit - 1]
    return f"T{unit}" if lang == "fr" else f"Q{unit}"


def _units_text(finest: str, units: list[int], lang: str) -> str:
    """'Jan to Jul' for a run of units, a comma list for a run with a gap."""
    names = [_unit_name(finest, u, lang) for u in units]
    if len(units) > 1 and units == list(range(units[0], units[-1] + 1)):
        return f"{names[0]} {'à' if lang == 'fr' else 'to'} {names[-1]}"
    return ", ".join(names)


def _coverage(parsed: ParsedTable, grain: Period) -> dict[str, set[int]]:
    """The finer units (months, or quarters) the whole table has, per period of `grain`.

    Counted over every row, not the filtered ones: a province with no rows in a month
    does not make that month missing from the file.
    """
    finest = parsed.periods[0]
    seen: dict[str, set[int]] = defaultdict(set)
    for row in parsed.rows:
        unit = row.month if finest == "month" else row.quarter
        label = _period_label(row, grain)
        if label is not None and unit is not None:
            seen[label].add(unit)
    return seen


def _partial_note(parsed: ParsedTable, grain: Period | None, periods: list[str], lang: str) -> str:
    """Names the periods summed from fewer months (or quarters) than a full period has.

    The files grow a month at a time, so summing to year or quarter makes the latest period
    the total of the months published so far, which reads as a sharp drop next to full ones.
    The first period can be partial too, when a table starts mid-year. The sums are not
    changed; only the reader is told.
    """
    if grain is None or not parsed.periods or grain == parsed.periods[0]:
        return ""
    finest = parsed.periods[0]
    expected = _UNITS_IN.get((finest, grain))
    if expected is None or not periods:
        return ""
    seen = _coverage(parsed, grain)
    partial = [(p, sorted(seen[p])) for p in periods if p in seen and len(seen[p]) < expected]
    if not partial:
        return ""
    listed = partial[:_PARTIAL_LISTED]
    more = len(partial) - len(listed)
    units_en, units_fr = ("months", "mois") if finest == "month" else ("quarters", "trimestres")
    en = "; ".join(
        f"{p} has {len(u)} of {expected} {units_en} ({_units_text(finest, u, 'en')})"
        for p, u in listed
    )
    fr = " ; ".join(
        f"{p} compte {len(u)} {units_fr} sur {expected} ({_units_text(finest, u, 'fr')})"
        for p, u in listed
    )
    many = len(partial) > 1
    more_en = f"; {more} more" if more else ""
    more_fr = f" ; {more} de plus" if more else ""
    return _fr(
        f" Partial {'periods' if many else 'period'}: {en}{more_en}. A partial period sums "
        f"only the {units_en} present, so it is not comparable with a full one.",
        f" {'Périodes partielles' if many else 'Période partielle'} : {fr}{more_fr}. "
        f"Une période partielle ne somme que les {units_fr} présents ; elle n'est pas "
        "comparable à une période complète.",
        lang,
    )


def _unread_period_note(count: int, example: str, lang: str) -> str:
    """Says how many matched rows had no readable period and were pooled into one row."""
    if not count:
        return ""
    en_example = f" (for example {example!r})" if example else " (blank)"
    fr_example = f" (par exemple {example!r})" if example else " (vide)"
    verb_en = "row has" if count == 1 else "rows have"
    subject_fr = "ligne retenue n'a" if count == 1 else "lignes retenues n'ont"
    return _fr(
        f" {count:,} matched {verb_en} no readable period"
        f"{en_example}; they are summed into one row whose period is null.",
        f" {fr_number(count)} {subject_fr} pas de période lisible{fr_example} ; elles sont "
        "additionnées dans une seule ligne dont la période est nulle.",
        lang,
    )


def _cut_period_note(rows: list[IrccRow], shown: list[IrccRow], lang: str) -> str:
    """Says so when `limit` cuts through the earliest period of a chronological result."""
    earliest = shown[0].period if shown else None
    if earliest is None:
        return ""
    total = sum(1 for r in rows if r.period == earliest)
    in_view = sum(1 for r in shown if r.period == earliest)
    if in_view >= total:
        return ""
    return _fr(
        f" The earliest period shown, {earliest}, lists {in_view} of its {total} rows because "
        f"of `limit`; raise `limit` (maximum {constants.ROWS_MAX}) or add filters to see them all.",
        f" La période la plus ancienne affichée, {earliest}, ne montre que {in_view} de ses "
        f"{total} lignes à cause de `limit` ; augmentez `limit` (maximum {constants.ROWS_MAX}) "
        "ou ajoutez des filtres pour les voir toutes.",
        lang,
    )


async def describe_table(table_id: str, *, lang: str = "en") -> IrccTableDescription:
    """Dimensions, their values, and time coverage of one table."""
    table = await _find(table_id, lang)
    parsed, cached = await _load(table, lang)
    finest = parsed.periods[0] if parsed.periods else None
    labels = sorted(
        {p for r in parsed.rows if (p := _period_label(r, finest)) is not None},
        key=_period_sort,
    )
    dimensions = []
    for i, dim in enumerate(parsed.dimensions):
        values = sorted({r.labels[i] for r in parsed.rows})
        dimensions.append(
            IrccDimension(
                key=dim.key,
                column=dim.column,
                column_fr=dim.column_fr,
                value_count=len(values),
                values=[_label(dim, v, lang) for v in values[: constants.VALUES_SHOWN_MAX]],
            )
        )
    return IrccTableDescription(
        table_id=table.table_id,
        title=table.title,
        dataset=table.dataset,
        periods=parsed.periods,
        first_period=labels[0] if labels else None,
        last_period=labels[-1] if labels else None,
        row_count=len(parsed.rows),
        # Unreadable cells are also None, so they are kept out of the suppressed count.
        suppressed_cells=sum(1 for r in parsed.rows if r.value is None) - parsed.unreadable_cells,
        unreadable_cells=parsed.unreadable_cells,
        dimensions=dimensions,
        value_column=parsed.value_column,
        note=_fr(constants.ROUNDING_NOTE, constants.ROUNDING_NOTE_FR, lang)
        + _unreadable_note(parsed, lang),
        provenance=_provenance(table, cached, "IrccTableDescription", lang),
    )


def _dimension(parsed: ParsedTable, name: str, lang: str = "en") -> int:
    wanted = name.strip().lower()
    for i, dim in enumerate(parsed.dimensions):
        if wanted in (dim.key, dim.column.lower(), (dim.column_fr or "").lower()):
            return i
    keys = [d.key for d in parsed.dimensions]
    _raise(
        InvalidInput,
        f"ircc_monthly: unknown dimension {name!r}; this table has {keys}.",
        f"ircc_monthly : dimension inconnue {name!r} ; ce tableau a {keys}.",
        lang,
    )


def _match_value(parsed: ParsedTable, i: int, value: str, lang: str = "en") -> str:
    dim = parsed.dimensions[i]
    wanted = " ".join(value.split()).lower()
    for english in {r.labels[i] for r in parsed.rows}:
        if wanted in (english.lower(), dim.fr.get(english, "").lower()):
            return english
    _raise(
        InvalidInput,
        f"ircc_monthly: {dim.key} has no value {value!r}; see ircc_monthly_describe_table.",
        f"ircc_monthly : {dim.key} n'a pas de valeur {value!r} ; consultez "
        "ircc_monthly_describe_table.",
        lang,
    )


async def query_table(
    table_id: str,
    filters: dict[str, str] | None = None,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    period: Period | None = None,
    group_by: list[str] | None = None,
    sort: str = "period",
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> IrccQueryResult:
    """Filter a table, then sum it to `period` and the `group_by` dimensions."""
    if limit < 1 or limit > constants.ROWS_MAX:
        _raise(
            InvalidInput,
            f"ircc_monthly: limit must be between 1 and {constants.ROWS_MAX}, got {limit}.",
            f"ircc_monthly : limit doit être entre 1 et {constants.ROWS_MAX} (reçu : {limit}).",
            lang,
        )
    if sort not in ("period", "value_desc"):
        _raise(
            InvalidInput,
            "ircc_monthly: sort must be 'period' or 'value_desc'.",
            "ircc_monthly : sort doit être 'period' ou 'value_desc'.",
            lang,
        )
    # The shared range check speaks English only; French callers get the same check in French.
    if lang == "fr" and year_from is not None and year_to is not None and year_from > year_to:
        raise_typed(
            InvalidInput,
            f"year_from ({year_from}) est postérieur à year_to ({year_to}) ; inversez-les "
            "ou élargissez la plage.",
            lang,
        )
    check_range(year_from, year_to, "year_from", "year_to")
    table = await _find(table_id, lang)
    parsed, cached = await _load(table, lang)
    if period is not None and period not in parsed.periods:
        _raise(
            InvalidInput,
            f"ircc_monthly: {table.table_id} supports periods {parsed.periods}, not {period!r}.",
            f"ircc_monthly : {table.table_id} accepte les périodes {parsed.periods}, "
            f"pas {period!r}.",
            lang,
        )
    grain = period or (parsed.periods[0] if parsed.periods else None)

    wanted: dict[int, str] = {}
    for name, value in (filters or {}).items():
        i = _dimension(parsed, name, lang)
        wanted[i] = _match_value(parsed, i, value, lang)
    kept = (
        [_dimension(parsed, g, lang) for g in group_by]
        if group_by is not None
        else list(range(len(parsed.dimensions)))
    )

    sums: dict[tuple[str | None, tuple[str, ...]], list[int]] = defaultdict(lambda: [0, 0, 0])
    matched_cells = 0
    # Matched rows with no readable period all land in the one period=None row; counted
    # here so the note can say how many instead of leaving them pooled without a word.
    unread_periods = 0
    unread_example = ""
    for row in parsed.rows:
        if any(row.labels[i] != v for i, v in wanted.items()):
            continue
        if year_from is not None and (row.year is None or row.year < year_from):
            continue
        if year_to is not None and (row.year is None or row.year > year_to):
            continue
        matched_cells += 1
        label = _period_label(row, grain)
        if grain is not None and label is None:
            unread_periods += 1
            unread_example = unread_example or row.unread_time
        slot = sums[(label, tuple(row.labels[i] for i in kept))]
        slot[1] += 1
        if row.value is None:
            slot[2] += 1
        else:
            slot[0] += row.value

    rows = [
        IrccRow(
            period=label,
            dimensions={
                parsed.dimensions[i].key: _label(parsed.dimensions[i], v, lang)
                for i, v in zip(kept, labels, strict=True)
            },
            value=None if suppressed == cells else total,
            cells=cells,
            suppressed_cells=suppressed,
        )
        for (label, labels), (total, cells, suppressed) in sums.items()
    ]
    if sort == "value_desc":
        rows.sort(key=lambda r: r.value if r.value is not None else -1, reverse=True)
        shown = rows[:limit]
    else:
        # Chronological, keeping the most recent `limit` rows.
        rows.sort(key=lambda r: (_period_sort(r.period), sorted(r.dimensions.values())))
        shown = rows[-limit:]
    extra = (
        _partial_note(
            parsed, grain, sorted({r.period for r in shown if r.period is not None}), lang
        )
        + _unread_period_note(unread_periods, unread_example, lang)
        + (_cut_period_note(rows, shown, lang) if sort == "period" else "")
    )
    return IrccQueryResult(
        table_id=table.table_id,
        title=table.title,
        rows=shown,
        returned_count=len(shown),
        total_matched=len(rows),
        matched_cells=matched_cells,
        applied_filters={parsed.dimensions[i].column: v for i, v in wanted.items()},
        group_by=[parsed.dimensions[i].key for i in kept],
        period=grain,
        value_column=parsed.value_column,
        note=_fr(constants.ROUNDING_NOTE, constants.ROUNDING_NOTE_FR, lang)
        + _unreadable_note(parsed, lang)
        + extra,
        provenance=_provenance(table, cached, "IrccQueryResult", lang, extra),
    )
