"""HTTP client for CMHC's Housing Market Information Portal (HMIP).

Every function wraps `shared.http.get_raw`/`post_form_raw` through the
cmhc rate limiter and either returns a typed model or raises a
`shared/errors.py` exception. The following was confirmed live against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ this session (not assumed from
the independently-maintained `mountainMath/cmhc` R package alone,
though its source was read and cross-checked as the "existing community
access pattern" this project's docs/PROJECT_GUIDE.md asks to investigate):

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
  resolved live from category names with no hardcoded table catalogue
  (the R package keeps a hand-built table registry instead). The same
  model also carries `AvailableFilters` (e.g. `season`: April/October,
  `dwelling_type_desc_en`: Row/Apartment/Row-Apartment for a Rental
  Market Survey table) - confirmed live these are extra filter
  dimensions beyond the ColumnField/RowField axes, and confirmed to
  genuinely change returned values (national vacancy rate for "Row"
  dwellings differs from "Apartment" for the same period) rather than
  just relabel the same numbers. `get_table_data`'s `filters` parameter
  is validated against this before it is sent.
- `POST /{lang}/TableMapChart/ExportTable`, form body
  `{TableId, GeographyId, GeographyTypeId, exportType: "csv",
  AppliedFilters[i].Key/.Value...}` -> `200
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
  * Shape: title line, subtitle line, a header row, one data row per
    period, a blank line, then a "Notes" block (reliability-code legend
    + source line where present). **Whether a column is followed by a
    companion quality/flag column (an empty header cell after a label)
    is NOT fixed across every table** - confirmed live: a statistically-
    sampled survey table (Rental Market Survey vacancy rates/rents) has
    one flag column per value column; a census-style administrative
    table (Starts and Completions Survey, which counts every issued
    permit rather than sampling) has none. Assuming every column is
    doubled (`header[1::2]`) silently misaligned and corrupted values
    for the latter shape - `_header_columns` below instead walks the
    header and only pairs a column with a flag when the following cell
    is genuinely empty.
  * Confirmed live: a value of 1,000 or more uses a thousands-comma
    separator inside its quoted CSV field (e.g. `"1,013"`) - stripped
    before `float()`, which does not accept it.
  * A cell can hold `"**"` (suppressed for confidentiality / not
    statistically reliable), `"++"` (change not statistically
    significant, % Change tables only), or `"n/a"` instead of a number -
    see constants.py's SUPPRESSED_VALUE_TOKENS. Confirmed live in a real
    province-level row (Prince Edward Island's Studio vacancy rate).
    Separately, a bare `"-"` is a real, counted zero, not a suppressed
    value (constants.py's NIL_VALUE_TOKENS) - confirmed live cross-
    checking the reference package's own parse_numeric() helper, which
    treats it the same way.
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

import asyncio
import csv
import html as html_module
import json
import re
import unicodedata
from datetime import UTC, datetime
from io import StringIO
from typing import Any, Literal, NoReturn
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.cmhc import constants
from maplestats_mcp.modules.cmhc.methodology import FLAG_MEANINGS
from maplestats_mcp.modules.cmhc.schemas import (
    CategoryList,
    CategoryOption,
    FilterOption,
    MetroAreaList,
    MetroAreaOption,
    ProvinceList,
    ProvinceOption,
    TableCell,
    TableDataResult,
    TableDataRow,
    TableFieldOption,
    TableOptions,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw, post_form_raw
from maplestats_mcp.shared.i18n import ERROR_KEYS, french_spacing
from maplestats_mcp.shared.i18n import t as i18n_text
from maplestats_mcp.shared.rate_limiter import get_limiter

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TABLE_MODEL_RE = re.compile(r'data-table-model="([^"]*)"')


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _text(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


def _flag_legend(rows: list[TableDataRow], lang: str) -> dict[str, str]:
    """The meaning of every cell flag the rows carry, in CMHC's order.

    The CSV's own Notes block holds a legend only for some tables, so a
    reader could not always tell what a "d" or "**" beside a value means.
    """
    present = {cell.flag for row in rows for cell in row.values.values() if cell.flag}
    return {
        code: _text(en, fr, lang) for code, (en, fr) in FLAG_MEANINGS.items() if code in present
    }


def _error(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> ValueError:
    """The error to raise with `from`: English as before, French in the typed template."""
    return exc_cls(i18n_text(ERROR_KEYS[exc_cls.__name__], "fr", detail=fr) if lang == "fr" else en)


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


def _require(value: str, name: str, lang: str = "en") -> str:
    value = value.strip()
    if not value:
        _raise(InvalidInput, f"{name} must not be empty.", f"{name} ne doit pas être vide.", lang)
    return value


def _ysod_title(body: str) -> str:
    match = _TITLE_RE.search(body)
    if not match:
        return "no further detail available"
    # The title carries markup ("...not a number.<br>Parameter name: 999",
    # live 2026-10-03); keep the text only.
    text = re.sub(r"<[^>]+>", " ", html_module.unescape(match.group(1)))
    return " ".join(text.split()) or "no further detail available"


def _norm(text: str) -> str:
    """Lower-case, accents dropped, punctuation to single spaces: for name matching."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", bare).split())


def _geography_type(geography_type: str, lang: str) -> str:
    """HMIP's own name for a geography type, from the spellings callers use."""
    key = re.sub(r"[\s_\-]+", "", geography_type.casefold())
    resolved = constants.GEOGRAPHY_TYPES.get(key)
    if resolved is None:
        _raise(
            InvalidInput,
            f"geography_type {geography_type!r} is not one HMIP knows; use 'Country', "
            "'Province' or 'MetropolitanMajorArea' (a CMA or other centre: 'CMA' also works).",
            f"geography_type {geography_type!r} n'est pas un type connu du PIMH ; utilisez "
            "'Country', 'Province' ou 'MetropolitanMajorArea' (une RMR ou un autre centre : "
            "'RMR' fonctionne aussi).",
            lang,
        )
    return resolved


