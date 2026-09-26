"""Client for PHAC Health Infobase data files.

Datasets come from the curated catalogue in catalogue.py, so a caller
names a dataset id, never a URL. Each file is downloaded once per cache
window, decoded (see constants.py for the encodings met live), parsed
into rows of strings and filtered here. Values are returned exactly as
published, including suppression markers such as "Suppr." or "X", which
are reported alongside the rows rather than silently dropped.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from maplestats_mcp.modules.phac_infobase import constants
from maplestats_mcp.modules.phac_infobase.catalogue import BY_ID, DATASETS, TOPICS, Dataset
from maplestats_mcp.modules.phac_infobase.schemas import (
    ColumnSummary,
    DatasetDescription,
    DatasetList,
    DatasetSummary,
    Marker,
    QueryResult,
    TopicCount,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SOURCE = "phac-infobase"
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_QUARTER = re.compile(r"^(\d{4})\s*-?\s*Q([1-4])\b", re.IGNORECASE)
_DAY_FIRST = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_YEAR = re.compile(r"^(\d{4})(?!\d)")
_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?%?$")
_DECIMAL_COMMA = re.compile(r"^-?\d+,\d+$")
_BOUND = re.compile(r"\d{4}(?:-(?:0[1-9]|1[0-2])(?:-\d{2})?)?|\d{4}\s*Q[1-4]", re.IGNORECASE)


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, str]]
    encoding: str
    last_modified: str | None


# Catalogue helpers ----------------------------------------------------------


def _fold(text: str) -> str:
    """Lower-case, accent-free, single-spaced text for matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _absolute(path: str) -> str:
    return path if path.startswith("https://") else constants.BASE_URL + path


def _dataset(dataset_id: str) -> Dataset:
    found = BY_ID.get(dataset_id.strip().lower())
    if found is None:
        raise NotFound(
            f"No Health Infobase dataset {dataset_id!r}. Use phac_infobase_list_datasets; "
            f"ids include {', '.join(d.id for d in DATASETS[:6])}, ..."
        )
    return found


def _source(dataset: Dataset, lang: str) -> tuple[str, str | None, str | None, str]:
    """(url, zip member, encoding override, file language) for `lang`."""
    if lang == "fr" and dataset.url_fr:
        return _absolute(dataset.url_fr), dataset.member_fr, dataset.encoding_fr, "fr"
    return _absolute(dataset.url_en), dataset.member_en, dataset.encoding_en, "en"


def _text(dataset: Dataset, lang: str) -> tuple[str, str, str | None]:
    if lang == "fr":
        return dataset.title_fr, dataset.description_fr, dataset.notes_fr
    return dataset.title_en, dataset.description_en, dataset.notes_en


def _dashboard(dataset: Dataset, lang: str) -> str:
    if lang == "fr" and dataset.dashboard_fr:
        return dataset.dashboard_fr
    return _absolute(dataset.dashboard_en)


def _frequency(dataset: Dataset, lang: str) -> str:
    english, french = constants.FREQUENCIES[dataset.frequency]
    return french if lang == "fr" else english


# Download and parse -----------------------------------------------------------


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in constants.ALLOWED_HOSTS:
        raise UpstreamError(f"phac_infobase: refusing to fetch {url} (unexpected host).")


