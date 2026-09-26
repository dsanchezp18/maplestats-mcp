"""Client for the Canadian Grain Commission's statistics CSV files.

Checked live 2026-09-26 against every English Grain Statistics Weekly
file (2013-14 to 2026-27), the French ones, and both export files:

1. Weekly files are long format: crop year, grain week, week-ending date,
   worksheet, metric, period ('Current Week' or 'Crop Year' to date),
   grain, grade, region, Ktonnes. Twelve worksheets every year.
2. The header changes between years: `crop_year,grain_week,...` to
   2016-17, `grain_week,crop_year,...` (columns swapped) from 2017-18 to
   2023-24, `"Crop Year","Grain Week",...` from 2024-25. Columns are found
   by name, never by position.
3. French files are Windows-1252. Their headers are French ("Campagne
   Agricole", "Semaine", "Silo Agréé", "Activité"), and since 2025-26 the
   accented letters are dropped from the header ("Silo Agr", "Activit").
   Labels are French ("Blé", "Livraisons", "Semaine en cours").
4. Week-ending dates are day/month/year ("09/08/2026", "11/8/2013"); the
   French 2014-15 file writes "10AUG2014".
5. Values: "1,191.10" (thousands separator, 2013-14 to 2023-24), "(0.4)"
   for a negative adjustment, and "" or "." for a blank cell.
6. Rows without a region are national totals (Process worksheet).
7. Grades: "All grades combined" is used for grains not reported by grade
   (peas); it did not overlap per-grade rows in the 2026-27 file, and in
   the exports file only once in 50,397 rows.
8. A missing file answers HTTP 200 with the site's "Error 404" HTML page,
   so a response that starts with HTML is treated as not found.
9. The monthly exports file (English) is Windows-1252 too ("Türkiye").

Weekly tables are kept column-wise (label lists plus small integer codes)
because a full crop year is about 220,000 rows.
"""

from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from array import array
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.cgc import constants
from maplestats_mcp.modules.cgc.schemas import (
    CgcExportRow,
    CgcExportsDescription,
    CgcExportsResult,
    CgcWeek,
    CgcWeeklyDescription,
    CgcWeeklyResult,
    CgcWeeklyRow,
    CgcWorksheet,
    ExportDimension,
    ExportFrequency,
    WeeklyDimension,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.csv_files import decode
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
Filter = str | Sequence[str] | None

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

WEEKLY_DIMENSIONS: tuple[WeeklyDimension, ...] = (
    "worksheet",
    "metric",
    "period",
    "grain",
    "grade",
    "region",
)
EXPORT_DIMENSIONS: tuple[ExportDimension, ...] = (
    "grain",
    "grade",
    "elevator",
    "region",
    "global_region",
    "destination",
)

# Normalized header -> column. Prefixes cover the French headers that lost
# their accented letters in 2025-26 ("Silo Agr", "Activit").
_WEEKLY_HEADERS = {
    "crop_year": "crop_year",
    "campagne_agricole": "crop_year",
    "grain_week": "grain_week",
    "semaine": "grain_week",
    "week_ending_date": "week_ending_date",
    "le_semaine_se_terminant": "week_ending_date",
    "worksheet": "worksheet",
    "metric": "metric",
    "period": "period",
    "periode": "period",
    "grain": "grain",
    "grade": "grade",
    "region": "region",
    "ktonnes": "ktonnes",
}
_WEEKLY_PREFIXES = (("silo_agr", "worksheet"), ("activit", "metric"))
_EXPORT_HEADERS = {
    "year": "year",
    "annee": "year",
    "month": "month",
    "mois": "month",
    "grain": "grain",
    "grade": "grade",
    "ktonnes": "ktonnes",
    "elevator": "elevator",
    "silo_a_grains": "elevator",
    "region": "region",
    "secteur": "region",
    "global_region": "global_region",
    "region_du_monde": "global_region",
    "destination": "destination",
}
_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "janvier"),
            ("february", "fevrier"),
            ("march", "mars"),
            ("april", "avril"),
            ("may", "mai"),
            ("june", "juin"),
            ("july", "juillet"),
            ("august", "aout"),
            ("september", "septembre"),
            ("october", "octobre"),
            ("november", "novembre"),
            ("december", "decembre"),
        ],
        start=1,
    )
    for name in names
}
_DATE_FORMATS = ("%d/%m/%Y", "%d%b%Y", "%Y-%m-%d")
_CROP_YEAR = re.compile(r"^\s*(\d{2}|\d{4})\s*(?:[-/]\s*(\d{2}|\d{4}))?\s*$")
_BLANK = frozenset({"", ".", "-", "--"})


