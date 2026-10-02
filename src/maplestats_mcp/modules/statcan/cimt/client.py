"""HTTP client for StatCan's Canadian International Merchandise Trade (CIMT) API.

Undocumented web-application API; see constants.py for how it was found,
the quirks confirmed live, and the reconciliation with WDS. Two kinds of
requests go to www150.statcan.gc.ca: the JSON trade methods under
/t1/cimt/rest/ (which need the application's Referer header), and the
static JavaScript code lists next to the application page (commodities,
partners, units), which are parsed here and cached for a week.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from maplestats_mcp.modules.statcan.cimt import constants
from maplestats_mcp.modules.statcan.cimt.schemas import (
    CimtPeriods,
    CommodityMatch,
    CommoditySearchResult,
    PartnerMatch,
    PartnerSearchResult,
    ProvinceBreakdownResult,
    RankedItem,
    SeriesPoint,
    SeriesResult,
    TopCommoditiesResult,
    TopPartnersResult,
    TradeResult,
    TradeRow,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_CAVEAT = (
    "Undocumented StatCan web-application API (found in the CIMT page's JavaScript); "
    "its methods and code lists may change without notice."
)
_UNIT_NOTE = "Values are Canadian dollars at current prices; quantities use the commodity's unit."

_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])(?:-01)?$")
_DIGITS = re.compile(r"^\d+$")

# One object per `{ ... }` in the code-list files; they are JavaScript array
# literals with trailing commas, so json.loads cannot read them.
_OBJECT = re.compile(r"\{[^{}]*\}")
_FIELD = re.compile(r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+)')

_NO_STATE = constants.ALL_STATES_ID
_WORLD_NAME = {"en": "All countries", "fr": "Tous les pays"}
_CANADA_NAME = {"en": "Canada", "fr": "Canada"}
_ALL_STATES_NAME = {"en": "All states", "fr": "Tous les États"}
_US_ALIASES = {"united states", "usa", "us", "etats unis", "etats unis d amerique"}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_lang(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be one of ('en', 'fr'), got {lang!r}.")
    return lang


def _validate_direction(direction: str) -> str:
    if direction not in constants.TRADE_TYPE:
        raise InvalidInput(f"direction must be 'exports' or 'imports', got {direction!r}.")
    return direction


def _validate_limit(limit: int, maximum: int) -> int:
    if limit < 1 or limit > maximum:
        raise InvalidInput(f"limit must be between 1 and {maximum}, got {limit}.")
    return limit


def _parse_period(value: str, name: str) -> str:
    """'2026-07' or '2026-07-01' -> '2026-07-01'. The service only knows whole months."""
    match = _PERIOD.match(value.strip())
    if not match:
        raise InvalidInput(
            f"{name} must be a month as YYYY-MM (for example 2026-07), got {value!r}."
        )
    return f"{match.group(1)}-{match.group(2)}-01"


def _clean_hs(value: str, *, allow_empty: bool = True) -> str:
    code = value.replace(".", "").replace(" ", "").strip()
    if not code:
        if allow_empty:
            return ""
        raise InvalidInput("hs_code is required.")
    if not _DIGITS.match(code):
        raise InvalidInput(f"hs_code must be digits only, got {value!r}.")
    # A one-digit code or an odd length is a 406 upstream (confirmed live).
    if len(code) not in (2, 4, 6, 8, 10):
        raise InvalidInput(
            f"hs_code must have 2 (chapter), 4 (heading), 6, 8 or 10 digits, got {len(code)}."
        )
    return code


def _clean_chapter(value: str) -> str:
    chapter = value.strip()
    if not chapter:
        return ""
    if chapter.isdigit() and len(chapter) == 1:
        chapter = f"0{chapter}"
    if not re.match(r"^\d{2}$", chapter):
        raise InvalidInput(f"hs_chapter must be a 2-digit HS chapter such as '27', got {value!r}.")
    return chapter


def _fold(text: str) -> str:
    """Lower-case, accent-free text for matching names ('Québec' == 'quebec')."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[\s\-–_]+", " ", stripped.casefold()).strip()


def _unit_code(code: str) -> str | None:
    """The code lists use "BLANK" (or nothing) for goods with no quantity unit."""
    return None if code in ("", "BLANK") else code