async def _get(url: str) -> httpx.Response:
    """GET with manual redirects: a missing file answers 302 to /404.html."""
    current = url
    for _ in range(constants.MAX_REDIRECTS + 1):
        _check_host(current)
        await _LIMITER.acquire()
        try:
            return await get_raw(current, timeout=120.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            location = exc.response.headers.get("location")
            if status in _REDIRECTS and location:
                target = str(exc.response.url.join(location))
                if urlparse(target).path == constants.NOT_FOUND_PAGE:
                    raise NotFound(f"phac_infobase: no file at {url} (moved or removed).") from exc
                current = target
                continue
            if status == 404:
                raise NotFound(f"phac_infobase: no file at {url}.") from exc
            raise UpstreamError(f"phac_infobase: {url} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"phac_infobase: {url} did not respond in time.") from exc
    raise UpstreamError(f"phac_infobase: {url} redirected too many times.")


def _decode(body: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding:
        return body.decode(encoding), encoding
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252"), "cp1252"
    return text, "utf-8-sig" if body.startswith(b"\xef\xbb\xbf") else "utf-8"


def _unique(names: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for name in names:
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def parse_csv(
    body: bytes, encoding: str | None, url: str
) -> tuple[list[str], list[dict[str, str]], str]:
    text, used = _decode(body, encoding)
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        raise NotFound(f"phac_infobase: {url} returned a web page, not a CSV file.")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        raise UpstreamError(f"phac_infobase: {url} is empty.")
    names = [h.strip() for h in header]
    # Columns with an empty header are row numbers written by R (the
    # tuberculosis files) or trailing blank columns (the 2018 CCDI and the
    # French positive mental health file, which has hundreds): drop them.
    keep = [i for i, name in enumerate(names) if name]
    unique = _unique([names[i] for i in keep])
    rows = []
    for record in reader:
        if not any(cell.strip() for cell in record):
            continue
        rows.append(
            {unique[j]: (record[i].strip() if i < len(record) else "") for j, i in enumerate(keep)}
        )
    return unique, rows, used


def zip_member(body: bytes, pattern: str | None, url: str) -> bytes:
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise UpstreamError(f"phac_infobase: {url} is not a readable ZIP file.") from exc
    members = [i for i in archive.infolist() if i.filename.lower().endswith(".csv")]
    if pattern:
        # Accent-insensitive: the French opioid member is DonnéesMéfaitsSubstances.csv.
        members = [i for i in members if _fold(pattern) in _fold(i.filename)]
    if not members:
        raise UpstreamError(f"phac_infobase: {url} has no CSV member matching {pattern!r}.")
    if members[0].file_size > constants.MAX_FILE_BYTES:
        raise UpstreamError(f"phac_infobase: {url} unpacks to more than this tool reads.")
    return archive.read(members[0])


def parse_api(body: bytes, url: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise UpstreamError(f"phac_infobase: {url} did not return JSON.") from exc
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise UpstreamError(f"phac_infobase: {url} did not return a list of records.")
    columns: list[str] = []
    for record in data:
        columns.extend(k for k in record if k not in columns)
    # The API sends JSON null for empty cells (confirmed on vri_rates).
    rows = [{c: "" if r.get(c) is None else str(r.get(c)).strip() for c in columns} for r in data]
    return columns, rows


async def _api_updated_at(url: str) -> str | None:
    """The database's updatedAt from /api/<database> (e.g. 2026-09-18T17:45:33Z)."""
    parts = urlparse(url).path.split("/")
    if len(parts) < 3:
        return None
    try:
        response = await _get(f"{constants.API_URL}/{parts[2]}")
        value = json.loads(response.content).get("updatedAt")
    except (NotFound, UpstreamError, UpstreamUnavailable, ValueError, AttributeError):
        return None
    return str(value) if value else None


async def load(dataset: Dataset, lang: str) -> tuple[Table, bool, str, str]:
    """(table, was_cached, url, file language) for one catalogue entry."""
    url, member, encoding, file_lang = _source(dataset, lang)

    async def fetch() -> Table:
        response = await _get(url)
        body = response.content
        if len(body) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"phac_infobase: {url} is larger than this tool reads.")
        if dataset.kind == "api":
            columns, rows = await asyncio.to_thread(parse_api, body, url)
            return Table(columns, rows, "json", await _api_updated_at(url))

        def parse() -> tuple[list[str], list[dict[str, str]], str]:
            raw = zip_member(body, member, url) if dataset.kind == "zip" else body
            return parse_csv(raw, encoding, url)

        # The 20 MB survey files take about a second to parse; keep it off
        # the event loop so other requests are not stalled.
        columns, rows, used = await asyncio.to_thread(parse)
        return Table(columns, rows, used, response.headers.get("last-modified"))

    table, cached = await cached_fetch(
        f"phac_infobase:{url}#{member or ''}", constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return table, cached, url, file_lang


# Values: periods, geography, markers ----------------------------------------


def _valid(year: int) -> bool:
    return 1800 <= year <= 2100


def parse_period(value: str) -> date | None:
    """Start date of a period cell: 2025-08-30, 2024-10, 2026 Q1, 2015-2018,
    2026 (Jan to Mar), 30-08-2025. None when there is no year."""
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    if match := _QUARTER.match(text):
        year = int(match.group(1))
        return date(year, 3 * int(match.group(2)) - 2, 1) if _valid(year) else None
    # "2024-25" is a fiscal or school year, not May 2024's successor month 25:
    # only months 1-12 count, anything else falls through to the year.
    if (match := _YEAR_MONTH.match(text)) and 1 <= int(match.group(2)) <= 12:
        year = int(match.group(1))
        return date(year, int(match.group(2)), 1) if _valid(year) else None
    if match := _DAY_FIRST.match(text):
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    if match := _YEAR.match(text):
        year = int(match.group(1))
        return date(year, 1, 1) if _valid(year) else None
    return None


def _bound(value: str | None, name: str, *, end: bool) -> date | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    start = parse_period(text) if _BOUND.fullmatch(text) else None
    if start is not None and len(text) == 10:
        try:
            date.fromisoformat(text)
        except ValueError:
            start = None
    if start is None:
        raise InvalidInput(f"{name} must be YYYY, YYYY-MM, YYYY-MM-DD or YYYY Qn, got {value!r}.")
    if not end:
        return start
    if re.fullmatch(r"\d{4}", text):
        return date(start.year, 12, 31)
    if match := _QUARTER.match(text):
        last_month = 3 * int(match.group(2))
        return _month_end(start.year, last_month)
    if _YEAR_MONTH.match(text):
        return _month_end(start.year, start.month)
    return start


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _province(query: str) -> str | None:
    """PRUID for a province or territory named, abbreviated or coded."""
    wanted = _fold(query).replace(".", "")
    for pruid, (english, french, abbreviations) in constants.PROVINCES.items():
        names = {pruid, _fold(english), _fold(french)}
        names |= {_fold(a).replace(".", "") for a in abbreviations}
        if wanted in names:
            return pruid
    return None


def geo_matcher(query: str) -> Callable[[str], bool]:
    """Match a geography cell against a province name (English or French),
    abbreviation or PRUID; any other text matches as a substring."""
    pruid = _province(query)
    if pruid is None:
        needle = _fold(query)
        return lambda cell: needle in _fold(cell)
    english, french, abbreviations = constants.PROVINCES[pruid]
    accepted = {pruid, _fold(english), _fold(french)}
    accepted |= {_fold(a).replace(".", "") for a in abbreviations}
    return lambda cell: _fold(cell).replace(".", "") in accepted


def _resolve(columns: list[str], name: str) -> str:
    by_fold = {_fold(c): c for c in columns}
    found = by_fold.get(_fold(name))
    if found is None:
        raise InvalidInput(f"Unknown column {name!r}; columns are {columns}.")
    return found


def _first_present(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    by_fold = {_fold(c): c for c in columns}
    return next((by_fold[_fold(c)] for c in candidates if _fold(c) in by_fold), None)


def _markers(rows: list[dict[str, str]], lang: str) -> list[Marker]:
    counts: Counter[str] = Counter(
        v for row in rows for v in row.values() if v in constants.MARKERS
    )
    index = 1 if lang == "fr" else 0
    return [
        Marker(value=value, meaning=constants.MARKERS[value][index], count=count)
        for value, count in counts.most_common()
    ]


def _decimal_comma(rows: list[dict[str, str]], file_lang: str) -> bool:
    if file_lang != "fr":
        return False
    return any(_DECIMAL_COMMA.match(v) for row in rows for v in row.values())


def _as_of(last_modified: str | None) -> datetime | None:
    if not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(last_modified)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Tools ------------------------------------------------------------------------


def _summary(dataset: Dataset, lang: str) -> DatasetSummary:
    title, description, _ = _text(dataset, lang)
    url, _, _, _ = _source(dataset, lang)
    labels = TOPICS[dataset.topic]
    return DatasetSummary(
        id=dataset.id,
        title=title,
        topic=dataset.topic,
        topic_label=labels[1] if lang == "fr" else labels[0],
        description=description,
        frequency=_frequency(dataset, lang),
        archived=dataset.frequency == "archived",
        languages=["en", "fr"] if dataset.url_fr else ["en"],
        file_url=url,
        dashboard_url=_dashboard(dataset, lang),
    )


def list_datasets(
    topic: str | None = None, query: str | None = None, lang: str = "en"
) -> DatasetList:
    wanted_topic = (topic or "").strip().lower()
    if wanted_topic and wanted_topic not in TOPICS:
        raise InvalidInput(f"Unknown topic {topic!r}; topics are {sorted(TOPICS)}.")
    words = _fold(query or "").split()
    matches = []
    for dataset in DATASETS:
        if wanted_topic and dataset.topic != wanted_topic:
            continue
        haystack = _fold(
            " ".join(
                [
                    dataset.id.replace("_", " "),
                    dataset.title_en,
                    dataset.title_fr,
                    dataset.description_en,
                    dataset.description_fr,
                    *TOPICS[dataset.topic],
                ]
            )
        )
        if all(word in haystack for word in words):
            matches.append(_summary(dataset, lang))
    counts = Counter(d.topic for d in DATASETS)
    index = 1 if lang == "fr" else 0
    return DatasetList(
        datasets=matches,
        topics=[
            TopicCount(key=key, label=labels[index], datasets=counts[key])
            for key, labels in TOPICS.items()
        ],
        total_count=len(matches),
        provenance=make_provenance(
            source=_SOURCE,
            url=constants.BASE_URL,
            cached=False,
            schema_name="phac_infobase.DatasetList",
            coverage=(
                f"{len(matches)} of {len(DATASETS)} curated Health Infobase files; dashboards "
                "without downloadable files (CCDSS, current CCDI) are not listed"
            ),
        ),
    )


def _column_summary(name: str, rows: list[dict[str, str]]) -> ColumnSummary:
    values = Counter(row.get(name, "") for row in rows)
    empty = values.pop("", 0)
    real = [v for v in values if v not in constants.MARKERS]
    return ColumnSummary(
        name=name,
        distinct_values=len(values),
        empty_cells=empty,
        sample_values=[v for v, _ in values.most_common(constants.SAMPLE_VALUES)],
        numeric=bool(real) and all(_NUMBER.match(v) for v in real),
    )


async def describe_dataset(dataset_id: str, lang: str = "en") -> DatasetDescription:
    dataset = _dataset(dataset_id)
    table, cached, url, file_lang = await load(dataset, lang)
    title, description, notes = _text(dataset, lang)
    date_column = _first_present(table.columns, dataset.date_columns)
    geo_column = _first_present(table.columns, dataset.geo_columns)
    dates = (
        sorted(d for d in (parse_period(r.get(date_column, "")) for r in table.rows) if d)
        if date_column
        else []
    )
    geo_values = (
        list(dict.fromkeys(r.get(geo_column, "") for r in table.rows if r.get(geo_column)))
        if geo_column
        else []
    )
    return DatasetDescription(
        id=dataset.id,
        title=title,
        topic=dataset.topic,
        description=description,
        notes=notes,
        frequency=_frequency(dataset, lang),
        file_url=url,
        file_language=file_lang,
        dashboard_url=_dashboard(dataset, lang),
        last_modified=table.last_modified,
        encoding=table.encoding,
        row_count=len(table.rows),
        columns=[_column_summary(c, table.rows) for c in table.columns],
        date_column=date_column,
        date_start=dates[0].isoformat() if dates else None,
        date_end=dates[-1].isoformat() if dates else None,
        geo_column=geo_column,
        geo_values=geo_values[: constants.GEO_VALUES_MAX],
        markers=_markers(table.rows, lang),
        decimal_comma=_decimal_comma(table.rows, file_lang),
        provenance=make_provenance(
            source=_SOURCE,
            url=url,
            cached=cached,
            schema_name="phac_infobase.DatasetDescription",
            as_of=_as_of(table.last_modified),
            freshness=_frequency(dataset, lang),
        ),
    )


async def query(
    dataset_id: str,
    *,
    filters: dict[str, str] | None = None,
    geography: str | None = None,
    start: str | None = None,
    end: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> QueryResult:
    """Rows of one dataset; the most recent `limit` when it has a date column."""
    if limit < 1 or limit > constants.ROWS_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.")
    start_date = _bound(start, "start", end=False)
    end_date = _bound(end, "end", end=True)
    if start_date and end_date and start_date > end_date:
        raise InvalidInput(f"start {start!r} is after end {end!r}.")
    dataset = _dataset(dataset_id)
    table, cached, url, file_lang = await load(dataset, lang)
    title, _, _ = _text(dataset, lang)

    wanted = [(_resolve(table.columns, k), _fold(v)) for k, v in (filters or {}).items()]
    matching = [r for r in table.rows if all(_fold(r.get(c, "")) == v for c, v in wanted)]

    geo_column = _first_present(table.columns, dataset.geo_columns)
    if geography and geography.strip():
        if geo_column is None:
            raise InvalidInput(
                f"{dataset.id} has no geography column; filter a column instead. "
                f"Columns are {table.columns}."
            )
        matches_geo = geo_matcher(geography)
        matching = [r for r in matching if matches_geo(r.get(geo_column, ""))]

    date_column = _first_present(table.columns, dataset.date_columns)
    if (start_date or end_date) and date_column is None:
        raise InvalidInput(f"{dataset.id} has no date column; use filters instead.")
    if date_column:
        dated = [(parse_period(r.get(date_column, "")), r) for r in matching]
        if start_date or end_date:
            dated = [
                (d, r)
                for d, r in dated
                if d
                and (start_date is None or d >= start_date)
                and (end_date is None or d <= end_date)
            ]
        dated.sort(key=lambda pair: pair[0] or date.min)
        matching = [r for _, r in dated]
        kept = matching[-limit:]
    else:
        kept = matching[:limit]

    chosen = [_resolve(table.columns, c) for c in columns] if columns else table.columns
    rows = [{c: r.get(c, "") for c in chosen} for r in kept]
    return QueryResult(
        id=dataset.id,
        title=title,
        file_url=url,
        columns=chosen,
        rows=rows,
        total_rows=len(table.rows),
        matching_rows=len(matching),
        returned_count=len(rows),
        date_column=date_column,
        geo_column=geo_column,
        markers=_markers(rows, lang),
        decimal_comma=_decimal_comma(rows, file_lang),
        provenance=make_provenance(
            source=_SOURCE,
            url=url,
            cached=cached,
            schema_name="phac_infobase.QueryResult",
            as_of=_as_of(table.last_modified),
            freshness=_frequency(dataset, lang),
            coverage=(
                f"{len(rows)} of {len(matching)} matching rows"
                + (" (the most recent, oldest first)" if date_column else "")
            ),
            limits=f"rows capped at {limit}",
        ),
    )