# ------------------------------------------------------------------ helpers


def fold(text: str) -> str:
    """Accent-free, case-free, single-spaced form used to compare labels."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def _header_key(header: str) -> str:
    return fold(header.strip().strip('"')).replace(" ", "_")


def parse_number(raw: str) -> float | None:
    text = raw.strip().replace(",", "")
    if text in _BLANK:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def parse_date(raw: str) -> date | None:
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def _today() -> date:
    return datetime.now(ZoneInfo(constants.TIMEZONE)).date()


def current_crop_year(today: date | None = None) -> int:
    """Start year of the crop year containing `today` (August to July)."""
    day = today or _today()
    return day.year if day.month >= constants.CROP_YEAR_START_MONTH else day.year - 1


def crop_year_label(start: int) -> str:
    return f"{start}-{(start + 1) % 100:02d}"


def available_crop_years() -> list[str]:
    return [crop_year_label(y) for y in range(constants.FIRST_CROP_YEAR, current_crop_year() + 1)]


def parse_crop_year(value: str | int | None) -> int | None:
    """Start year from '2026-27', '2026-2027', '26-27', '2026' or 2026."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    match = _CROP_YEAR.match(str(value))
    if match is None:
        raise InvalidInput(f"cgc: crop_year {value!r} should look like '2025-26'.")
    first = int(match.group(1))
    start = first + 2000 if first < 100 else first
    if match.group(2):
        second = int(match.group(2))
        if second % 100 != (start + 1) % 100:
            raise InvalidInput(f"cgc: {value!r} is not a crop year (e.g. '2025-26').")
    latest = current_crop_year()
    if not constants.FIRST_CROP_YEAR <= start <= latest:
        raise InvalidInput(
            f"cgc: crop year {crop_year_label(start)} is outside the CSV series "
            f"({crop_year_label(constants.FIRST_CROP_YEAR)} to {crop_year_label(latest)})."
        )
    return start


def weekly_url(start: int, lang: Lang) -> str:
    if lang == "fr":
        return f"{constants.WEEKLY_PAGE_FR}{start % 100:02d}-{(start + 1) % 100:02d}/gsw-shg-fr.csv"
    folder = "csv/" if start <= constants.LAST_CSV_SUBFOLDER_YEAR else ""
    return f"{constants.WEEKLY_PAGE_EN}{crop_year_label(start)}/{folder}gsw-shg-en.csv"


def _as_list(value: Filter) -> list[str]:
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return [str(v).strip() for v in items if str(v).strip()]


def _values_hint(values: Iterable[str]) -> str:
    shown = sorted({v for v in values if v})
    head = shown[: constants.VALUES_LISTED_MAX]
    more = f" (+{len(shown) - len(head)} more)" if len(shown) > len(head) else ""
    return ", ".join(repr(v) for v in head) + more


def keep_latest[T](rows: list[T], limit: int, period: Callable[[T], Any]) -> list[T]:
    """At most `limit` rows, dropping the oldest periods first.

    `rows` are in period order; within the oldest period kept, its first
    rows (table order, or largest first for exports) are the ones kept.
    """
    if len(rows) <= limit:
        return rows
    order = sorted(range(len(rows)), key=lambda i: (period(rows[i]), -i), reverse=True)
    return [rows[i] for i in sorted(order[:limit])]


