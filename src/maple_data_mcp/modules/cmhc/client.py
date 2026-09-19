"""HTTP client for CMHC's Housing Market Information Portal (HMIP).

Every function wraps `shared.http.get_raw`/`post_form_raw` through the
cmhc rate limiter and either returns a typed model or raises a
`shared/errors.py` exception. The following was confirmed live against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ this session (not assumed from
the independently-maintained `mountainMath/cmhc` R package alone,
though its source was read and cross-checked as the "existing community
access pattern" this project's PROJECT_GUIDE.md asks to investigate):

- `GET /{lang}/TableMapChart?geographyType=Country&geographyId=1` ->
  full category taxonomy for a geography, as
  `<a data-category-link="true" href=".../TableCategory?...
  categoryLevel1=...&categoryLevel2=...">` anchors. `categoryLevel1`/
  `categoryLevel2` are read straight from each anchor's own href query
  string (case-insensitively - the site itself is inconsistent, using
  lowercase-first param names here and uppercase-first ones on
  TableMatchingCriteria-bound links elsewhere, both confirmed to work
  since ASP.NET MVC model binding matches query names case-
  insensitively).
- `GET /{lang}/TableMapChart/TableCategory?GeographyType=...&
  GeographyId=...&CategoryLevel1=...&CategoryLevel2=...` (with NO
  ColumnField/RowField) -> every valid `(ColumnField, RowField)`
  combination for that category, each already resolved into a full
  `.../TableMatchingCriteria?...` link with a human label as the
  anchor's own text (e.g. "Bedroom Type", "Historical Time Periods").
  Confirmed live: calling this WITH a ColumnField/RowField narrows the
  response to two 1-D "what if you changed just this" slices around the
  requested point rather than the full option set - `get_table_options`
  below deliberately never sends those two params for this reason.
- `GET /{lang}/TableMapChart/TableMatchingCriteria?GeographyType=...&
  GeographyId=...&CategoryLevel1=...&CategoryLevel2=...&ColumnField=...
  &RowField=...` -> resolves a category+fields combination to one
  concrete table. Embeds
  `<input id="serialized-model" data-table-model="{...}">`, an
  HTML-escaped JSON blob confirmed live to carry the resolved `TableId`
  (a dotted survey/series/dimension/breakdown code, e.g. "2.2.1"),
  `GeographyTypeId`, `TableName`, and (genuinely misspelled in CMHC's
  own payload, confirmed live - read verbatim, do not "fix" it)
  `GeograghyName`. This is what lets `TableId`/`GeographyTypeId` be
  resolved live from category names with no hardcoded table catalogue -
  unlike the reference R package, which hardcodes its entire table
  registry by hand because it never uses this discovery path.
- `POST /{lang}/TableMapChart/ExportTable`, form body
  `{TableId, GeographyId, GeographyTypeId, exportType: "csv"}` -> `200
  OK`, `Content-Type: text/csv`. Confirmed live end-to-end for both a
  `RowField=TIMESERIES` table (national historical vacancy rates,
  1990-2025) and a `RowField=21` ("Provinces" breakdown) table - neither
  needed `BreakdownGeographyTypeId` in the POST body, matching the
  reference package's own params exactly.
  * **The CSV is Windows-1252 (cp1252) encoded, not UTF-8 and not
    strict ISO-8859-1/latin-1** - confirmed live: a title-line em-dash
    (byte 0x97) decodes to U+2014 EM DASH under cp1252 but to an
    unprintable C1 control character under true latin-1. (The reference
    package's own code comment claims "latin1"; this was checked
    directly against the raw bytes rather than trusted.)
  * Shape: title line, subtitle line, a header row with **paired
    (label, "") columns** - one label cell followed by one empty cell
    per breakdown category - then one data row per period as **paired
    (value, flag) columns**, then a blank line, then a "Notes" block
    (reliability-code legend + source line).
  * A cell can hold `"**"` (suppressed for confidentiality / not
    statistically reliable) or `"++"` (change not statistically
    significant, % Change tables only) instead of a number - see
    constants.py's SUPPRESSED_VALUE_TOKENS. Confirmed live in a real
    province-level row (Prince Edward Island's Studio vacancy rate).
- `GET /{lang}/Navigation/ProvincesByCountry?countryId=1` -> province
  options as `<a data-type="Province" data-type-code="2" data-id="n">
  NAME</a>` anchors. Confirmed live in both `en` and `fr` - numeric
  `data-id` values are identical across languages (only the name text
  changes), e.g. id=10 is Newfoundland and Labrador / Terre-Neuve-et-
  Labrador in both. **No live-confirmed endpoint exists yet for the
  next level down (Centre/CMA)** - three plausible controller-action
  name guesses (CentresByProvince, MarketsByProvince,
  CentersByProvince) all 404'd, and an autocomplete endpoint found in
  the page's own markup (`/Main/Search`) 404'd on every GET param name
  tried and 500'd on POST - genuinely unresolved, not guessed further.
  `list_provinces` therefore only covers Canada + province-level
  geography for now.
- An unresolvable category/geography/TableId/field combination returns
  **HTTP 500 with an ASP.NET "Server Error" (YSOD) page**, not a clean
  404/400 - confirmed live for a nonexistent category, a nonexistent
  geography id, and a nonexistent TableId, each producing a distinct,
  human-readable `<title>` ("Sequence contains no elements", "Sequence
  contains no matching element"). Mapped to `NotFound` here (a
  caller-actionable "no such table," not a generic upstream failure),
  with that title text preserved in the error message where present.
- No numeric rate limit is published, and this is a legacy IIS 7.5
  server - see constants.py for the conservative default used.
- A strict-TLS-negotiating client (e.g. a modern Chromium browser) can
  fail `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` against
  www03.cmhc-schl.gc.ca - confirmed live this session - but plain httpx
  (used here via shared/http.py) connects without issue, the same
  category of client-fingerprint quirk already documented for StatCan
  in AGENTS.md.
"""

