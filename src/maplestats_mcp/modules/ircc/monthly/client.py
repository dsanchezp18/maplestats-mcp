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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

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
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
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


@dataclass
class ParsedTable:
    dimensions: list[_Dimension]
    value_column: str
    periods: list[Period]
    rows: list[_Row]
    delimiter: str = "	"


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


async def _packages() -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> list[dict[str, Any]]:
        await _LIMITER.acquire()
        try:
            result = await api_get(
                constants.CKAN_SEARCH_URL,
                params={"q": constants.CKAN_QUERY, "rows": constants.CKAN_ROWS},
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "ircc_monthly: open.canada.ca did not return the dataset list."
            ) from exc
        packages = [
            p
            for p in list_or_empty(result.get("result") or {}, "results")
            if "Monthly IRCC Updates" in str(p.get("title") or "")
        ]
        if not packages:
            raise UpstreamError("ircc_monthly: open.canada.ca lists no Monthly IRCC Updates.")
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
    packages, cached = await _packages()
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
            freshness="IRCC refreshes the files monthly",
            coverage=None if include_archived else "archived datasets left out",
        ),
    )


async def _find(table_id: str, lang: str) -> IrccTable:
    packages, _ = await _packages()
    wanted = table_id.strip().removesuffix(".csv").lower()
    for table in _tables(packages, lang):
        if table.table_id.lower() == wanted:
            return table
    raise NotFound(f"ircc_monthly: no table {table_id!r}; list them with ircc_monthly_list_tables.")


# ------------------------------------------------------------------ parsing


def _key(column: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", column.removeprefix("EN_").lower()).strip("_")


def _count(cell: str) -> int | None:
    cell = cell.strip()
    if cell == constants.SUPPRESSED or not cell:
        return None
    try:
        return int(cell.replace(",", ""))
    except ValueError as exc:
        raise UpstreamError(f"ircc_monthly: unexpected count {cell!r}.") from exc


def parse_table(body: bytes) -> ParsedTable:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("cp1252")
    first_line = text.split("\n", 1)[0]
    delimiter = "\t" if "\t" in first_line else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip() for h in next(reader, [])]
    if not any(h.startswith("EN_") for h in header):
        raise UpstreamError(
            "ircc_monthly: IRCC published this file without a header row, so its "
            "columns cannot be named; use the dataset's XLSX version instead."
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
        raise UpstreamError("ircc_monthly: the file has no TOTAL column.")

    rows: list[_Row] = []
    interned: dict[str, str] = {}
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
        month = constants.MONTHS.get(cell(time_index.get("month"))[:3].title())
        quarter_text = cell(time_index.get("quarter"))
        quarter = int(quarter_text[1]) if re.fullmatch(r"Q[1-4]", quarter_text) else None
        if quarter is None and month is not None:
            quarter = (month - 1) // 3 + 1
        rows.append(
            _Row(
                year=int(year_text) if year_text.isdigit() else None,
                quarter=quarter,
                month=month,
                labels=tuple(labels),
                value=_count(cells[value_index]),
            )
        )

    periods: list[Period] = []
    if "month" in time_index:
        periods = ["month", "quarter", "year"]
    elif "quarter" in time_index:
        periods = ["quarter", "year"]
    elif "year" in time_index:
        periods = ["year"]
    return ParsedTable(dims, header[value_index], periods, rows, delimiter)


async def _load(table: IrccTable) -> tuple[ParsedTable, bool]:
    async def fetch() -> ParsedTable:
        await _LIMITER.acquire()
        try:
            response = await get_raw(table.csv_url, timeout=180.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"ircc_monthly: {table.csv_url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"ircc_monthly: {table.csv_url} did not respond in time."
            ) from exc
        if len(response.content) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"ircc_monthly: {table.csv_url} is larger than expected.")
        if response.content.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            raise UpstreamError(f"ircc_monthly: {table.csv_url} returned a web page, not data.")
        return parse_table(response.content)

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


def _provenance(table: IrccTable, cached: bool, schema: str, lang: str) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=table.csv_url,
        cached=cached,
        schema_name=f"ircc_monthly.{schema}",
        freshness="monthly; IRCC adds the latest month and may revise earlier ones",
        limits=constants.ROUNDING_NOTE_FR if lang == "fr" else constants.ROUNDING_NOTE,
    )


async def describe_table(table_id: str, *, lang: str = "en") -> IrccTableDescription:
    """Dimensions, their values, and time coverage of one table."""
    table = await _find(table_id, lang)
    parsed, cached = await _load(table)
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
        suppressed_cells=sum(1 for r in parsed.rows if r.value is None),
        dimensions=dimensions,
        value_column=parsed.value_column,
        note=constants.ROUNDING_NOTE_FR if lang == "fr" else constants.ROUNDING_NOTE,
        provenance=_provenance(table, cached, "IrccTableDescription", lang),
    )


def _dimension(parsed: ParsedTable, name: str) -> int:
    wanted = name.strip().lower()
    for i, dim in enumerate(parsed.dimensions):
        if wanted in (dim.key, dim.column.lower(), (dim.column_fr or "").lower()):
            return i
    keys = [d.key for d in parsed.dimensions]
    raise InvalidInput(f"ircc_monthly: unknown dimension {name!r}; this table has {keys}.")


def _match_value(parsed: ParsedTable, i: int, value: str) -> str:
    dim = parsed.dimensions[i]
    wanted = " ".join(value.split()).lower()
    for english in {r.labels[i] for r in parsed.rows}:
        if wanted in (english.lower(), dim.fr.get(english, "").lower()):
            return english
    raise InvalidInput(
        f"ircc_monthly: {dim.key} has no value {value!r}; see ircc_monthly_describe_table."
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
        raise InvalidInput(
            f"ircc_monthly: limit must be between 1 and {constants.ROWS_MAX}, got {limit}."
        )
    if sort not in ("period", "value_desc"):
        raise InvalidInput("ircc_monthly: sort must be 'period' or 'value_desc'.")
    table = await _find(table_id, lang)
    parsed, cached = await _load(table)
    if period is not None and period not in parsed.periods:
        raise InvalidInput(
            f"ircc_monthly: {table.table_id} supports periods {parsed.periods}, not {period!r}."
        )
    grain = period or (parsed.periods[0] if parsed.periods else None)

    wanted: dict[int, str] = {}
    for name, value in (filters or {}).items():
        i = _dimension(parsed, name)
        wanted[i] = _match_value(parsed, i, value)
    kept = (
        [_dimension(parsed, g) for g in group_by]
        if group_by is not None
        else list(range(len(parsed.dimensions)))
    )

    sums: dict[tuple[str | None, tuple[str, ...]], list[int]] = defaultdict(lambda: [0, 0, 0])
    matched_cells = 0
    for row in parsed.rows:
        if any(row.labels[i] != v for i, v in wanted.items()):
            continue
        if year_from is not None and (row.year is None or row.year < year_from):
            continue
        if year_to is not None and (row.year is None or row.year > year_to):
            continue
        matched_cells += 1
        slot = sums[(_period_label(row, grain), tuple(row.labels[i] for i in kept))]
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
        note=constants.ROUNDING_NOTE_FR if lang == "fr" else constants.ROUNDING_NOTE,
        provenance=_provenance(table, cached, "IrccQueryResult", lang),
    )