def _as_of(day: date | None) -> datetime | None:
    if day is None:
        return None
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(constants.TIMEZONE)).astimezone(UTC)


# ----------------------------------------------------------------- download


async def _download(url: str, context: str) -> tuple[str, str | None]:
    """The file's text and Last-Modified header, retrying failed handshakes."""
    last_error: Exception | None = None
    for _ in range(constants.DOWNLOAD_PASSES):
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=constants.DOWNLOAD_TIMEOUT_SECONDS)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"{context}: no file at {url}.") from exc
            raise UpstreamError(
                f"{context}: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            # The shared client already retried 3 times; grainscanada.gc.ca
            # drops some TLS handshakes outright (see constants.py).
            last_error = exc
            continue
        if response.status_code != 200:
            raise UpstreamError(f"{context}: {url} returned HTTP {response.status_code}.")
        body = response.content
        if len(body) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"{context}: {url} is larger than this tool reads.")
        head = body[:200].lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")):
            # The site answers a missing file with HTTP 200 and its 404 page.
            raise NotFound(f"{context}: {url} returned the site's 'page not found' page.")
        return decode(body), response.headers.get("last-modified")
    raise UpstreamUnavailable(
        f"{context}: grainscanada.gc.ca did not complete a connection for {url} "
        f"({type(last_error).__name__ if last_error else 'no response'}); try again shortly."
    )


# ------------------------------------------------------------ weekly table


@dataclass
class _Labels:
    values: list[str] = field(default_factory=list)
    index: dict[str, int] = field(default_factory=dict)

    def code(self, label: str) -> int:
        found = self.index.get(label)
        if found is None:
            found = len(self.values)
            self.index[label] = found
            self.values.append(label)
        return found


@dataclass
class WeeklyTable:
    crop_year: int
    lang: Lang
    url: str
    last_modified: str | None
    labels: dict[str, list[str]]
    codes: dict[str, array]
    weeks: array
    values: array  # float, NaN for a blank cell
    week_ending: dict[int, date | None]
    by_worksheet: dict[int, array]  # worksheet code -> row numbers

    @property
    def row_count(self) -> int:
        return len(self.weeks)

    @property
    def latest_week(self) -> int | None:
        return max(self.week_ending) if self.week_ending else None


def _map_header(header: list[str], known: dict[str, str], prefixes=()) -> dict[str, int]:
    positions: dict[str, int] = {}
    for i, name in enumerate(header):
        key = _header_key(name)
        column = known.get(key)
        if column is None:
            column = next((col for prefix, col in prefixes if key.startswith(prefix)), None)
        if column is not None and column not in positions:
            positions[column] = i
    return positions


def parse_weekly(text: str, *, crop_year: int, lang: Lang, url: str, last_modified: str | None):
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        raise UpstreamError(f"cgc: {url} is empty.")
    positions = _map_header(header, _WEEKLY_HEADERS, _WEEKLY_PREFIXES)
    needed = ("grain_week", "week_ending_date", *WEEKLY_DIMENSIONS, "ktonnes")
    missing = [c for c in needed if c not in positions]
    if missing:
        raise UpstreamError(f"cgc: {url} has an unexpected header {header} (missing {missing}).")
    labels = {d: _Labels() for d in WEEKLY_DIMENSIONS}
    codes = {d: array("H") for d in WEEKLY_DIMENSIONS}
    weeks = array("H")
    values = array("d")
    week_ending: dict[int, date | None] = {}
    by_worksheet: dict[int, array] = {}
    width = max(positions.values()) + 1
    week_col, date_col, value_col = (
        positions["grain_week"],
        positions["week_ending_date"],
        positions["ktonnes"],
    )
    for row in reader:
        if len(row) < width:
            continue
        try:
            week = int(row[week_col].strip())
        except ValueError:
            continue
        if week not in week_ending or week_ending[week] is None:
            week_ending[week] = parse_date(row[date_col])
        row_number = len(weeks)
        weeks.append(week)
        for dim in WEEKLY_DIMENSIONS:
            codes[dim].append(labels[dim].code(row[positions[dim]].strip()))
        value = parse_number(row[value_col])
        values.append(math.nan if value is None else value)
        by_worksheet.setdefault(codes["worksheet"][-1], array("I")).append(row_number)
    if not weeks:
        raise UpstreamError(f"cgc: {url} has a header but no rows.")
    return WeeklyTable(
        crop_year=crop_year,
        lang=lang,
        url=url,
        last_modified=last_modified,
        labels={d: labels[d].values for d in WEEKLY_DIMENSIONS},
        codes=codes,
        weeks=weeks,
        values=values,
        week_ending=dict(sorted(week_ending.items())),
        by_worksheet=by_worksheet,
    )