def _pick_by_name(
    name: str, options: list[tuple[str, str]], kind_en: str, kind_fr: str, lang: str
) -> str:
    """The id of the one option whose name matches: exact first, then a whole-word part.

    `options` are (id, name) pairs. "Toronto" matches "Toronto" exactly; "Ottawa" matches
    "Ottawa - Gatineau" when no area is named "Ottawa". More than one match is refused with
    the candidates, never guessed.
    """
    wanted = _norm(name)
    exact = {i: n for i, n in options if _norm(n) == wanted}
    if not exact:
        pattern = re.compile(rf"(^| ){re.escape(wanted)}( |$)")
        exact = {i: n for i, n in options if wanted and pattern.search(_norm(n))}
    if len(exact) == 1:
        return next(iter(exact))
    if not exact:
        _raise(
            InvalidInput,
            f"No {kind_en} named {name!r}. Pass a numeric geography_id, or list the names "
            "with cmhc_list_metropolitan_areas (cmhc_list_provinces for provinces).",
            f"aucune {kind_fr} nommée {name!r}. Passez un geography_id numérique, ou voyez "
            "les noms avec cmhc_list_metropolitan_areas (cmhc_list_provinces pour les "
            "provinces).",
            lang,
        )
    found = "; ".join(f"{i} ({n})" for i, n in sorted(exact.items(), key=lambda kv: kv[1]))
    _raise(
        InvalidInput,
        f"{name!r} matches more than one {kind_en}: {found}. Pass one of these ids.",
        f"{name!r} correspond à plus d'une {kind_fr} : {found}. Passez l'un de ces identifiants.",
        lang,
    )


async def _resolve_geography(geography_type: str, geography_id: str, lang: str) -> tuple[str, str]:
    """HMIP's (type, id) for what the caller passed, refusing what HMIP would misread.

    An unknown province id is answered with the national category list
    (geography_id="999" with type Province returned all of Canada's
    categories, live 2026-10-03), so a typo read as a real answer. The same
    check runs for metropolitan areas. A name ("Toronto", "Ontario") is
    accepted for an id when exactly one area or province carries it.
    """
    kind = _geography_type(geography_type, lang)
    if kind == "Country":
        if geography_id.strip().casefold() in {"1", "canada"}:
            return kind, "1"
        _raise(
            InvalidInput,
            f"For geography_type 'Country' the id is '1' (Canada), got {geography_id!r}.",
            f"pour geography_type 'Country', l'identifiant est '1' (Canada), "
            f"reçu {geography_id!r}.",
            lang,
        )
    if kind == "Province":
        provinces = (await list_provinces(lang=lang)).provinces
        options = [(p.id, p.name) for p in provinces]
        if not geography_id.isdigit():
            return kind, _pick_by_name(geography_id, options, "province", "province", lang)
        if geography_id not in {p.id for p in provinces}:
            known = ", ".join(f"{p.id} ({p.name})" for p in provinces)
            _raise(
                InvalidInput,
                f"No province with id {geography_id!r}; province ids are {known}.",
                f"aucune province avec l'identifiant {geography_id!r} ; les identifiants des "
                f"provinces sont {known}.",
                lang,
            )
        return kind, geography_id
    areas = (await list_metropolitan_areas(lang=lang)).areas
    if not geography_id.isdigit():
        options = list({a.id: a.name for a in areas}.items())
        return kind, _pick_by_name(
            geography_id, options, "metropolitan area", "zone métropolitaine", lang
        )
    if geography_id not in {a.id for a in areas}:
        _raise(
            InvalidInput,
            f"No metropolitan area with id {geography_id!r}. cmhc_list_metropolitan_areas "
            "lists them (with name='Toronto' to find one).",
            f"aucune zone métropolitaine avec l'identifiant {geography_id!r}. "
            "cmhc_list_metropolitan_areas les énumère (avec name='Toronto' pour en trouver "
            "une).",
            lang,
        )
    return kind, geography_id


def _raise_for_status(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    if status == 500:
        # Confirmed live: an unresolvable category/geography/TableId
        # combination returns an ASP.NET YSOD page, not a clean 404 -
        # see module docstring.
        title = _ysod_title(exc.response.text)
        raise _error(
            NotFound,
            f"{context}: HMIP has no matching table for this combination ({title}).",
            f"{context} : le PIMH n'a aucun tableau pour cette combinaison (message de la "
            f"source : {title}).",
            lang,
        ) from exc
    if status == 404:
        raise _error(NotFound, f"{context}: not found.", f"{context} : introuvable.", lang) from exc
    if status == 400:
        raise _error(
            InvalidInput,
            f"{context}: rejected the request (HTTP 400).",
            f"{context} : requête refusée (HTTP 400).",
            lang,
        ) from exc
    raise _error(
        UpstreamError,
        f"{context}: upstream returned HTTP {status}.",
        f"{context} : la source a renvoyé HTTP {status}.",
        lang,
    ) from exc


def _no_answer(url: str, lang: str) -> ValueError:
    return _error(
        UpstreamUnavailable,
        f"{url} did not respond in time (already retried by shared/http.py).",
        f"{url} n'a pas répondu à temps (malgré les nouvelles tentatives).",
        lang,
    )


async def _get_html(url: str, params: dict[str, Any], lang: str = "en") -> str:
    await _limiter().acquire()
    try:
        response = await get_raw(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url, lang)
    except httpx.HTTPError as exc:
        raise _no_answer(url, lang) from exc
    return response.text


async def _post_csv(url: str, data: dict[str, Any], lang: str = "en") -> bytes:
    await _limiter().acquire()
    try:
        response = await post_form_raw(url, data=data)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url, lang)
    except httpx.HTTPError as exc:
        raise _no_answer(url, lang) from exc
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


def _breakdown_of(anchor: Any) -> Literal["column", "row"] | None:
    """Which axis an option link's label names, from the list it sits in.

    Confirmed live 2026-11-09 on TableCategory for Edmonton: HMIP lists the column
    breakdowns under <h4>By:</h4> (French "Selon :") in a plain <ol>, and the row
    breakdowns under <h4>Display Options:</h4> ("Options d'affichage :") in
    <ol class="last-of-type">. A table with a single column breakdown has no "By:"
    list at all (% Change of Average Rent: its column is always Bedroom Type).
    """
    ol = anchor.find_parent("ol")
    if ol is None:
        return None
    classes = ol.get("class") or []
    heading = ol.find_previous_sibling("h4")
    title = _norm(heading.get_text()) if heading is not None else ""
    if "last-of-type" in classes or "display" in title or "affichage" in title:
        return "row"
    if title.startswith(("by", "selon")):
        return "column"
    return None