def _month(code: str) -> str | None:
    """'200201' -> '2002-01'; the open-ended '999912' -> None."""
    if len(code) != 6 or code == "999912" or not code.isdigit():
        return None
    return f"{code[:4]}-{code[4:]}"


# ---------------------------------------------------------------------------
# Upstream access
# ---------------------------------------------------------------------------


def _map_http_error(context: str, exc: httpx.HTTPStatusError) -> Exception:
    status = exc.response.status_code
    if status == 406:
        return InvalidInput(
            f"{context}: the CIMT service rejected the parameters (HTTP 406). "
            "Check the HS code length and the partner and province codes."
        )
    if status == 404:
        return UpstreamError(
            f"{context}: HTTP 404. The CIMT service answers 404 when it no longer accepts "
            "the application's Referer header or has moved; the API is undocumented and "
            "may have changed."
        )
    return UpstreamError(f"{context} returned HTTP {status}.")


async def _get_json(context: str, url: str, referer: str) -> Any:
    await _LIMITER.acquire()
    try:
        return await api_get(url, headers={"Referer": referer})
    except httpx.HTTPStatusError as exc:
        raise _map_http_error(context, exc) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). "
            "Try again shortly."
        ) from exc


async def _call(path: str, direction: str, ttl: int) -> tuple[Any, bool, str]:
    """GET one CIMT method; returns (json, was_cached, url)."""
    url = f"{constants.BASE_URL}/{path}"
    referer = constants.REFERER_BY_DIRECTION[direction]

    async def fetch() -> Any:
        return await _get_json(f"statcan_cimt:{path.split('/', 1)[0]}", url, referer)

    body, was_cached = await cached_fetch(f"statcan-cimt:{url}", ttl, fetch)
    return body, was_cached, url


def _provenance(
    schema: str,
    url: str,
    *,
    cached: bool,
    latest: str | None = None,
    limits: str | None = None,
) -> Provenance:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"statcan_cimt.{schema}",
        as_of=datetime.fromisoformat(latest).replace(tzinfo=UTC) if latest else None,
        freshness="monthly, 1988-01 onward",
        coverage=f"{_CAVEAT} {_UNIT_NOTE}",
        limits=limits,
    )


async def get_periods() -> CimtPeriods:
    body, was_cached, url = await _call(
        "getPeriods", "exports", constants.CACHE_TTL_PERIODS_SECONDS
    )
    try:
        first, latest = str(body["start"]), str(body["current"])
    except (KeyError, TypeError) as exc:
        raise UpstreamError("getPeriods did not return start and current months.") from exc
    return CimtPeriods(
        first_period=first[:7],
        latest_period=latest[:7],
        provenance=_provenance("CimtPeriods", url, cached=was_cached, latest=latest),
    )


async def _bounds() -> tuple[str, str]:
    periods = await get_periods()
    return f"{periods.first_period}-01", f"{periods.latest_period}-01"


async def _check_in_range(*periods: tuple[str, str]) -> None:
    """Reject months the service has not published; it answers HTTP 500 for them."""
    first, latest = await _bounds()
    for name, value in periods:
        if value < first or value > latest:
            raise InvalidInput(
                f"{name} {value[:7]} is outside the published range {first[:7]} to {latest[:7]}."
            )


async def _resolve_period(period: str) -> str:
    if not period.strip():
        return (await _bounds())[1]
    value = _parse_period(period, "period")
    await _check_in_range(("period", value))
    return value


# ---------------------------------------------------------------------------
# Code lists (static JavaScript files next to the application page)
# ---------------------------------------------------------------------------


def _parse_objects(text: str) -> list[dict[str, str | int]]:
    objects: list[dict[str, str | int]] = []
    for match in _OBJECT.finditer(text):
        fields: dict[str, str | int] = {}
        for key, raw in _FIELD.findall(match.group(0)):
            fields[key] = raw[1:-1] if raw.startswith('"') else int(raw)
        if fields:
            objects.append(fields)
    return objects