async def _load_weekly(start: int, lang: Lang) -> tuple[WeeklyTable, bool]:
    url = weekly_url(start, lang)
    ttl = (
        constants.CURRENT_WEEKLY_TTL_SECONDS
        if start >= current_crop_year()
        else constants.PAST_WEEKLY_TTL_SECONDS
    )

    async def fetch() -> WeeklyTable:
        text, modified = await _download(url, "cgc weekly")
        return parse_weekly(text, crop_year=start, lang=lang, url=url, last_modified=modified)

    return await cached_fetch(f"cgc:weekly:{url}", ttl, fetch)


async def load_weekly(crop_year: str | int | None, lang: Lang) -> tuple[WeeklyTable, bool]:
    """The crop year's table; with no crop year, the latest one published.

    In early August the new crop year has no file until week 1 is out, so
    the default falls back to the previous crop year.
    """
    start = parse_crop_year(crop_year)
    if start is not None:
        return await _load_weekly(start, lang)
    latest = current_crop_year()
    try:
        return await _load_weekly(latest, lang)
    except NotFound:
        if latest - 1 < constants.FIRST_CROP_YEAR:
            raise
        return await _load_weekly(latest - 1, lang)


def _weekly_provenance(table: WeeklyTable, cached: bool, schema: str, **extra: Any) -> Provenance:
    latest = table.latest_week
    return make_provenance(
        source="cgc-grain-statistics-weekly",
        url=table.url,
        cached=cached,
        schema_name=schema,
        as_of=_as_of(table.week_ending.get(latest) if latest is not None else None),
        freshness=(
            "Weekly: the crop year's file is replaced each Thursday with the grain week "
            "that ended the previous Sunday"
            + (f" (file Last-Modified: {table.last_modified})" if table.last_modified else "")
            + ". Licence: "
            + constants.LICENCE
            + "."
        ),
        **extra,
    )


def _resolve(table: WeeklyTable, dim: str, wanted: list[str], among: set[int]) -> set[int]:
    """Codes of `dim` whose label matches one of `wanted` (accent/case-free)."""
    labels = table.labels[dim]
    folded: dict[str, list[int]] = {}
    for code in among:
        folded.setdefault(fold(labels[code]), []).append(code)
    chosen: set[int] = set()
    for value in wanted:
        hits = folded.get(fold(value))
        if not hits:
            raise InvalidInput(
                f"cgc: no {dim} {value!r} here; values are: "
                + _values_hint(labels[c] for c in among)
                + ". Call cgc_weekly_describe for the full lists."
            )
        chosen.update(hits)
    return chosen


def _codes_in(table: WeeklyTable, dim: str, rows: Iterable[int]) -> set[int]:
    column = table.codes[dim]
    return {column[r] for r in rows}