def _parse_table_options(body: str) -> list[TableFieldOption]:
    soup = BeautifulSoup(body, "html.parser")
    seen: dict[tuple[str, str, str | None], TableFieldOption] = {}
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
        breakdown = _breakdown_of(anchor)
        # The default table appears in both lists, under its column label ("Bedroom
        # Type") and its row label ("Survey Zones"); both labels are kept.
        seen.setdefault(
            (column_field, row_field, breakdown),
            TableFieldOption(
                label=label, column_field=column_field, row_field=row_field, breakdown=breakdown
            ),
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


def _extract_table_model(body: str, lang: str = "en") -> dict[str, Any]:
    match = _TABLE_MODEL_RE.search(body)
    if not match:
        _raise(
            NotFound,
            "HMIP returned no resolvable table for this category/geography/field combination.",
            "le PIMH n'a renvoyé aucun tableau pour cette combinaison de catégorie, de "
            "géographie et de champs.",
            lang,
        )
    raw = html_module.unescape(match.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _error(
            UpstreamError,
            "HMIP's embedded table model was not valid JSON.",
            "le modèle de tableau intégré du PIMH n'était pas du JSON valide.",
            lang,
        ) from exc


# Thousands separators a French export can use: space, no-break space, and the
# narrow no-break space (U+202F) that French typography prescribes.
_FRENCH_THOUSANDS_RE = re.compile(r"[ \u00a0\u202f]")


def _parse_number(raw_value: str, lang: str) -> float:
    """Parse a value cell's number, raising ValueError when it is not one.

    English (confirmed live): a comma is a thousands separator ("1,013").
    French: a comma is the decimal mark and a space or no-break space groups
    thousands ("1 013,5", "1,5"), as in French Canadian typography. The
    French export's number format has not been confirmed against a live
    download yet; stripping every comma there would turn "1,5" into 15.0
    without any error, so the French rule is the safer reading.
    """
    if lang == "fr":
        return float(_FRENCH_THOUSANDS_RE.sub("", raw_value).replace(",", "."))
    return float(raw_value.replace(",", ""))


def _parse_value_cell(raw_value: str, raw_flag: str, lang: str = "en") -> TableCell:
    raw_value = raw_value.strip()
    raw_flag = raw_flag.strip()
    if raw_value in constants.SUPPRESSED_VALUE_TOKENS:
        return TableCell(value=None, flag=raw_value)
    if raw_value in constants.NIL_VALUE_TOKENS:
        # Confirmed live (and matching the reference R package's own
        # parse_numeric()): a bare "-" means a real, counted zero, not a
        # suppressed/unavailable value - distinct from "**"/"++"/"n/a".
        return TableCell(value=0.0, flag=raw_flag or None)
    if not raw_value:
        return TableCell(value=None, flag=raw_flag or None)
    try:
        # Confirmed live: values >= 1,000 use a thousands-comma
        # separator inside the quoted CSV field (e.g. "1,013") - Python's
        # float() does not accept that, unlike the value's own literal
        # meaning, so it is stripped before parsing (see _parse_number for
        # the French reading).
        return TableCell(value=_parse_number(raw_value, lang), flag=raw_flag or None)
    except ValueError:
        return TableCell(value=None, flag=raw_flag or raw_value)


def _header_columns(header: list[str]) -> list[tuple[str, int, int | None]]:
    """Pair each non-empty header cell with a following empty cell as its
    quality/flag companion column, confirmed live to NOT be a fixed
    doubled-column shape across every table: a statistically-sampled
    survey table (e.g. Rental Market Survey vacancy rates/rents) pairs
    every value column with an adjacent reliability-flag column, while an
    administrative/census-style table (e.g. Starts and Completions Survey,
    which counts every permit rather than sampling) has no flag columns
    at all - `header[1::2]` (assuming every column is doubled) silently
    misaligned and corrupted values for the latter shape, which is why
    this walks the header sequentially and only pairs a column with a
    flag when the following cell is genuinely empty, rather than assuming
    every other cell is one.
    """
    columns: list[tuple[str, int, int | None]] = []
    i = 0
    n = len(header)
    while i < n:
        label = header[i].strip()
        if not label:
            i += 1
            continue
        if i + 1 < n and not header[i + 1].strip():
            columns.append((label, i, i + 1))
            i += 2
        else:
            columns.append((label, i, None))
            i += 1
    return columns


# Month names as HMIP writes them in an export's subtitle line, in both languages.
_MONTHS = {
    name: number
    for names in (
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ),
    )
    for number, name in enumerate(names, start=1)
}
# "[Month] YYYY", optionally followed by " to|à [Month] YYYY". Whatever follows is
# the table's filter description ("Row / Apartment", a season), not the period.
_PERIOD_RE = re.compile(
    r"^\s*(?:(?P<month1>[^\W\d_]+)\s+)?(?P<year1>\d{4})"
    r"(?:\s+(?:to|à)\s+(?:(?P<month2>[^\W\d_]+)\s+)?(?P<year2>\d{4}))?(?!\d)",
    re.IGNORECASE,
)


def _reference_period(subtitle: str) -> tuple[str | None, datetime | None]:
    """The reference period an export's subtitle line states, and its latest month.

    The line under the title starts with the period and may go on with the
    filters applied. Confirmed live on 2026-11-09: "October 2025 Row /
    Apartment" (a rental cross-tab), "1990 to 2025 Row / Apartment October"
    (its time series), "September 2026" and "January 1990 to September 2026"
    (starts), "2021" and "2009 to 2021" (seniors' housing), and in French
    "octobre 2025 En rangée / Appartements" and "1990 à 2025 ...". The period
    is returned in CMHC's own words. The date is the first of the latest
    period's month, and None when that period has no month: a bare year would
    claim a precision CMHC did not state (its rental survey is held in October).
    A line that does not open with a period gives (None, None).
    """
    match = _PERIOD_RE.match(subtitle)
    if not match:
        return None, None
    months = [match.group("month1"), match.group("month2")]
    if any(m is not None and m.lower() not in _MONTHS for m in months):
        return None, None
    latest_year = match.group("year2") or match.group("year1")
    latest_month = months[1] if match.group("year2") else months[0]
    as_of = (
        datetime(int(latest_year), _MONTHS[latest_month.lower()], 1, tzinfo=UTC)
        if latest_month
        else None
    )
    return match.group(0).strip(), as_of


def _citation(table_id: str, table_name: str, geography: str, period: str | None, lang: str) -> str:
    parts = [
        _text(
            "Canada Mortgage and Housing Corporation (CMHC), Housing Market Information Portal",
            "Société canadienne d'hypothèques et de logement (SCHL), Portail de l'information "
            "sur le marché de l'habitation",
            lang,
        ),
        _text(f"table {table_id}", f"tableau {table_id}", lang),
        table_name.strip(),
        geography,
        period or _text("reference period not stated", "période de référence non indiquée", lang),
    ]
    return ", ".join(p for p in parts if p) + "."


def _parse_csv_export(
    text: str, lang: str = "en", *, total_label: str = ""
) -> tuple[list[str], list[TableDataRow], list[str]]:
    """Parse HMIP's ExportTable CSV: title line, subtitle line, a header
    row (columns sometimes, but not always, paired with a following empty
    quality/flag column - see `_header_columns`), one data row per period,
    a blank line, then a Notes/legend block - see module docstring.

    A cross-tab export (one row per province or centre) ends with the
    requested geography's total row, and CMHC leaves that row's label cell
    empty. Confirmed live on 2026-11-09 for vacancy rates by province
    (2.1.1.1), starts by province (5.4.1) and Alberta's vacancy rates by
    centre (2.1.1.2): the unlabelled row is Canada's (or Alberta's) total,
    the same figures the parent geography's own row shows elsewhere. Such a
    row takes `total_label`, the geography's name, so it is not returned
    with an empty `period`.
    """
    lines = text.splitlines()
    if len(lines) < 3:
        _raise(
            UpstreamError,
            "HMIP's CSV export was shorter than expected (missing header/data rows).",
            "l'export CSV du PIMH est plus court que prévu (en-tête ou lignes de données absents).",
            lang,
        )

    body_rows = list(csv.reader(StringIO("\n".join(lines[2:]))))
    if not body_rows:
        _raise(
            UpstreamError,
            "HMIP's CSV export had no header row.",
            "l'export CSV du PIMH n'a pas de ligne d'en-tête.",
            lang,
        )

    column_specs = _header_columns(body_rows[0])
    if not column_specs:
        _raise(
            UpstreamError,
            "HMIP's CSV export header had no data columns.",
            "l'en-tête de l'export CSV du PIMH n'a aucune colonne de données.",
            lang,
        )
    columns = [name for name, _, _ in column_specs]

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

        period = raw_row[0].strip() or total_label
        values: dict[str, TableCell] = {}
        for name, value_idx, flag_idx in column_specs:
            raw_value = raw_row[value_idx] if value_idx < len(raw_row) else ""
            raw_flag = raw_row[flag_idx] if flag_idx is not None and flag_idx < len(raw_row) else ""
            values[name] = _parse_value_cell(raw_value, raw_flag, lang)
        rows.append(TableDataRow(period=period, values=values))

    return columns, rows, notes


async def list_categories(
    *, geography_type: str = "Country", geography_id: str = "1", lang: str = "en"
) -> CategoryList:
    geography_type = _require(geography_type, "geography_type", lang)
    geography_id = _require(geography_id, "geography_id", lang)
    geography_type, geography_id = await _resolve_geography(geography_type, geography_id, lang)
    base = _base_path(lang)
    params = {"geographyType": geography_type, "geographyId": geography_id}
    url = f"{base}/TableMapChart"
    cache_key = f"cmhc:categories:{lang}:{geography_type}:{geography_id}"

    async def fetch() -> list[CategoryOption]:
        body = await _get_html(url, params, lang)
        found = _parse_categories(body)
        if not found:
            # Raised inside fetch so the empty page is never cached for 24 h.
            _raise(
                UpstreamError,
                f"HMIP's category page for {geography_type} {geography_id!r} held no "
                "category links (a[data-category-link]); the page layout may have changed.",
                f"la page des catégories du PIMH pour {geography_type} {geography_id!r} ne "
                "contenait aucun lien de catégorie (a[data-category-link]) ; la mise en page "
                "a peut-être changé.",
                lang,
            )
        return found

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
            lang=lang,
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
    category_level_1 = _require(category_level_1, "category_level_1", lang)
    category_level_2 = _require(category_level_2, "category_level_2", lang)
    geography_type = _require(geography_type, "geography_type", lang)
    geography_id = _require(geography_id, "geography_id", lang)
    geography_type, geography_id = await _resolve_geography(geography_type, geography_id, lang)
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
        body = await _get_html(url, params, lang)
        return _parse_table_options(body)

    field_options, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TABLE_OPTIONS_SECONDS, fetch
    )
    if not field_options:
        _raise(
            NotFound,
            f"No breakdown options found for category ({category_level_1!r}, "
            f"{category_level_2!r}) at {geography_type} {geography_id!r}.",
            f"aucune option de répartition pour la catégorie ({category_level_1!r}, "
            f"{category_level_2!r}) au niveau {geography_type} {geography_id!r}.",
            lang,
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
            lang=lang,
        ),
    )


