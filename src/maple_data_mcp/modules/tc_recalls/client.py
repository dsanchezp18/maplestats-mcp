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

from maple_data_mcp.modules.tc_recalls import constants
from maple_data_mcp.modules.tc_recalls.schemas import (
    AffectedVehicle,
    RecallDetail,
    RecallRow,
    RecallSearchResult,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_NAME = re.compile(r"^[\w .&'-]{1,60}$")


def _root(lang: str) -> str:
    return constants.BASE_URL.format(lang="fra" if lang == "fr" else "eng")


async def _get(url: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"tc_recalls: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"tc_recalls: {url} did not respond in time.") from exc

    body, _ = await cached_fetch(
        f"tc-recalls:{url}:{sorted((params or {}).items())}", constants.CACHE_TTL_SECONDS, fetch
    )
    rows = body.get("ResultSet") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise UpstreamError("tc_recalls: response has no ResultSet.")
    return rows


def _values(row: list[dict[str, Any]]) -> list[Any]:
    return [(field.get("Value") or {}).get("Literal") for field in row]


def _named(row: list[dict[str, Any]]) -> dict[str, Any]:
    return {field.get("Name"): (field.get("Value") or {}).get("Literal") for field in row}


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
        start, end = year_from or year_to, year_to or year_from
        if start is None or end is None or start > end or start < 1900 or end > 2100:
            raise InvalidInput(f"Invalid model-year range {year_from}-{year_to}.")
        path += f"/year-range/{start}-{end}"
    url = _root(lang) + path
    rows = await _get(url, {"limit": limit, "page": page})
    recalls = []
    for row in rows:
        values = _values(row) + [None] * 6
        recalls.append(
            RecallRow(
                recall_number=str(values[0]),
                manufacturer=values[1],
                model=values[2],
                make=values[3],
                model_year=_int(values[4]),
                recall_date=_date(values[5]),
            )
        )
    return RecallSearchResult(
        recalls=recalls,
        returned_count=len(recalls),
        page=page,
        limit=limit,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="tc_recalls.RecallSearchResult",
            limits="results are oldest first; narrow with a model-year range or page",
        ),
    )


async def get_recall(recall_number: str, lang: str = "en") -> RecallDetail:
    number = recall_number.strip()
    if not number.isdigit():
        raise InvalidInput(f"recall_number must be digits like '2021001', got {recall_number!r}.")
    url = _root(lang) + f"recall-summary/recall-number/{number}"
    rows = [_named(r) for r in await _get(url)]
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
            cached=False,
            schema_name="tc_recalls.RecallDetail",
        ),
    )