def describe_weekly_table(table: WeeklyTable, cached: bool) -> CgcWeeklyDescription:
    worksheets: list[CgcWorksheet] = []
    names = table.labels
    for code, rows in table.by_worksheet.items():

        def labels(dim: str, rows: array = rows) -> list[str]:
            seen: dict[str, None] = {}
            for c in sorted(_codes_in(table, dim, rows)):
                if names[dim][c]:
                    seen[names[dim][c]] = None
            return list(seen)

        grades = labels("grade")
        regions_all = [names["region"][c] for c in _codes_in(table, "region", rows)]
        worksheets.append(
            CgcWorksheet(
                worksheet=names["worksheet"][code],
                row_count=len(rows),
                metrics=labels("metric"),
                periods=labels("period"),
                grains=labels("grain"),
                regions=labels("region"),
                grades=grades[: constants.VALUES_LISTED_MAX],
                grades_total=len(grades),
                has_national_rows="" in regions_all,
            )
        )
    latest = table.latest_week
    return CgcWeeklyDescription(
        crop_year=crop_year_label(table.crop_year),
        lang=table.lang,
        available_crop_years=available_crop_years(),
        weeks=[CgcWeek(week=w, week_ending=d) for w, d in table.week_ending.items()],
        latest_week=latest,
        latest_week_ending=table.week_ending.get(latest) if latest is not None else None,
        row_count=table.row_count,
        worksheets=worksheets,
        provenance=_weekly_provenance(table, cached, "cgc.CgcWeeklyDescription"),
    )


async def describe_weekly(crop_year: str | int | None = None, lang: Lang = "en"):
    table, cached = await load_weekly(crop_year, lang)
    return describe_weekly_table(table, cached)


def query_weekly_table(
    table: WeeklyTable,
    cached: bool,
    *,
    worksheet: str,
    metric: Filter = None,
    period: Filter = None,
    grain: Filter = None,
    grade: Filter = None,
    region: Filter = None,
    week_from: int | None = None,
    week_to: int | None = None,
    latest_week_only: bool = False,
    group_by: list[WeeklyDimension] | None = None,
    limit: int = constants.ROWS_DEFAULT,
) -> CgcWeeklyResult:
    if not 1 <= limit <= constants.ROWS_MAX:
        raise InvalidInput(f"cgc: limit must be between 1 and {constants.ROWS_MAX}.")
    if not worksheet.strip():
        raise InvalidInput("cgc: worksheet is required; cgc_weekly_describe lists them.")
    sheet_codes = _resolve(table, "worksheet", [worksheet], set(table.by_worksheet))
    candidates = sorted(r for code in sheet_codes for r in table.by_worksheet[code])
    filters = {
        "metric": _as_list(metric),
        "period": _as_list(period),
        "grain": _as_list(grain),
        "grade": _as_list(grade),
        "region": _as_list(region),
    }
    wanted: dict[str, set[int]] = {}
    for dim, values in filters.items():
        if values:
            wanted[dim] = _resolve(table, dim, values, _codes_in(table, dim, candidates))
    low, high = week_from, week_to
    if latest_week_only:
        low = high = table.latest_week
    weeks, values = table.weeks, table.values
    matched = [
        r
        for r in candidates
        if (low is None or weeks[r] >= low)
        and (high is None or weeks[r] <= high)
        and all(table.codes[dim][r] in codes for dim, codes in wanted.items())
    ]
    # Files are not always in week order (2025-26 starts with 'Crop Year'
    # rows), and truncation keeps the latest weeks.
    matched.sort(key=lambda r: (weeks[r], r))
    names = table.labels
    rows: list[CgcWeeklyRow] = []
    if group_by is None:
        for r in matched:
            value = values[r]
            label = {d: names[d][table.codes[d][r]] for d in WEEKLY_DIMENSIONS}
            rows.append(
                CgcWeeklyRow(
                    week=weeks[r],
                    week_ending=table.week_ending.get(weeks[r]),
                    ktonnes=None if math.isnan(value) else value,
                    **{d: (label[d] or None) for d in WEEKLY_DIMENSIONS},
                )
            )
    else:
        unknown = [d for d in group_by if d not in WEEKLY_DIMENSIONS]
        if unknown:
            raise InvalidInput(f"cgc: group_by accepts {list(WEEKLY_DIMENSIONS)}; got {unknown}.")
        for dim in ("metric", "period"):
            if dim not in group_by and len(_codes_in(table, dim, matched)) > 1:
                raise InvalidInput(
                    f"cgc: the matched rows have several {dim}s; summing across them would add "
                    f"different quantities (e.g. a week's figure to a crop-year total). Filter "
                    f"`{dim}` to one value or add it to group_by."
                )
        keep = [d for d in WEEKLY_DIMENSIONS if d in group_by or d == "worksheet"]
        sums: dict[tuple[int, ...], list[float]] = {}
        for r in matched:
            key = (weeks[r], *(table.codes[d][r] for d in keep))
            bucket = sums.setdefault(key, [0.0, 0, 0])
            value = values[r]
            bucket[1] += 1
            if math.isnan(value):
                bucket[2] += 1
            else:
                bucket[0] += value
        for key, (total, cells, blank) in sums.items():
            week, *key_codes = key
            label = {d: names[d][c] for d, c in zip(keep, key_codes, strict=True)}
            rows.append(
                CgcWeeklyRow(
                    week=int(week),
                    week_ending=table.week_ending.get(int(week)),
                    ktonnes=None if blank == cells else round(total, 6),
                    cells=int(cells),
                    blank_cells=int(blank),
                    **{d: (label[d] or None) for d in keep},
                )
            )
        rows.sort(key=lambda row: row.week)
    total = len(rows)
    truncated = total > limit
    rows = keep_latest(rows, limit, lambda row: row.week)
    latest = table.latest_week
    return CgcWeeklyResult(
        crop_year=crop_year_label(table.crop_year),
        lang=table.lang,
        worksheet=names["worksheet"][min(sheet_codes)],
        filters={k: v for k, v in filters.items() if v},
        group_by=list(group_by) if group_by is not None else None,
        latest_week=latest,
        latest_week_ending=table.week_ending.get(latest) if latest is not None else None,
        rows=rows,
        returned_count=len(rows),
        total_matched=total,
        truncated=truncated,
        provenance=_weekly_provenance(
            table,
            cached,
            "cgc.CgcWeeklyResult",
            limits=(
                f"Kept the latest {len(rows)} of {total} rows (limit={limit}); narrow the "
                "filters or weeks for the rest."
                if truncated
                else None
            ),
        ),
    )