async def list_provinces(*, lang: str = "en") -> ProvinceList:
    base = _base_path(lang)
    url = f"{base}/Navigation/ProvincesByCountry"
    params = {"countryId": "1"}
    cache_key = f"cmhc:provinces:{lang}"

    async def fetch() -> list[ProvinceOption]:
        body = await _get_html(url, params, lang)
        found = _parse_provinces(body)
        if not found:
            # Raised inside fetch so the empty page is never cached for 24 h
            # (after which _resolve_geography would reject every province id).
            _raise(
                UpstreamError,
                'HMIP\'s province list held no province links (a[data-type="Province"]); '
                "the page layout may have changed.",
                "la liste des provinces du PIMH ne contenait aucun lien de province "
                '(a[data-type="Province"]) ; la mise en page a peut-être changé.',
                lang,
            )
        return found

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
            lang=lang,
        ),
    )


def _parse_metro_areas(body: str, province: ProvinceOption) -> list[MetroAreaOption]:
    soup = BeautifulSoup(body, "html.parser")
    found: list[MetroAreaOption] = []
    for anchor in soup.find_all("a", attrs={"data-type": "MetropolitanMajorArea"}):
        area_id = anchor.get("data-id")
        name = anchor.get_text(strip=True)
        if area_id and name:
            found.append(
                MetroAreaOption(
                    id=str(area_id),
                    name=name,
                    province_id=province.id,
                    province_name=province.name,
                )
            )
    return found