async def _fetch_list(name: str) -> list[dict[str, str | int]]:
    url = f"{constants.CODES_BASE_URL}/{name}.js"
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=constants.CODES_TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            f"statcan_cimt: code list {name}.js returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"statcan_cimt: code list {name}.js did not respond.") from exc
    # The files start with a byte-order mark.
    objects = _parse_objects(response.content.decode("utf-8-sig"))
    if not objects:
        raise UpstreamError(
            f"statcan_cimt: code list {name}.js held no entries; the format may have changed."
        )
    return objects


async def _code_list(name: str) -> list[dict[str, str | int]]:
    async def fetch() -> Any:
        return await _fetch_list(name)

    body, _ = await cached_fetch(
        f"statcan-cimt:codes:{name}", constants.CACHE_TTL_CODES_SECONDS, fetch
    )
    return body


# A commodity is (code, unit code, English, French, valid from, valid to).
type Commodity = tuple[str, str, str, str, str, str]


async def _commodities(level: str, direction: str) -> list[Commodity]:
    """The commodity list for a level; the HS8 and HS10 lists are national (Canadian) detail."""
    if level == "chapter":
        name = "chaptersF"
    elif level == "heading":
        name = "hs4F"
    elif level == "hs6":
        # The export and import pages load different HS6 lists (hs6F_X and hs6F).
        name = "hs6F_X" if direction == "exports" else "hs6F"
    else:
        name = "hs8F" if direction == "exports" else "hs10F"

    async def build() -> Any:
        entries = await _code_list(name)
        return [
            (
                str(e.get("HS", "")),
                str(e.get("UOM", "")),
                str(e.get("EN", "")),
                str(e.get("FR", "")),
                str(e.get("C_START", "")),
                str(e.get("C_END", "")),
            )
            for e in entries
        ]

    body, _ = await cached_fetch(
        f"statcan-cimt:commodities:{name}", constants.CACHE_TTL_CODES_SECONDS, build
    )
    return body


async def _description_lookup(level: str, direction: str, lang: str) -> dict[str, tuple[str, str]]:
    """code -> (description, unit code). Empty on failure: a name is not worth losing the data."""
    try:
        entries = await _commodities(level, direction)
    except (UpstreamError, UpstreamUnavailable):
        return {}
    index = 2 if lang == "en" else 3
    return {e[0]: (e[index], e[1]) for e in entries}


async def _unit_labels(lang: str) -> dict[str, str]:
    try:
        entries = await _code_list("uom")
    except (UpstreamError, UpstreamUnavailable):
        return {}
    key = "en" if lang == "en" else "fr"
    return {str(e["id"]): str(e.get(key, "")) for e in entries if "id" in e}


async def _countries() -> list[dict[str, str | int]]:
    return await _code_list("countriesF")