async def query_weekly(
    worksheet: str,
    *,
    crop_year: str | int | None = None,
    lang: Lang = "en",
    **kwargs: Any,
) -> CgcWeeklyResult:
    table, cached = await load_weekly(crop_year, lang)
    return query_weekly_table(table, cached, worksheet=worksheet, **kwargs)


# ----------------------------------------------------------------- exports


@dataclass(frozen=True)
class ExportRecord:
    year: int
    month: int
    grain: str
    grade: str
    elevator: str
    region: str
    global_region: str
    destination: str
    ktonnes: float


@dataclass
class ExportsTable:
    lang: Lang
    url: str
    last_modified: str | None
    records: list[ExportRecord]

    @property
    def latest(self) -> tuple[int, int] | None:
        return max(((r.year, r.month) for r in self.records), default=None)

    @property
    def first(self) -> tuple[int, int] | None:
        return min(((r.year, r.month) for r in self.records), default=None)


def _month_label(year_month: tuple[int, int] | None) -> str | None:
    return f"{year_month[0]}-{year_month[1]:02d}" if year_month else None


def parse_exports(text: str, *, lang: Lang, url: str, last_modified: str | None) -> ExportsTable:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        raise UpstreamError(f"cgc: {url} is empty.")
    positions = _map_header(header, _EXPORT_HEADERS)
    needed = ("year", "month", "ktonnes", *EXPORT_DIMENSIONS)
    missing = [c for c in needed if c not in positions]
    if missing:
        raise UpstreamError(f"cgc: {url} has an unexpected header {header} (missing {missing}).")
    width = max(positions.values()) + 1
    interned: dict[str, str] = {}
    records: list[ExportRecord] = []
    for row in reader:
        if len(row) < width:
            continue
        month = _MONTHS.get(fold(row[positions["month"]]))
        value = parse_number(row[positions["ktonnes"]])
        try:
            year = int(row[positions["year"]].strip())
        except ValueError:
            continue
        if month is None or value is None:
            continue
        labels = {
            d: interned.setdefault(row[positions[d]].strip(), row[positions[d]].strip())
            for d in EXPORT_DIMENSIONS
        }
        records.append(ExportRecord(year=year, month=month, ktonnes=value, **labels))
    if not records:
        raise UpstreamError(f"cgc: {url} has no readable rows.")
    return ExportsTable(lang=lang, url=url, last_modified=last_modified, records=records)