async def _metro_areas_of(
    province: ProvinceOption, lang: str
) -> tuple[list[MetroAreaOption], bool]:
    # Found 2026-11-03 through the province breadcrumb (POST Navigation/Breadcrumb links
    # each level's "expand" list): /Navigation/MetsByProvince/{province id} answers the
    # province's metropolitan major areas as a[data-type="MetropolitanMajorArea"] anchors
    # (65 for Ontario, Toronto = 2270), with the same ids in /en/ and /fr/. A territory
    # can have none (Nunavut, 62): that answer is the empty
    # <div class="MetropolitanMajorAreaContainer">. Any other page without anchors (a
    # maintenance or error page served with HTTP 200) is raised inside fetch, so it is
    # never cached for a day and valid ids are not refused meanwhile.
    url = f"{_base_path(lang)}/Navigation/MetsByProvince/{province.id}"

    async def fetch() -> list[MetroAreaOption]:
        body = await _get_html(url, {}, lang)
        found = _parse_metro_areas(body, province)
        if not found and "MetropolitanMajorAreaContainer" not in body:
            _raise(
                UpstreamError,
                f"HMIP's metropolitan area list for {province.name} held neither areas nor "
                "its list container; the page layout may have changed or the site is down.",
                f"la liste des zones métropolitaines du PIMH pour {province.name} ne "
                "contenait ni zones ni son conteneur ; la mise en page a peut-être changé ou "
                "le site est en panne.",
                lang,
            )
        return found

    return await cached_fetch(
        f"cmhc:metro_areas:{lang}:{province.id}",
        constants.CACHE_TTL_METRO_AREAS_SECONDS,
        fetch,
    )


async def list_metropolitan_areas(
    *, province_id: str | None = None, name: str | None = None, lang: str = "en"
) -> MetroAreaList:
    provinces = (await list_provinces(lang=lang)).provinces
    if province_id:
        wanted = province_id.strip()
        if not wanted.isdigit():
            wanted = _pick_by_name(
                wanted, [(p.id, p.name) for p in provinces], "province", "province", lang
            )
        chosen = [p for p in provinces if p.id == wanted]
        if not chosen:
            known = ", ".join(f"{p.id} ({p.name})" for p in provinces)
            _raise(
                InvalidInput,
                f"No province with id {province_id!r}; province ids are {known}.",
                f"aucune province avec l'identifiant {province_id!r} ; les identifiants des "
                f"provinces sont {known}.",
                lang,
            )
    else:
        chosen = provinces
    # Read together: one by one, the 13 lists took 20 s cold (live 2026-11-03); the rate
    # limiter still spaces the requests.
    results = await asyncio.gather(*(_metro_areas_of(p, lang) for p in chosen))
    areas = [area for found, _ in results for area in found]
    all_cached = all(was_cached for _, was_cached in results)
    if not areas and not province_id:
        _raise(
            UpstreamError,
            "HMIP listed no metropolitan areas in any province "
            '(a[data-type="MetropolitanMajorArea"]); the page layout may have changed.',
            "le PIMH n'a énuméré aucune zone métropolitaine dans aucune province "
            '(a[data-type="MetropolitanMajorArea"]) ; la mise en page a peut-être changé.',
            lang,
        )
    if name and name.strip():
        wanted_name = _norm(name)
        pattern = re.compile(rf"(^| ){re.escape(wanted_name)}( |$)")
        areas = [a for a in areas if pattern.search(_norm(a.name))]
    url = f"{_base_path(lang)}/Navigation/MetsByProvince/" + (
        chosen[0].id if len(chosen) == 1 else "{province_id}"
    )
    return MetroAreaList(
        areas=areas,
        total_count=len(areas),
        provenance=make_provenance(
            source="cmhc",
            url=url,
            cached=all_cached,
            schema_name="cmhc.MetroAreaList",
            lang=lang,
        ),
    )


def _parse_available_filters(model: dict[str, Any]) -> list[FilterOption]:
    """Parse the resolved table model's "AvailableFilters" entries.

    Confirmed live: each entry is {"Item1": key, "Item2": label|null,
    "Item3": [values...]} - e.g. {"Item1": "season", "Item2": null,
    "Item3": ["April", "October"]} or {"Item1": "dwelling_type_desc_en",
    "Item2": "Dwelling Type", "Item3": ["Row", "Apartment", "Row /
    Apartment"]}. Confirmed live these genuinely change returned values
    (e.g. national vacancy rate differs by dwelling type), not just a
    display label - a capability the CategoryLevel1/2 + ColumnField/
    RowField axes alone cannot reach for every table.
    """
    options: list[FilterOption] = []
    for entry in model.get("AvailableFilters") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("Item1")
        values = entry.get("Item3")
        if not key or not isinstance(values, list) or not values:
            continue
        options.append(
            FilterOption(key=key, label=entry.get("Item2"), values=[str(v) for v in values])
        )
    return options


def _validate_filters(
    filters: dict[str, str], available: list[FilterOption], context: str, lang: str = "en"
) -> None:
    by_key = {f.key: f.values for f in available}
    for key, value in filters.items():
        if key not in by_key:
            _raise(
                InvalidInput,
                f"{context}: filter key {key!r} is not available for this table "
                f"(available: {sorted(by_key)}).",
                f"{context} : la clé de filtre {key!r} n'existe pas pour ce tableau "
                f"(clés possibles : {sorted(by_key)}).",
                lang,
            )
        if value not in by_key[key]:
            _raise(
                InvalidInput,
                f"{context}: filter value {value!r} is not valid for {key!r} "
                f"(valid values: {by_key[key]}).",
                f"{context} : la valeur de filtre {value!r} n'est pas valide pour {key!r} "
                f"(valeurs possibles : {by_key[key]}).",
                lang,
            )


def _is_field_code(value: str) -> bool:
    """A code every table uses the same way, so it needs no lookup: a number or TIMESERIES.

    Not every code is one of these: Core Housing Need's are words ("HouseholdType",
    "Province"), and a province's vacancy-rate "Rent Quartiles" column is
    "RENTQUARTILE" (live 2026-11-09). `_resolve_fields` finds those among the table's own options.
    """
    return value.isdigit() or value.upper() == "TIMESERIES"