from __future__ import annotations

import csv
import html as html_module
import json
import re
from io import StringIO
from typing import Any, NoReturn
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from maple_data_mcp.modules.cmhc import constants
from maple_data_mcp.modules.cmhc.schemas import (
    CategoryList,
    CategoryOption,
    ProvinceList,
    ProvinceOption,
    TableCell,
    TableDataResult,
    TableDataRow,
    TableFieldOption,
    TableOptions,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw, post_form_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TABLE_MODEL_RE = re.compile(r'data-table-model="([^"]*)"')


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _base_path(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")
    return f"{constants.BASE_URL}/{lang}"


def _require(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise InvalidInput(f"{name} must not be empty.")
    return value


def _ysod_title(body: str) -> str:
    match = _TITLE_RE.search(body)
    return match.group(1).strip() if match else "no further detail available"


def _raise_for_status(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    if status == 500:
        # Confirmed live: an unresolvable category/geography/TableId
        # combination returns an ASP.NET YSOD page, not a clean 404 -
        # see module docstring.
        raise NotFound(
            f"{context}: HMIP has no matching table for this combination "
            f"({_ysod_title(exc.response.text)})."
        ) from exc
    if status == 404:
        raise NotFound(f"{context}: not found.") from exc
    if status == 400:
        raise InvalidInput(f"{context}: rejected the request (HTTP 400).") from exc
    raise UpstreamError(f"{context}: upstream returned HTTP {status}.") from exc


async def _get_html(url: str, params: dict[str, Any]) -> str:
    await _limiter().acquire()
    try:
        response = await get_raw(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{url} did not respond in time (already retried by shared/http.py)."
        ) from exc
    return response.text


async def _post_csv(url: str, data: dict[str, Any]) -> bytes:
    await _limiter().acquire()
    try:
        response = await post_form_raw(url, data=data)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{url} did not respond in time (already retried by shared/http.py)."
        ) from exc
    return response.content


def _qs_get(query: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return None


def _parse_categories(body: str) -> list[CategoryOption]:
    soup = BeautifulSoup(body, "html.parser")
    seen: dict[tuple[str, str], CategoryOption] = {}
    for anchor in soup.find_all("a", attrs={"data-category-link": "true"}):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        query = parse_qs(urlparse(href).query)
        level1 = _qs_get(query, "categoryLevel1", "CategoryLevel1")
        level2 = _qs_get(query, "categoryLevel2", "CategoryLevel2")
        if not level1 or not level2:
            continue
        seen.setdefault(
            (level1, level2), CategoryOption(category_level_1=level1, category_level_2=level2)
        )
    return list(seen.values())


def _parse_table_options(body: str) -> list[TableFieldOption]:
    soup = BeautifulSoup(body, "html.parser")
    seen: dict[tuple[str, str], TableFieldOption] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or "TableMatchingCriteria" not in href:
            continue
        query = parse_qs(urlparse(href).query)
        column_field = _qs_get(query, "ColumnField", "columnField")
        row_field = _qs_get(query, "RowField", "rowField")
        if not column_field or not row_field:
            continue
        label = anchor.get_text(strip=True) or f"{column_field}/{row_field}"
        seen.setdefault(
            (column_field, row_field),
            TableFieldOption(label=label, column_field=column_field, row_field=row_field),
        )
    return list(seen.values())


def _parse_provinces(body: str) -> list[ProvinceOption]:
    soup = BeautifulSoup(body, "html.parser")
    provinces: list[ProvinceOption] = []
    for anchor in soup.find_all("a", attrs={"data-type": "Province"}):
        province_id = anchor.get("data-id")
        type_code = anchor.get("data-type-code")
        name = anchor.get_text(strip=True)
        if province_id and type_code and name:
            provinces.append(
                ProvinceOption(id=str(province_id), name=name, type_code=str(type_code))
            )
    return provinces


def _extract_table_model(body: str) -> dict[str, Any]:
    match = _TABLE_MODEL_RE.search(body)
    if not match:
        raise NotFound(
            "HMIP returned no resolvable table for this category/geography/field combination."
        )
    raw = html_module.unescape(match.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpstreamError("HMIP's embedded table model was not valid JSON.") from exc


def _parse_value_cell(raw_value: str, raw_flag: str) -> TableCell:
    raw_value = raw_value.strip()
    raw_flag = raw_flag.strip()
    if raw_value in constants.SUPPRESSED_VALUE_TOKENS:
        return TableCell(value=None, flag=raw_value)
    if not raw_value:
        return TableCell(value=None, flag=raw_flag or None)
    try:
        return TableCell(value=float(raw_value), flag=raw_flag or None)
    except ValueError:
        return TableCell(value=None, flag=raw_flag or raw_value)


def _parse_csv_export(text: str) -> tuple[list[str], list[TableDataRow], list[str]]:
    """Parse HMIP's ExportTable CSV: title line, subtitle line, a paired
    (label, "") header row, paired (value, flag) data rows per period,
    a blank line, then a Notes/legend block - see module docstring."""
    lines = text.splitlines()
    if len(lines) < 3:
        raise UpstreamError(
            "HMIP's CSV export was shorter than expected (missing header/data rows)."
        )

    body_rows = list(csv.reader(StringIO("\n".join(lines[2:]))))
    if not body_rows:
        raise UpstreamError("HMIP's CSV export had no header row.")

    header = body_rows[0]
    columns = [cell for cell in header[1::2] if cell]

    rows: list[TableDataRow] = []
    notes: list[str] = []
    past_data = False
    for raw_row in body_rows[1:]:
        if not any(cell.strip() for cell in raw_row):
            past_data = True
            continue
        if past_data:
            note_text = ", ".join(cell.strip() for cell in raw_row if cell.strip())
            if note_text:
                notes.append(note_text)
            continue

        period = raw_row[0].strip()
        values: dict[str, TableCell] = {}
        for i, column in enumerate(columns):
            value_idx = 1 + 2 * i
            flag_idx = value_idx + 1
            raw_value = raw_row[value_idx] if value_idx < len(raw_row) else ""
            raw_flag = raw_row[flag_idx] if flag_idx < len(raw_row) else ""
            values[column] = _parse_value_cell(raw_value, raw_flag)
        rows.append(TableDataRow(period=period, values=values))

    return columns, rows, notes


async def list_categories(
    *, geography_type: str = "Country", geography_id: str = "1", lang: str = "en"
) -> CategoryList:
    geography_type = _require(geography_type, "geography_type")
    geography_id = _require(geography_id, "geography_id")
    base = _base_path(lang)
    params = {"geographyType": geography_type, "geographyId": geography_id}
    url = f"{base}/TableMapChart"
    cache_key = f"cmhc:categories:{lang}:{geography_type}:{geography_id}"

    async def fetch() -> list[CategoryOption]:
        body = await _get_html(url, params)
        return _parse_categories(body)

    categories, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_CATEGORIES_SECONDS, fetch
    )
    return CategoryList(
        geography_type=geography_type,
        geography_id=geography_id,
        categories=categories,
        total_count=len(categories),
        provenance=make_provenance(
            source="cmhc",
            url=f"{url}?{urlencode(params)}",
            cached=was_cached,
            schema_name="cmhc.CategoryList",
        ),
    )


async def get_table_options(
    category_level_1: str,
    category_level_2: str,
    *,
    geography_type: str = "Country",
    geography_id: str = "1",
    lang: str = "en",
) -> TableOptions:
    category_level_1 = _require(category_level_1, "category_level_1")
    category_level_2 = _require(category_level_2, "category_level_2")
    geography_type = _require(geography_type, "geography_type")
    geography_id = _require(geography_id, "geography_id")
    base = _base_path(lang)
    params = {
        "GeographyType": geography_type,
        "GeographyId": geography_id,
        "CategoryLevel1": category_level_1,
        "CategoryLevel2": category_level_2,
    }
    url = f"{base}/TableMapChart/TableCategory"
    cache_key = f"cmhc:table_options:{lang}:{sorted(params.items())}"

    async def fetch() -> list[TableFieldOption]:
        body = await _get_html(url, params)
        return _parse_table_options(body)

    field_options, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TABLE_OPTIONS_SECONDS, fetch
    )
    if not field_options:
        raise NotFound(
            f"No breakdown options found for category ({category_level_1!r}, "
            f"{category_level_2!r}) at {geography_type} {geography_id!r}."
        )
    return TableOptions(
        category_level_1=category_level_1,
        category_level_2=category_level_2,
        field_options=field_options,
        provenance=make_provenance(
            source="cmhc",
            url=f"{url}?{urlencode(params)}",
            cached=was_cached,
            schema_name="cmhc.TableOptions",
        ),
    )


async def list_provinces(*, lang: str = "en") -> ProvinceList:
    base = _base_path(lang)
    url = f"{base}/Navigation/ProvincesByCountry"
    params = {"countryId": "1"}
    cache_key = f"cmhc:provinces:{lang}"

    async def fetch() -> list[ProvinceOption]:
        body = await _get_html(url, params)
        return _parse_provinces(body)

    provinces, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_PROVINCES_SECONDS, fetch
    )
    return ProvinceList(
        provinces=provinces,
        provenance=make_provenance(
            source="cmhc",
            url=f"{url}?countryId=1",
            cached=was_cached,
            schema_name="cmhc.ProvinceList",
        ),
    )


async def get_table_data(
    category_level_1: str,
    category_level_2: str,
    column_field: str,
    row_field: str,
    *,
    geography_type: str = "Country",
    geography_id: str = "1",
    lang: str = "en",
) -> TableDataResult:
    category_level_1 = _require(category_level_1, "category_level_1")
    category_level_2 = _require(category_level_2, "category_level_2")
    column_field = _require(column_field, "column_field")
    row_field = _require(row_field, "row_field")
    geography_type = _require(geography_type, "geography_type")
    geography_id = _require(geography_id, "geography_id")
    base = _base_path(lang)

    match_params = {
        "GeographyType": geography_type,
        "GeographyId": geography_id,
        "CategoryLevel1": category_level_1,
        "CategoryLevel2": category_level_2,
        "ColumnField": column_field,
        "RowField": row_field,
    }
    match_url = f"{base}/TableMapChart/TableMatchingCriteria"
    export_url = f"{base}/TableMapChart/ExportTable"
    cache_key = f"cmhc:table_data:{lang}:{sorted(match_params.items())}"

    async def fetch() -> dict[str, Any]:
        body = await _get_html(match_url, match_params)
        model = _extract_table_model(body)
        table_id = model.get("TableId")
        geography_type_id = model.get("GeographyTypeId")
        if not table_id or geography_type_id is None:
            raise NotFound(
                f"HMIP resolved no TableId for category ({category_level_1!r}, "
                f"{category_level_2!r}) with column_field={column_field!r}, "
                f"row_field={row_field!r}."
            )
        export_params = {
            "TableId": str(table_id),
            "GeographyId": geography_id,
            "GeographyTypeId": str(geography_type_id),
            "exportType": "csv",
        }
        raw_csv = await _post_csv(export_url, export_params)
        text = raw_csv.decode(constants.CSV_ENCODING)
        columns, rows, notes = _parse_csv_export(text)
        return {
            "table_id": str(table_id),
            # sic: CMHC's own JSON key is "GeograghyName" - see module docstring.
            "table_name": model.get("TableName") or "",
            "geography_name": model.get("GeograghyName") or "",
            "columns": columns,
            "rows": rows,
            "notes": notes,
        }

    parsed, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TABLE_DATA_SECONDS, fetch
    )
    return TableDataResult(
        table_id=parsed["table_id"],
        table_name=parsed["table_name"],
        geography_name=parsed["geography_name"],
        category_level_1=category_level_1,
        category_level_2=category_level_2,
        column_field=column_field,
        row_field=row_field,
        columns=parsed["columns"],
        rows=parsed["rows"],
        notes=parsed["notes"],
        provenance=make_provenance(
            source="cmhc",
            url=export_url,
            cached=was_cached,
            schema_name="cmhc.TableDataResult",
        ),
    )