async def load_exports(lang: Lang) -> tuple[ExportsTable, bool]:
    url = constants.EXPORTS_URL_FR if lang == "fr" else constants.EXPORTS_URL_EN

    async def fetch() -> ExportsTable:
        text, modified = await _download(url, "cgc exports")
        return parse_exports(text, lang=lang, url=url, last_modified=modified)

    return await cached_fetch(f"cgc:exports:{url}", constants.EXPORTS_TTL_SECONDS, fetch)


def _exports_provenance(table: ExportsTable, cached: bool, schema: str, **extra: Any):
    latest = table.latest
    return make_provenance(
        source="cgc-exports-licensed-facilities",
        url=table.url,
        cached=cached,
        schema_name=schema,
        as_of=_as_of(date(latest[0], latest[1], 1)) if latest else None,
        freshness=(
            "Monthly, a few weeks after the month ends"
            + (f" (file Last-Modified: {table.last_modified})" if table.last_modified else "")
            + ". Exports from licensed facilities, by destination. Licence: "
            + constants.LICENCE
            + "."
        ),
        **extra,
    )


def describe_exports_table(table: ExportsTable, cached: bool) -> CgcExportsDescription:
    def values(dim: str) -> list[str]:
        return sorted({getattr(r, dim) for r in table.records if getattr(r, dim)})

    grades = values("grade")
    return CgcExportsDescription(
        lang=table.lang,
        first_month=_month_label(table.first),
        latest_month=_month_label(table.latest),
        row_count=len(table.records),
        grains=values("grain"),
        elevators=values("elevator"),
        regions=values("region"),
        global_regions=values("global_region"),
        destinations=values("destination"),
        grades=grades[: constants.VALUES_LISTED_MAX],
        grades_total=len(grades),
        provenance=_exports_provenance(table, cached, "cgc.CgcExportsDescription"),
    )


async def describe_exports(lang: Lang = "en") -> CgcExportsDescription:
    table, cached = await load_exports(lang)
    return describe_exports_table(table, cached)


def _period(year: int, month: int, frequency: ExportFrequency) -> str:
    if frequency == "month":
        return f"{year}-{month:02d}"
    if frequency == "year":
        return str(year)
    start = year if month >= constants.CROP_YEAR_START_MONTH else year - 1
    return crop_year_label(start)


def _export_period(record: ExportRecord, frequency: ExportFrequency) -> str:
    return _period(record.year, record.month, frequency)