async def _resolve_fields(
    category_level_1: str,
    category_level_2: str,
    column_field: str,
    row_field: str,
    *,
    geography_type: str,
    geography_id: str,
    lang: str,
) -> tuple[str, str, str | None]:
    """Field codes for labels a caller copied from cmhc_get_table_options, and the
    column label still to check against the resolved table's name (or None).

    The chat demo's model passed column_field="Bedroom Type" (live 2026-11-03), which
    HMIP answers "Sequence contains no elements"; the code for it is "2". Numeric codes
    and TIMESERIES pass through untouched, so this costs a call (cached a day) only
    for anything else. A value is looked for first among the table's own codes, then
    among its labels: a code can be a word, and was rejected as an unknown label
    until 2026-11-09 ('HouseholdType', which cmhc_get_table_options itself lists).

    A column label is looked up in the "By:" list first and a row label in "Display
    Options:" (see `_breakdown_of`). A table with one column breakdown has no "By:"
    list: "% Change of Average Rent" for Edmonton lists only Survey Zones, Census
    Subdivisions and Historical Time Periods (live 2026-11-09), so the "Bedroom Type"
    that Average Rent ($) accepts was refused there although its column is Bedroom
    Type ("2"). There the one column code is used, and the label is returned so the
    caller can check it against the table's name ("% Change of Average Rents by
    Bedroom Type by Zone") once the table is resolved.
    """
    if _is_field_code(column_field) and _is_field_code(row_field):
        return column_field.upper(), row_field.upper(), None
    options = (
        await get_table_options(
            category_level_1,
            category_level_2,
            geography_type=geography_type,
            geography_id=geography_id,
            lang=lang,
        )
    ).field_options
    column_codes = sorted({o.column_field for o in options})
    has_by_list = any(o.breakdown == "column" for o in options)

    def listing() -> tuple[str, str]:
        def labels(kind: str, attr: str) -> str:
            found = {o.label: getattr(o, attr) for o in options if o.breakdown in (kind, None)}
            return ", ".join(f"{label} ({code})" for label, code in found.items()) or "-"

        columns = labels("column", "column_field")
        if not has_by_list and len(column_codes) == 1:
            columns = _text(
                f"one column breakdown only, code {column_codes[0]} (named in the table's title)",
                f"une seule répartition en colonnes, code {column_codes[0]} (nommée dans le "
                "titre du tableau)",
                lang,
            )
        return columns, labels("row", "row_field")

    def code(value: str, attr: str, kind: str) -> str:
        codes = {getattr(o, attr).upper(): getattr(o, attr) for o in options}
        if value.upper() in codes:
            return codes[value.upper()]
        if _is_field_code(value):
            return value.upper()
        wanted = _norm(value)
        for preferred in (True, False):
            for option in options:
                if (option.breakdown == kind) == preferred and _norm(option.label) == wanted:
                    return getattr(option, attr)
        columns, rows = listing()
        _raise(
            InvalidInput,
            f"{value!r} is not a {kind}_field code or label of this table. column_field "
            f"accepts: {columns}. row_field accepts: {rows}. Labels and codes come from "
            "cmhc_get_table_options.",
            f"{value!r} n'est ni un code ni un libellé de {kind}_field pour ce tableau. "
            f"column_field accepte : {columns}. row_field accepte : {rows}. Libellés et codes "
            "viennent de cmhc_get_table_options.",
            lang,
        )

    row_code = code(row_field, "row_field", "row")
    known_column = column_field.upper() in {c.upper() for c in column_codes} or any(
        _norm(o.label) == _norm(column_field) for o in options
    )
    # Only a label (words with spaces, "Bedroom Type") falls back to the one column
    # code; a code-shaped word ("RENTQUARTILE") that this table lacks is refused.
    is_label = " " in column_field.strip()
    if (
        is_label
        and not (known_column or has_by_list or _is_field_code(column_field))
        and len(column_codes) == 1
    ):
        return column_codes[0], row_code, column_field
    return code(column_field, "column_field", "column"), row_code, None


def _check_column_label(label: str | None, table_name: str, column_field: str, lang: str) -> None:
    """Refuse a column label the resolved table's own name does not carry."""
    if label is None or _norm(label) in _norm(table_name):
        return
    _raise(
        InvalidInput,
        f"column_field {label!r} does not name this table's only column breakdown "
        f"(code {column_field}): the table is {table_name.strip()!r}. Pass "
        f"column_field={column_field!r}.",
        f"column_field {label!r} ne nomme pas la seule répartition en colonnes de ce tableau "
        f"(code {column_field}) : le tableau est {table_name.strip()!r}. Passez "
        f"column_field={column_field!r}.",
        lang,
    )


def _parse_default_filters(model: dict[str, Any]) -> dict[str, str]:
    """HMIP's own default filters, from the resolved table model's "AppliedFilters".

    Confirmed live 2026-11-09: [{"Key": "dwelling_type_desc_en", "Value": "Row /
    Apartment"}, {"Key": "season", "Value": "October"}] for Edmonton's historical
    average rents, [{"Key": "dimension-18", "Value": "All"}] for its starts. The
    export applies these when the POST names no filter: Edmonton's 2025 total average
    rent came back as $1,493 (row and apartment combined), not the $1,464 of
    apartments only, and nothing in the table's name said so.
    """
    defaults: dict[str, str] = {}
    for entry in model.get("AppliedFilters") or []:
        if isinstance(entry, dict) and entry.get("Key") and entry.get("Value") is not None:
            defaults[str(entry["Key"])] = str(entry["Value"])
    return defaults


def _filter_notes(
    applied: dict[str, str], defaults: set[str], available: list[FilterOption], lang: str
) -> list[str]:
    """One line per filter dimension: the value applied, where it came from, the others."""
    notes: list[str] = []
    for option in available:
        value = applied.get(option.key)
        name = f"{option.label} ({option.key})" if option.label else option.key
        other_values = [v for v in option.values if v != value]
        others = ", ".join(other_values)
        example = f'filters={{"{option.key}": "{(other_values or option.values)[0]}"}}'
        if value is None:
            notes.append(
                _text(
                    f"{name}: no value applied; values: {', '.join(option.values)}.",
                    f"{name} : aucune valeur appliquée ; valeurs : {', '.join(option.values)}.",
                    lang,
                )
            )
        elif option.key in defaults:
            notes.append(
                _text(
                    f"{name}: {value} (CMHC's default, as filters did not set it). Other "
                    f"values: {others}; pass e.g. {example}.",
                    f"{name} : {value} (valeur par défaut de la SCHL, filters ne la fixant "
                    f"pas). Autres valeurs : {others} ; passez par ex. {example}.",
                    lang,
                )
            )
        else:
            notes.append(
                _text(
                    f"{name}: {value} (from filters). Other values: {others}.",
                    f"{name} : {value} (selon filters). Autres valeurs : {others}.",
                    lang,
                )
            )
    return notes


