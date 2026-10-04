"""Client for Transport Canada's vehicle recall API.

Responses are lists of name/value pairs, flattened by `_values`/`_named`.
Search columns are labelled in the request language ("Recall number" /
"Numéro de rappel"), so rows are read by position, confirmed stable in
both languages; summary fields use fixed database names.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from maplestats_mcp.modules.tc_recalls import constants
from maplestats_mcp.modules.tc_recalls.schemas import (
    AffectedVehicle,
    RecallDetail,
    RecallRow,
    RecallSearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.validation import check_range

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_NAME = re.compile(r"^[\w .&'-]{1,60}$")


def _root(lang: str) -> str:
    return constants.BASE_URL.format(lang="fra" if lang == "fr" else "eng")


async def _get(url: str, params: dict[str, Any] | None = None) -> tuple[list[list[Any]], bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"tc_recalls: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"tc_recalls: {url} could not be reached.") from exc

    body, cached = await cached_fetch(
        f"tc-recalls:{url}:{sorted((params or {}).items())}", constants.CACHE_TTL_SECONDS, fetch
    )
    rows = body.get("ResultSet") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise UpstreamError("tc_recalls: response has no ResultSet.")
    return rows, cached


def _values(row: list[dict[str, Any]]) -> list[Any]:
    return [(field.get("Value") or {}).get("Literal") for field in row]


def _named(row: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(field.get("Name")): (field.get("Value") or {}).get("Literal") for field in row}


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        month, day, year = str(value).split(" ")[0].split("/")
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _segment(value: str, name: str) -> str:
    value = value.strip()
    if not _NAME.match(value):
        raise InvalidInput(f"{name} contains unsupported characters: {value!r}.")
    return quote(value.lower())


def _row(row: list[dict[str, Any]]) -> RecallRow:
    values = _values(row) + [None] * 6
    return RecallRow(
        recall_number=str(values[0]),
        manufacturer=values[1],
        model=values[2],
        make=values[3],
        model_year=_int(values[4]),
        recall_date=_date(values[5]),
    )


async def _count(url: str) -> int:
    """`<search path>/count` answers one row, "Result Count" (confirmed live 2026-10-03)."""
    rows, _ = await _get(f"{url}/count")
    values = _values(rows[0]) if rows else []
    return _int(values[0]) or 0 if values else 0


async def search(
    *,
    make: str | None = None,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    page: int = 1,
    lang: str = "en",
) -> RecallSearchResult:
    """Recalls matching the filters, newest first.

    The API lists oldest first with page/limit paging and has no sort
    parameter, so the total comes from the `/count` endpoint and the
    newest-first page is cut from the (at most two) upstream pages that
    hold it.
    """
    if not (make or model or year_from or year_to):
        raise InvalidInput("Give at least a make, a model, or a model-year range.")
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")
    if page < 1:
        raise InvalidInput(f"page must be >= 1, got {page}.")
    path = "recall"
    if make:
        path += f"/make-name/{_segment(make, 'make')}"
    if model:
        path += f"/model-name/{_segment(model, 'model')}"
    if year_from or year_to:
        first, last = year_from or year_to, year_to or year_from
        if first is None or last is None or first < 1900 or last > 2100:
            raise InvalidInput(f"Invalid model-year range {year_from}-{year_to}.")
        check_range(first, last, "year_from", "year_to")
        path += f"/year-range/{first}-{last}"
    url = _root(lang) + path
    total = await _count(url)
    # An unknown make answers an empty list; tell it apart from a known make
    # with no recalls for this model or these years.
    narrowed = bool(model or year_from or year_to)
    make_url = _root(lang) + f"recall/make-name/{_segment(make, 'make')}" if make else None
    if total == 0 and make_url and (not narrowed or await _count(make_url) == 0):
        raise InvalidInput(
            f"No recall at all lists make {make!r}; check the spelling (makes are "
            "matched as written, e.g. 'Honda', 'Mercedes-Benz')."
        )
    # Newest-first rows [low, high) are, oldest first, [total - high, total - low).
    low, high = (page - 1) * limit, page * limit
    first_index, stop_index = max(total - high, 0), max(total - low, 0)
    rows: list[RecallRow] = []
    cached = True
    if stop_index > first_index:
        first_page = first_index // limit + 1
        last_page = (stop_index - 1) // limit + 1
        fetched: list[RecallRow] = []
        for upstream_page in range(first_page, last_page + 1):
            part, part_cached = await _get(url, {"limit": limit, "page": upstream_page})
            cached = cached and part_cached
            fetched.extend(_row(r) for r in part)
        offset = (first_page - 1) * limit
        rows = fetched[first_index - offset : stop_index - offset][::-1]
    has_more = high < total
    note = (
        "No recall matched; check the make and model spelling (matched as written)."
        if total == 0
        else (
            f"Newest first: recalls {low + 1} to {low + len(rows)} of {total:,}; next page "
            f"is page={page + 1}."
            if has_more
            else None
        )
    )
    return RecallSearchResult(
        recalls=rows,
        returned_count=len(rows),
        total_count=total,
        has_more=has_more,
        page=page,
        limit=limit,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="tc_recalls.RecallSearchResult",
            limits=join_limits(
                f"Request: GET {url}/count, then GET {url}?limit={limit}&page=N for the "
                "upstream pages holding these rows (the API lists oldest first)",
                note,
            ),
        ),
    )


async def get_recall(recall_number: str, lang: str = "en") -> RecallDetail:
    number = recall_number.strip()
    if not number.isdigit():
        raise InvalidInput(f"recall_number must be digits like '2021001', got {recall_number!r}.")
    url = _root(lang) + f"recall-summary/recall-number/{number}"
    raw, cached = await _get(url)
    rows = [_named(r) for r in raw]
    if not rows:
        raise NotFound(f"No Transport Canada recall {number}.")
    first = rows[0]
    suffix = "FTXT" if lang == "fr" else "ETXT"
    vehicles = {
        (r.get("MAKE_NAME_NM"), r.get("MODEL_NAME_NM"), _int(r.get("DATE_YEAR_CD"))) for r in rows
    }
    return RecallDetail(
        recall_number=number,
        manufacturer_recall_number=first.get("MANUFACTURER_RECALL_NO_TXT"),
        recall_date=_date(first.get("RECALL_DATE_DTE")),
        category=first.get(f"CATEGORY_{suffix}"),
        system=first.get(f"SYSTEM_TYPE_{suffix}"),
        notification_type=first.get(f"NOTIFICATION_TYPE_{suffix}"),
        units_affected=_int(first.get("UNIT_AFFECTED_NBR")),
        description=(first.get(f"COMMENT_{suffix}") or "").strip() or None,
        affected_vehicles=[
            AffectedVehicle(make=m, model=mo, model_year=y)
            for m, mo, y in sorted(vehicles, key=lambda v: (str(v[0]), str(v[1]), v[2] or 0))
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="tc_recalls.RecallDetail",
        ),
    )