def query_exports_table(
    table: ExportsTable,
    cached: bool,
    *,
    grain: Filter = None,
    grade: Filter = None,
    elevator: Filter = None,
    region: Filter = None,
    global_region: Filter = None,
    destination: Filter = None,
    year_from: int | None = None,
    year_to: int | None = None,
    frequency: ExportFrequency = "month",
    group_by: list[ExportDimension] | None = None,
    limit: int = constants.ROWS_DEFAULT,
) -> CgcExportsResult:
    if not 1 <= limit <= constants.ROWS_MAX:
        raise InvalidInput(f"cgc: limit must be between 1 and {constants.ROWS_MAX}.")
    if frequency not in ("month", "year", "crop_year"):
        raise InvalidInput("cgc: frequency must be 'month', 'year' or 'crop_year'.")
    if group_by is not None:
        unknown = [d for d in group_by if d not in EXPORT_DIMENSIONS]
        if unknown:
            raise InvalidInput(f"cgc: group_by accepts {list(EXPORT_DIMENSIONS)}; got {unknown}.")
    filters = {
        "grain": _as_list(grain),
        "grade": _as_list(grade),
        "elevator": _as_list(elevator),
        "region": _as_list(region),
        "global_region": _as_list(global_region),
        "destination": _as_list(destination),
    }
    wanted: dict[str, set[str]] = {}
    for dim, requested in filters.items():
        if not requested:
            continue
        present: dict[str, set[str]] = {}
        for record in table.records:
            label = getattr(record, dim)
            present.setdefault(fold(label), set()).add(label)
        chosen: set[str] = set()
        for value in requested:
            hits = present.get(fold(value))
            if not hits:
                raise InvalidInput(
                    f"cgc: no {dim} {value!r} in the exports file; values are: "
                    + _values_hint(label for labels in present.values() for label in labels)
                    + ". Call cgc_exports_describe for the full lists."
                )
            chosen |= hits
        wanted[dim] = chosen
    matched = [
        r
        for r in table.records
        if (year_from is None or r.year >= year_from)
        and (year_to is None or r.year <= year_to)
        and all(getattr(r, dim) in labels for dim, labels in wanted.items())
    ]
    matched.sort(key=lambda r: (r.year, r.month))
    rows: list[CgcExportRow] = []
    if group_by is None and frequency == "month":
        rows = [
            CgcExportRow(
                period=_export_period(r, "month"),
                year=r.year,
                month=r.month,
                ktonnes=r.ktonnes,
                **{d: (getattr(r, d) or None) for d in EXPORT_DIMENSIONS},
            )
            for r in matched
        ]
    else:
        keep = list(group_by or [])
        # Months the file covers in each period within the year bounds,
        # whatever the other filters: a month with no shipment to a
        # destination is still a month of data, but year_from=2023 leaves
        # only January to July 2023 in crop year 2022-23.
        covered: dict[str, int] = {}
        in_bounds = {
            (r.year, r.month)
            for r in table.records
            if (year_from is None or r.year >= year_from) and (year_to is None or r.year <= year_to)
        }
        for year_month in in_bounds:
            label = _period(*year_month, frequency)
            covered[label] = covered.get(label, 0) + 1
        sums: dict[tuple[str, ...], list[Any]] = {}
        for r in matched:
            key = (_export_period(r, frequency), *(getattr(r, d) for d in keep))
            bucket = sums.setdefault(key, [0.0, 0, r.year, r.month])
            bucket[0] += r.ktonnes
            bucket[1] += 1
        for key, (total, cells, year, month) in sums.items():
            period, *labels = key
            rows.append(
                CgcExportRow(
                    period=period,
                    year=year if frequency != "crop_year" else None,
                    month=month if frequency == "month" else None,
                    ktonnes=round(total, 6),
                    cells=cells,
                    months=covered.get(period) if frequency != "month" else None,
                    **{d: (label or None) for d, label in zip(keep, labels, strict=True)},
                )
            )
    # Largest first within a period: the usual question is "which markets".
    rows.sort(key=lambda row: (row.period, -row.ktonnes))
    total = len(rows)
    truncated = total > limit
    rows = keep_latest(rows, limit, lambda row: row.period)
    return CgcExportsResult(
        lang=table.lang,
        frequency=frequency,
        filters={k: v for k, v in filters.items() if v},
        group_by=list(group_by) if group_by is not None else None,
        latest_month=_month_label(table.latest),
        rows=rows,
        returned_count=len(rows),
        total_matched=total,
        truncated=truncated,
        total_ktonnes=round(sum(r.ktonnes for r in matched), 6),
        provenance=_exports_provenance(
            table,
            cached,
            "cgc.CgcExportsResult",
            limits=(
                f"Kept the latest {len(rows)} of {total} rows (limit={limit}); narrow the "
                "filters, years or add group_by for the rest."
                if truncated
                else None
            ),
        ),
    )


async def query_exports(lang: Lang = "en", **kwargs: Any) -> CgcExportsResult:
    table, cached = await load_exports(lang)
    return query_exports_table(table, cached, **kwargs)