# Categories whose monthly values are flows (counts during the month), which add up to
# a year or a year to date. Compared with _norm(). Not here, and so never summed:
# Starts (SAAR) (an annual rate), Under Construction Inventory and the inventory of
# completed and unabsorbed units (stocks at month end), prices, lengths, percentages,
# and every rental-market table (rates, rents, universe counts).
_FLOW_CATEGORIES = frozenset(
    {
        ("new housing construction", "starts actual"),
        ("new housing construction", "completions"),
        ("new housing construction", "absorbed units homeowner condo"),
        ("marche du neuf", "mises en chantier d habitations donnees reelles"),
        ("marche du neuf", "achevements"),
        ("marche du neuf", "logements ecoules pour proprietaires absolues ou en copropriete"),
    }
)

# A monthly period as an HMIP time series writes it, by its _norm() month: "Jan 1990"
# in English and "janv. 1990", "févr. 1990", "août 1990" in French (live 2026-11-09,
# Edmonton starts 1.2.1 and completions 1.2.2).
_MONTH_ABBREVIATIONS = {
    **{_norm(name): number for name, number in _MONTHS.items()},
    **{
        name: number
        for number, names in enumerate(
            (
                ("jan", "janv"),
                ("feb", "fev", "fevr"),
                ("mar",),
                ("apr", "avr"),
                ("may",),
                ("jun",),
                ("jul", "juil"),
                ("aug",),
                ("sep", "sept"),
                ("oct",),
                ("nov",),
                ("dec",),
            ),
            start=1,
        )
        for name in names
    },
}
_MONTHLY_PERIOD_RE = re.compile(r"^(?P<month>[a-z]+) (?P<year>\d{4})$")
_MONTH_NAMES = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "fr": (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ),
}


def _monthly_period(period: str) -> tuple[int, int] | None:
    """(year, month) of a monthly time-series period, or None."""
    match = _MONTHLY_PERIOD_RE.match(_norm(period))
    if match is None:
        return None
    month = _MONTH_ABBREVIATIONS.get(match.group("month"))
    return (int(match.group("year")), month) if month else None


def _sum_cells(cells: list[TableCell]) -> TableCell:
    """The total of a column's monthly cells; unknown when any month is not a number."""
    missing = [cell for cell in cells if cell.value is None]
    if missing:
        return TableCell(value=None, flag=missing[0].flag or "**")
    return TableCell(value=sum(cell.value or 0.0 for cell in cells))


def _aggregate_rows(
    rows: list[TableDataRow],
    columns: list[str],
    aggregate: Literal["annual", "ytd"],
    lang: str,
) -> tuple[list[TableDataRow], str]:
    """Sum monthly flow rows into calendar years or year-to-date windows.

    Annual totals cover the years with all 12 months; "ytd" sums January to the
    latest month in the table, for every year with those months, so years compare
    like for like. Checked live 2026-11-09 against HMIP's own Frequency=Annual export
    of Edmonton starts (1.2.1): the annual sums match it for every year from 1990.
    """
    by_year: dict[int, dict[int, TableDataRow]] = {}
    for row in rows:
        year, month = _monthly_period(row.period) or (0, 0)
        by_year.setdefault(year, {})[month] = row
    latest_year = max(by_year)
    last_month = 12 if aggregate == "annual" else max(by_year[latest_year])
    months = range(1, last_month + 1)
    complete = [y for y in sorted(by_year) if all(m in by_year[y] for m in months)]
    left_out = [y for y in sorted(by_year) if y not in complete]

    names = _MONTH_NAMES["fr" if lang == "fr" else "en"]
    window = _text(
        f"{names[0]} to {names[last_month - 1]}",
        f"{names[0]} à {names[last_month - 1]}",
        lang,
    )
    summed: list[TableDataRow] = []
    for year in complete:
        label = str(year) if aggregate == "annual" else f"{window} {year}"
        values = {
            column: _sum_cells([by_year[year][m].values[column] for m in months])
            for column in columns
        }
        summed.append(TableDataRow(period=label, values=values))

    kind = _text(
        "Annual totals" if aggregate == "annual" else f"Year-to-date totals ({window})",
        "Totaux annuels" if aggregate == "annual" else f"Cumuls annuels ({window})",
        lang,
    )
    note = _text(
        f"{kind} summed by MapleStats from CMHC's monthly values; CMHC did not publish "
        "these rows in this form.",
        f"{kind} additionnés par MapleStats à partir des valeurs mensuelles de la SCHL ; la "
        "SCHL n'a pas publié ces lignes sous cette forme.",
        lang,
    )
    if left_out:
        years = ", ".join(str(y) for y in left_out)
        if aggregate == "annual":
            note += _text(
                f" Left out as incomplete: {years} (aggregate='ytd' covers the latest year).",
                f" Années incomplètes exclues : {years} (aggregate='ytd' couvre la dernière "
                "année).",
                lang,
            )
        else:
            note += _text(
                f" Left out as incomplete: {years}.",
                f" Années incomplètes exclues : {years}.",
                lang,
            )
    return summed, note


def _check_aggregate(
    aggregate: str | None,
    category_level_1: str,
    category_level_2: str,
    row_field: str,
    lang: str,
) -> None:
    """Refuse an aggregation of anything but a monthly flow time series."""
    if aggregate is None:
        return
    if aggregate not in ("annual", "ytd"):
        _raise(
            InvalidInput,
            f"aggregate must be 'annual' or 'ytd', got {aggregate!r}.",
            f"aggregate doit valoir 'annual' ou 'ytd' ; reçu {aggregate!r}.",
            lang,
        )
    if (_norm(category_level_1), _norm(category_level_2)) not in _FLOW_CATEGORIES:
        _raise(
            InvalidInput,
            "aggregate sums monthly flows only (New Housing Construction: Starts (Actual), "
            f"Completions, Absorbed Units); {category_level_2!r} is a stock, rate, price or "
            "survey value that must not be summed. Leave aggregate unset.",
            "aggregate n'additionne que des flux mensuels (Marché du neuf : mises en "
            "chantier (données réelles), achèvements, logements écoulés) ; "
            f"{category_level_2!r} est un stock, un taux, un prix ou une valeur d'enquête "
            "qui ne s'additionne pas. Laissez aggregate vide.",
            lang,
        )
    if row_field != "TIMESERIES":
        _raise(
            InvalidInput,
            "aggregate needs a monthly time series: pass row_field='TIMESERIES' "
            "(Historical Time Periods).",
            "aggregate demande une série chronologique mensuelle : passez "
            "row_field='TIMESERIES' (Données chronologiques).",
            lang,
        )