def _unique_by_id(entries: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    """countriesF.js repeats some ids (Virgin Islands, United States appears twice)."""
    return list({int(e["id"]): e for e in entries}.values())


async def _states() -> list[dict[str, str | int]]:
    return await _code_list("states_codr")


async def _provinces() -> list[dict[str, str | int]]:
    return await _code_list("provinces")


def _country_name(entry: dict[str, str | int], lang: str) -> str:
    return str(entry.get(lang, entry.get("en", "")))


def _province_name(entry: dict[str, str | int], lang: str) -> str:
    # provinces.js writes French names with en dashes (Terre–Neuve–et–Labrador).
    return str(entry.get(lang, "")).replace("–", "-")


def _state_name(entry: dict[str, str | int], lang: str) -> str:
    return str(entry.get(f"label_{lang}", entry.get("label_en", "")))


# ---------------------------------------------------------------------------
# Resolving the caller's partner and province arguments to CIMT identifiers
# ---------------------------------------------------------------------------


def _pick(
    value: str,
    kind: str,
    candidates: list[tuple[int, list[str]]],
    names: dict[int, str],
) -> int:
    """Find the one candidate whose id, code or name equals (or uniquely contains) value."""
    needle = _fold(value)
    if value.strip().isdigit() and int(value) in names:
        return int(value)
    # The list has no plain "United States" (it is "United States of America"), and
    # Virgin Islands appears twice, so a name alone would be ambiguous.
    if kind == "country" and needle in _US_ALIASES:
        return constants.US_ID
    exact = list(
        dict.fromkeys(cid for cid, labels in candidates if needle in {_fold(x) for x in labels})
    )
    if len(exact) == 1:
        return exact[0]
    partial = list(
        dict.fromkeys(cid for cid, labels in candidates if any(needle in _fold(x) for x in labels))
    )
    if len(exact) == 0 and len(partial) == 1:
        return partial[0]
    options = exact or partial
    if not options:
        raise NotFound(f"No {kind} matches {value!r}. Search with cimt_search_partners.")
    shown = ", ".join(f"{names[c]} ({c})" for c in options[:6])
    raise InvalidInput(f"{kind} {value!r} is ambiguous: {shown}. Pass the numeric code.")


async def _resolve_country(partner: str, lang: str) -> tuple[int, str]:
    if not partner.strip() or _fold(partner) in {"world", "all", "all countries", "monde"}:
        return constants.WORLD_ID, _WORLD_NAME[lang]
    entries = await _countries()
    names = {int(e["id"]): _country_name(e, lang) for e in entries}
    candidates = [
        (int(e["id"]), [str(e.get("c_code", "")), str(e.get("en", "")), str(e.get("fr", ""))])
        for e in entries
    ]
    code = _pick(partner, "country", candidates, names)
    return code, names[code]


async def _resolve_state(us_state: str, lang: str) -> tuple[int, str]:
    if not us_state.strip():
        return _NO_STATE, _ALL_STATES_NAME[lang]
    entries = await _states()
    names = {int(e["id"]): _state_name(e, lang) for e in entries}
    candidates = [
        (int(e["id"]), [str(e.get("label_en", "")), str(e.get("label_fr", ""))]) for e in entries
    ]
    code = _pick(us_state, "US state", candidates, names)
    return code, names[code]


async def _resolve_province(province: str, lang: str) -> tuple[int, str]:
    if not province.strip() or _fold(province) in {"canada", "all"}:
        return constants.CANADA_ID, _CANADA_NAME[lang]
    entries = await _provinces()
    names = {int(e["id"]): _province_name(e, lang) for e in entries}
    abbreviation = constants.PROVINCE_ABBREVIATIONS.get(province.strip().upper())
    if abbreviation is not None:
        return abbreviation, names[abbreviation]
    candidates = [(int(e["id"]), [str(e.get("en", "")), str(e.get("fr", ""))]) for e in entries]
    code = _pick(province, "province", candidates, names)
    return code, names[code]


async def _resolve_partner_pair(
    partner: str, us_state: str, lang: str
) -> tuple[int, str, int, str]:
    """Country and US state ids. A state implies the United States."""
    country_id, country_name = await _resolve_country(partner, lang)
    state_id, state_name = await _resolve_state(us_state, lang)
    if state_id != _NO_STATE:
        if not partner.strip():
            country_id, country_name = await _resolve_country("US", lang)
        if country_id != constants.US_ID:
            raise InvalidInput("us_state can only be used with the United States as partner.")
    return country_id, country_name, state_id, state_name


# ---------------------------------------------------------------------------
# Searching code lists
# ---------------------------------------------------------------------------


def _matches(query: str, haystack: str) -> bool:
    return all(token in haystack for token in _fold(query).split())


async def search_commodities(
    query: str = "",
    *,
    direction: str = "exports",
    level: str = "hs6",
    lang: str = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> CommoditySearchResult:
    """Search HS commodity codes by code prefix or by words in either language."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    _validate_limit(limit, constants.SEARCH_LIMIT_MAX)
    if level not in ("chapter", "heading", "hs6", "national"):
        raise InvalidInput(f"level must be chapter, heading, hs6 or national, got {level!r}.")

    entries = await _commodities(level, direction)
    units = await _unit_labels(lang)
    text_index = 2 if lang == "en" else 3
    needle = query.strip().replace(".", "")
    by_code = bool(needle) and needle.isdigit()
    found = [
        e
        for e in entries
        if not needle
        or (e[0].startswith(needle) if by_code else _matches(needle, _fold(f"{e[2]} {e[3]}")))
    ]
    # An exact code first, then codes still in use before retired ones, then code order.
    found.sort(key=lambda e: (e[0] != needle, _month(e[5]) is not None, e[0]))
    matches = [
        CommodityMatch(
            code=e[0],
            level=level,
            description=e[text_index],
            unit_code=_unit_code(e[1]),
            unit=units.get(e[1]) or None,
            valid_from=_month(e[4]),
            valid_to=_month(e[5]),
        )
        for e in found[:limit]
    ]
    return CommoditySearchResult(
        query=query,
        direction=direction,
        level=level,
        commodities=matches,
        returned_count=len(matches),
        total_matched=len(found),
        provenance=_provenance(
            "CommoditySearchResult",
            f"{constants.CODES_BASE_URL}/{'exp' if direction == 'exports' else 'imp'}-eng.htm",
            cached=True,
            limits=f"Showing up to {limit} of {len(found)} matching codes.",
        ),
    )


async def search_partners(
    query: str = "",
    *,
    kind: str = "country",
    lang: str = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> PartnerSearchResult:
    """Search trading-partner countries, US states or Canadian provinces by name or code."""
    lang = _validate_lang(lang)
    _validate_limit(limit, constants.SEARCH_LIMIT_MAX)
    if kind not in ("country", "us_state", "province"):
        raise InvalidInput(f"kind must be country, us_state or province, got {kind!r}.")

    rows: list[PartnerMatch] = []
    if kind == "country":
        rows.append(PartnerMatch(kind=kind, code=constants.WORLD_ID, name=_WORLD_NAME[lang]))
        for e in _unique_by_id(await _countries()):
            rows.append(
                PartnerMatch(
                    kind=kind,
                    code=int(e["id"]),
                    iso_code=str(e.get("c_code", "")) or None,
                    name=_country_name(e, lang),
                    valid_from=_month(str(e.get("c_start", ""))),
                    valid_to=_month(str(e.get("c_end", ""))),
                )
            )
    elif kind == "us_state":
        for e in await _states():
            rows.append(PartnerMatch(kind=kind, code=int(e["id"]), name=_state_name(e, lang)))
    else:
        rows.append(PartnerMatch(kind=kind, code=constants.CANADA_ID, name=_CANADA_NAME[lang]))
        abbreviations = {v: k for k, v in constants.PROVINCE_ABBREVIATIONS.items()}
        for e in await _provinces():
            rows.append(
                PartnerMatch(
                    kind=kind,
                    code=int(e["id"]),
                    iso_code=abbreviations.get(int(e["id"])),
                    name=_province_name(e, lang),
                )
            )

    needle = _fold(query)
    found = [
        r
        for r in rows
        if not needle
        or needle == str(r.code)
        or needle == _fold(r.iso_code or "")
        or _matches(query, _fold(f"{r.name} {r.iso_code or ''}"))
    ]
    # An exact id or code ("AB", "553") ahead of names that merely contain it.
    found.sort(key=lambda r: not (needle and needle in (str(r.code), _fold(r.iso_code or ""))))
    shown = found[:limit]
    return PartnerSearchResult(
        query=query,
        kind=kind,
        partners=shown,
        returned_count=len(shown),
        total_matched=len(found),
        provenance=_provenance(
            "PartnerSearchResult",
            f"{constants.CODES_BASE_URL}/countriesF.js",
            cached=True,
            limits=f"Showing up to {limit} of {len(found)} matches.",
        ),
    )


# ---------------------------------------------------------------------------
# Trade data
# ---------------------------------------------------------------------------


def _check_hs_for_level(hs_code: str, hs_level: str, direction: str) -> None:
    if hs_level not in ("hs6", "national"):
        raise InvalidInput(f"hs_level must be 'hs6' or 'national', got {hs_level!r}.")
    # The service matches a code by prefix only at the level the flag selects;
    # a longer code returns no rows (confirmed live), so say so up front.
    longest = 6 if hs_level == "hs6" else (8 if direction == "exports" else 10)
    if len(hs_code) > longest:
        hint = "pass hs_level='national'" if hs_level == "hs6" else "use a shorter code"
        raise InvalidInput(
            f"A {len(hs_code)}-digit code does not match at hs_level={hs_level!r} for "
            f"{direction}: {hint}."
        )


def _province_path(province_ids: list[int]) -> str:
    return f"({','.join(str(i) for i in province_ids)})"


async def get_trade(
    direction: str,
    from_period: str,
    to_period: str,
    *,
    hs_code: str = "",
    partner: str = "",
    us_state: str = "",
    provinces: list[str] | None = None,
    hs_level: str = "hs6",
    annualize: bool = False,
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> TradeResult:
    """Merchandise trade rows by month (or calendar year), commodity, partner and province."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    _validate_limit(limit, constants.ROWS_MAX)
    hs = _clean_hs(hs_code)
    _check_hs_for_level(hs, hs_level, direction)
    start = _parse_period(from_period, "from_period")
    end = _parse_period(to_period, "to_period")
    if start > end:
        raise InvalidInput(f"from_period {start[:7]} is after to_period {end[:7]}.")
    await _check_in_range(("from_period", start), ("to_period", end))

    country_id, _, state_id, _ = await _resolve_partner_pair(partner, us_state, lang)
    province_ids = [(await _resolve_province(p, lang))[0] for p in (provinces or [])]
    # (1, 35) returns Canada only (confirmed live), so a list with 1 is just Canada.
    if constants.CANADA_ID in province_ids or not province_ids:
        province_ids = [constants.CANADA_ID]
    province_ids = sorted(set(province_ids))

    path = "/".join(
        [
            "getReport",
            _province_path(province_ids),
            str(country_id),
            str(state_id),
            hs or "0",
            "1" if hs_level == "hs6" else "0",
            str(limit),
            str(constants.TRADE_TYPE[direction]),
            "1" if annualize else "0",
            start,
            end,
        ]
    )
    body, was_cached, url = await _call(path, direction, constants.CACHE_TTL_DATA_SECONDS)
    raw_rows = list_or_empty(body, "trade")
    total = int(body.get("count") or len(raw_rows))

    descriptions = await _description_lookup(
        "hs6" if hs_level == "hs6" else "national", direction, lang
    )
    units = await _unit_labels(lang)
    countries = {int(e["id"]): _country_name(e, lang) for e in await _countries()}
    states = {int(e["id"]): _state_name(e, lang) for e in await _states()}
    province_names = {int(e["id"]): _province_name(e, lang) for e in await _provinces()}
    province_names[constants.CANADA_ID] = _CANADA_NAME[lang]
    countries[constants.WORLD_ID] = _WORLD_NAME[lang]

    rows: list[TradeRow] = []
    for r in raw_rows:
        code = str(r["H"])
        description, unit_code = descriptions.get(code, (None, ""))
        state = int(r["S"])
        rows.append(
            TradeRow(
                period=str(r["T"])[:4] if annualize else str(r["T"])[:7],
                hs_code=code,
                hs_description=description,
                partner_code=int(r["C"]),
                partner=countries.get(int(r["C"]), str(r["C"])),
                us_state_code=None if state == _NO_STATE else state,
                us_state=None if state == _NO_STATE else states.get(state, str(state)),
                province_code=int(r["P"]),
                province=province_names.get(int(r["P"]), str(r["P"])),
                value_cad=float(r["V"]),
                quantity=float(r["Q"]) if r.get("Q") is not None else None,
                unit_code=_unit_code(unit_code),
                unit=units.get(unit_code) or None,
            )
        )
    rows.sort(key=lambda row: (row.period, -row.value_cad))
    truncated = total > len(rows)
    return TradeResult(
        direction=direction,
        hs_level=hs_level,
        annualized=annualize,
        from_period=start[:7],
        to_period=end[:7],
        rows=rows,
        returned_count=len(rows),
        total_count=total,
        truncated=truncated,
        returned_value_cad=sum(row.value_cad for row in rows),
        provenance=_provenance(
            "TradeResult",
            url,
            cached=was_cached,
            latest=end,
            limits=(
                f"Row limit {limit}; the query matches {total} rows, so the rows returned are "
                "an arbitrary subset. Narrow the commodity, partner, province or period."
                if truncated
                else f"Row limit {limit}; not reached."
            ),
        ),
    )


def _ranked(
    items: list[dict[str, Any]],
    key: str,
    names: Callable[[str], str],
    total: float | None,
) -> list[RankedItem]:
    ranked: list[RankedItem] = []
    for position, item in enumerate(items, start=1):
        value = float(item["V"])
        code = str(item[key])
        ranked.append(
            RankedItem(
                rank=position,
                code=code,
                name=names(code),
                value_cad=value,
                share_of_total=value / total if total else None,
            )
        )
    return ranked


async def get_top_partners(
    direction: str,
    *,
    period: str = "",
    hs_chapter: str = "",
    province: str = "",
    view: str = "country",
    lang: str = "en",
) -> TopPartnersResult:
    """The 15 largest partners (countries, or US states) for one month."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    if view not in ("country", "us_state"):
        raise InvalidInput(f"view must be 'country' or 'us_state', got {view!r}.")
    chapter = _clean_chapter(hs_chapter)
    refper = await _resolve_period(period)
    province_id, province_name = await _resolve_province(province, lang)

    country_id = constants.WORLD_ID if view == "country" else constants.US_ID
    path = "/".join(
        [
            "getTopPartners",
            refper,
            str(province_id),
            str(country_id),
            str(_NO_STATE),
            chapter or "0",
            "0" if view == "country" else "1",
            str(constants.TRADE_TYPE[direction]),
        ]
    )
    body, was_cached, url = await _call(path, direction, constants.CACHE_TTL_DATA_SECONDS)
    countries = {str(e["id"]): _country_name(e, lang) for e in await _countries()}
    states = {str(e["id"]): _state_name(e, lang) for e in await _states()}
    lookup = countries if view == "country" else states
    total = float(body.get("total") or 0)
    items = _ranked(list_or_empty(body, "trade"), "C", lambda c: lookup.get(c, c), total)
    return TopPartnersResult(
        direction=direction,
        period=refper[:7],
        view=view,
        hs_chapter=chapter or None,
        province=province_name,
        total_value_cad=total,
        partners=items,
        returned_count=len(items),
        provenance=_provenance(
            "TopPartnersResult",
            url,
            cached=was_cached,
            latest=refper,
            limits="The service returns its 15 largest partners only.",
        ),
    )


async def get_top_commodities(
    direction: str,
    *,
    period: str = "",
    hs_chapter: str = "",
    province: str = "",
    partner: str = "",
    us_state: str = "",
    hs_level: str = "hs6",
    lang: str = "en",
) -> TopCommoditiesResult:
    """The largest commodities for one month, optionally within a chapter, partner or province."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    if hs_level not in ("hs6", "national"):
        raise InvalidInput(f"hs_level must be 'hs6' or 'national', got {hs_level!r}.")
    chapter = _clean_chapter(hs_chapter)
    refper = await _resolve_period(period)
    province_id, province_name = await _resolve_province(province, lang)
    country_id, country_name, state_id, state_name = await _resolve_partner_pair(
        partner, us_state, lang
    )

    path = "/".join(
        [
            "getTopCommodities",
            refper,
            str(province_id),
            str(country_id),
            str(state_id),
            chapter or "0",
            "1" if hs_level == "hs6" else "0",
            str(constants.TRADE_TYPE[direction]),
        ]
    )
    body, was_cached, url = await _call(path, direction, constants.CACHE_TTL_DATA_SECONDS)
    descriptions = await _description_lookup(
        "hs6" if hs_level == "hs6" else "national", direction, lang
    )
    items = _ranked(
        list_or_empty(body, "trade"), "H", lambda c: descriptions.get(c, (c, ""))[0], None
    )
    # Shares need the total of every commodity, which the service does not send.
    return TopCommoditiesResult(
        direction=direction,
        period=refper[:7],
        hs_level=hs_level,
        hs_chapter=chapter or None,
        province=province_name,
        partner=state_name if state_id != _NO_STATE else country_name,
        commodities=items,
        returned_count=len(items),
        provenance=_provenance(
            "TopCommoditiesResult",
            url,
            cached=was_cached,
            latest=refper,
            limits="The service returns its largest commodities only (about 25).",
        ),
    )


async def get_province_breakdown(
    direction: str,
    *,
    period: str = "",
    hs_chapter: str = "",
    partner: str = "",
    us_state: str = "",
    lang: str = "en",
) -> ProvinceBreakdownResult:
    """Trade by province for one month. Exports: province of origin. Imports: of clearance."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    chapter = _clean_chapter(hs_chapter)
    refper = await _resolve_period(period)
    country_id, country_name, state_id, state_name = await _resolve_partner_pair(
        partner, us_state, lang
    )

    path = "/".join(
        [
            "getProvinces",
            refper,
            str(country_id),
            str(state_id),
            chapter or "0",
            str(constants.TRADE_TYPE[direction]),
        ]
    )
    body, was_cached, url = await _call(path, direction, constants.CACHE_TTL_DATA_SECONDS)
    names = {str(e["id"]): _province_name(e, lang) for e in await _provinces()}
    domestic = float(body.get("domestic") or 0)
    reexports = float(body.get("reexports") or 0)
    items = _ranked(
        list_or_empty(body, "trade"), "P", lambda c: names.get(c, c), domestic + reexports
    )
    return ProvinceBreakdownResult(
        direction=direction,
        period=refper[:7],
        partner=state_name if state_id != _NO_STATE else country_name,
        hs_chapter=chapter or None,
        domestic_value_cad=domestic,
        reexport_value_cad=reexports,
        provinces=items,
        returned_count=len(items),
        provenance=_provenance(
            "ProvinceBreakdownResult",
            url,
            cached=was_cached,
            latest=refper,
            limits="Province values are exports domestic plus re-exports shipped from the province.",
        ),
    )


async def get_series(
    direction: str,
    hs_code: str,
    *,
    period: str = "",
    partner: str = "",
    us_state: str = "",
    province: str = "",
    lang: str = "en",
) -> SeriesResult:
    """A five-year monthly series ending at `period`, for a chapter or one commodity."""
    lang = _validate_lang(lang)
    direction = _validate_direction(direction)
    hs = _clean_hs(hs_code, allow_empty=False)
    if len(hs) == 4:
        raise InvalidInput(
            "hs_code must be a 2-digit chapter or a 6-, 8- or 10-digit commodity; "
            "the service has no 4-digit series."
        )
    refper = await _resolve_period(period)
    province_id, province_name = await _resolve_province(province, lang)
    country_id, country_name, state_id, state_name = await _resolve_partner_pair(
        partner, us_state, lang
    )

    if len(hs) == 2:
        method = "getChapterChart"
    else:
        method = "getCommodityChart"
    path = "/".join(
        [
            method,
            refper,
            str(province_id),
            str(country_id),
            str(state_id),
            hs,
            str(constants.TRADE_TYPE[direction]),
        ]
    )
    body, was_cached, url = await _call(path, direction, constants.CACHE_TTL_DATA_SECONDS)
    measures = constants.ESTIMATE_MEASURES[direction]
    points: list[SeriesPoint] = []
    for item in list_or_empty(body, "chart"):
        if method == "getChapterChart":
            points.append(
                SeriesPoint(period=str(item["T"])[:7], measure="value", value=float(item["V"]))
            )
        else:
            flag = int(item["E"])
            points.append(
                SeriesPoint(
                    period=str(item["R"])[:7],
                    measure=measures.get(flag, f"estimate_{flag}"),
                    value=float(item["V"]),
                )
            )
    points.sort(key=lambda p: (p.period, p.measure))
    unit: str | None = None
    if method == "getCommodityChart":
        level = "hs6" if len(hs) == 6 else "national"
        _, unit_code = (await _description_lookup(level, direction, lang)).get(hs, (None, ""))
        unit = (await _unit_labels(lang)).get(unit_code) if unit_code else None
    return SeriesResult(
        direction=direction,
        hs_code=hs,
        partner=state_name if state_id != _NO_STATE else country_name,
        province=province_name,
        from_period=points[0].period if points else refper[:7],
        to_period=points[-1].period if points else refper[:7],
        unit=unit,
        points=points,
        returned_count=len(points),
        provenance=_provenance(
            "SeriesResult",
            url,
            cached=was_cached,
            latest=refper,
            limits=(
                "Five years of months ending at the requested period. Exports: total exports "
                "are domestic_value plus reexport_value."
                if direction == "exports" and method == "getCommodityChart"
                else "Five years of months ending at the requested period."
            ),
        ),
    )