async def get_table_data(
    category_level_1: str,
    category_level_2: str,
    column_field: str,
    row_field: str,
    *,
    geography_type: str = "Country",
    geography_id: str = "1",
    filters: dict[str, str] | None = None,
    aggregate: Literal["annual", "ytd"] | None = None,
    lang: str = "en",
) -> TableDataResult:
    """One HMIP table as rows; `aggregate` sums a monthly flow series (`_aggregate_rows`)."""
    category_level_1 = _require(category_level_1, "category_level_1", lang)
    category_level_2 = _require(category_level_2, "category_level_2", lang)
    column_field = _require(column_field, "column_field", lang)
    row_field = _require(row_field, "row_field", lang)
    geography_type = _require(geography_type, "geography_type", lang)
    geography_id = _require(geography_id, "geography_id", lang)
    geography_type, geography_id = await _resolve_geography(geography_type, geography_id, lang)
    column_field, row_field, column_label = await _resolve_fields(
        category_level_1,
        category_level_2,
        column_field,
        row_field,
        geography_type=geography_type,
        geography_id=geography_id,
        lang=lang,
    )
    _check_aggregate(aggregate, category_level_1, category_level_2, row_field, lang)
    filters = filters or {}
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
    cache_key = f"cmhc:table_data:{lang}:{sorted(match_params.items())}:{sorted(filters.items())}"

    async def fetch() -> dict[str, Any]:
        body = await _get_html(match_url, match_params, lang)
        model = _extract_table_model(body, lang)
        table_id = model.get("TableId")
        geography_type_id = model.get("GeographyTypeId")
        if not table_id or geography_type_id is None:
            _raise(
                NotFound,
                f"HMIP resolved no TableId for category ({category_level_1!r}, "
                f"{category_level_2!r}) with column_field={column_field!r}, "
                f"row_field={row_field!r}.",
                f"le PIMH n'a trouvé aucun TableId pour la catégorie ({category_level_1!r}, "
                f"{category_level_2!r}) avec column_field={column_field!r}, "
                f"row_field={row_field!r}.",
                lang,
            )
        available_filters = _parse_available_filters(model)
        _validate_filters(
            filters,
            available_filters,
            f"get_table_data({category_level_1!r}, {category_level_2!r})",
            lang,
        )
        export_params: dict[str, Any] = {
            "TableId": str(table_id),
            "GeographyId": geography_id,
            "GeographyTypeId": str(geography_type_id),
            "exportType": "csv",
        }
        for i, (key, value) in enumerate(filters.items()):
            export_params[f"AppliedFilters[{i}].Key"] = key
            export_params[f"AppliedFilters[{i}].Value"] = value
        raw_csv = await _post_csv(export_url, export_params, lang)
        text = raw_csv.decode(constants.CSV_ENCODING)
        # sic: CMHC's own JSON key is "GeograghyName" - see module docstring.
        geography_name = model.get("GeograghyName") or ""
        columns, rows, notes = _parse_csv_export(
            text, lang, total_label=geography_name or _text("Total", "Total", lang)
        )
        return {
            "table_id": str(table_id),
            "table_name": model.get("TableName") or "",
            "geography_name": geography_name,
            # The line under the title (the parser above checked it exists): the
            # reference period, then any filters.
            "subtitle": text.splitlines()[1],
            "columns": columns,
            "rows": rows,
            "notes": notes,
            "available_filters": available_filters,
            "default_filters": _parse_default_filters(model),
            "export_params": export_params,
        }

    parsed, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_TABLE_DATA_SECONDS, fetch
    )
    _check_column_label(column_label, parsed["table_name"], column_field, lang)
    reference_period, as_of = _reference_period(parsed.get("subtitle") or "")
    available_filters: list[FilterOption] = parsed["available_filters"]
    available_keys = {f.key for f in available_filters}
    defaults = {
        key: value
        for key, value in (parsed.get("default_filters") or {}).items()
        if key not in filters and (key in available_keys or not available_keys)
    }
    applied_filters = {**defaults, **filters}

    rows: list[TableDataRow] = parsed["rows"]
    aggregation_note: str | None = None
    if aggregate is not None:
        not_monthly = [row.period for row in rows if _monthly_period(row.period) is None]
        if not_monthly or not rows:
            _raise(
                InvalidInput,
                f"aggregate needs monthly rows; this table's periods include "
                f"{not_monthly[:3]!r}. Leave aggregate unset.",
                f"aggregate demande des lignes mensuelles ; les périodes de ce tableau "
                f"comprennent {not_monthly[:3]!r}. Laissez aggregate vide.",
                lang,
            )
        rows, aggregation_note = _aggregate_rows(rows, parsed["columns"], aggregate, lang)

    return TableDataResult(
        table_id=parsed["table_id"],
        table_name=parsed["table_name"],
        geography_name=parsed["geography_name"],
        reference_period=reference_period,
        citation=_citation(
            parsed["table_id"],
            parsed["table_name"],
            parsed["geography_name"],
            reference_period,
            lang,
        ),
        category_level_1=category_level_1,
        category_level_2=category_level_2,
        column_field=column_field,
        row_field=row_field,
        columns=parsed["columns"],
        rows=rows,
        notes=parsed["notes"],
        available_filters=available_filters,
        applied_filters=applied_filters,
        default_filters=defaults,
        filter_notes=_filter_notes(applied_filters, set(defaults), available_filters, lang),
        aggregate=aggregate,
        aggregation_note=aggregation_note,
        flag_legend=_flag_legend(rows, lang),
        provenance=make_provenance(
            source="cmhc",
            url=export_url,
            cached=was_cached,
            schema_name="cmhc.TableDataResult",
            as_of=as_of,
            coverage=aggregation_note,
            # The export is a form POST, so a URL alone cannot reproduce it;
            # the table is resolved first by a GET to TableMatchingCriteria.
            limits=_text(
                f"Request: GET {match_url}?{urlencode(match_params)} to resolve the table, "
                f"then POST {export_url} with form fields "
                f"{urlencode(parsed.get('export_params') or {})}.",
                f"Requête : GET {match_url}?{urlencode(match_params)} pour trouver le tableau, "
                f"puis POST {export_url} avec les champs de formulaire "
                f"{urlencode(parsed.get('export_params') or {})}.",
                lang,
            ),
            lang=lang,
        ),
    )
