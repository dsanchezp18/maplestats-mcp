"""HTTP client for the Alberta Economic Dashboard data API.

See constants.py for the routes and quirks confirmed live. Table names
are checked against the live table list before use, so a caller-supplied
name can never reach a URL path unvalidated.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, NoReturn

import httpx

from maple_data_mcp.modules.ab_economic import constants
from maple_data_mcp.modules.ab_economic.schemas import (
    ColumnInfo,
    Indicator,
    IndicatorList,
    TableData,
    TableFields,
    TableInfo,
    TableList,
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
_PID = re.compile(r"_(\d{8,10})$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _raise_for(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = exc.response.text[:200].strip()
    if status == 404:
        raise NotFound(f"{context}: not found.") from exc
    if status == 400:
        raise InvalidInput(f"{context}: {detail or 'rejected the request'}.") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    await _LIMITER.acquire()
    context = f"ab_economic:{path.split('?')[0]}"
    try:
        return await api_get(f"{constants.BASE_URL}/{path}", params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{context} did not respond in time. Try again shortly.") from exc


async def _table_names() -> tuple[list[str], bool]:
    async def fetch() -> Any:
        return await _get("api/chart-editor/data-tables")

    raw, cached = await cached_fetch(
        "ab-economic:tables", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    return [t["tableName"] for t in raw if t.get("tableName")], cached


async def _resolve_table(table: str) -> str:
    names, _ = await _table_names()
    by_lower = {n.lower(): n for n in names}
    match = by_lower.get(table.strip().lower())
    if match is None:
        raise NotFound(
            f"No Alberta Economic Dashboard table {table!r}. Use ab_economic_list_tables."
        )
    return match


def _pid(table: str) -> str | None:
    found = _PID.search(table)
    return found.group(1) if found else None


async def list_tables(query: str | None = None) -> TableList:
    names, cached = await _table_names()
    needle = (query or "").strip().lower()
    matches = [n for n in names if not needle or needle in n.lower() or needle == _pid(n)]
    return TableList(
        tables=[TableInfo(table=n, statcan_pid=_pid(n)) for n in matches],
        total_count=len(matches),
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/api/chart-editor/data-tables",
            cached=cached,
            schema_name="ab_economic.TableList",
            freshness="table list cached 24h",
        ),
    )


async def get_table_fields(table: str) -> TableFields:
    name = await _resolve_table(table)

    async def fetch_fields() -> Any:
        return await _get(f"api/chart-editor/field-info/{name}")

    async def fetch_info() -> Any:
        return await _get(f"api/chart-editor/indicator-info/{name}")

    fields, cached = await cached_fetch(
        f"ab-economic:fields:{name}", constants.CACHE_TTL_FIELDS_SECONDS, fetch_fields
    )
    info, _ = await cached_fetch(
        f"ab-economic:info:{name}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch_info
    )
    columns = []
    for col in fields:
        values = [str(v) for v in col.get("values") or []]
        columns.append(
            ColumnInfo(
                name=col["columnName"],
                data_type=col.get("dataType") or "unknown",
                distinct_count=len(values),
                values=values[: constants.FIELD_VALUES_MAX],
                values_truncated=len(values) > constants.FIELD_VALUES_MAX,
            )
        )
    info = info if isinstance(info, dict) else {}
    return TableFields(
        table=name,
        # Upstream misspells this key.
        indicator_name=info.get("indicaorName") or info.get("indicatorName"),
        period=info.get("period"),
        columns=columns,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/api/chart-editor/field-info/{name}",
            cached=cached,
            schema_name="ab_economic.TableFields",
        ),
    )


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


def _row_date(row: dict[str, Any]) -> datetime | None:
    raw = row.get("Date")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def get_data(
    table: str,
    filters: dict[str, str] | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
) -> TableData:
    """Rows of one table, filtered upstream by column values.

    Date bounds are inclusive and applied client-side; the most recent
    `limit` matching rows are returned, oldest first.
    """
    if limit < 1 or limit > constants.ROWS_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.")
    filters = dict(filters or {})
    for column in filters:
        if not _COLUMN.match(column):
            raise InvalidInput(f"Filter column {column!r} is not a valid column name.")
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start and end and start > end:
        raise InvalidInput(f"start_date {start} is after end_date {end}.")
    name = await _resolve_table(table)
    params = {"table": name, **filters}

    async def fetch() -> Any:
        return await _get("data", params)

    rows, cached = await cached_fetch(
        f"ab-economic:data:{sorted(params.items())}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )
    if not isinstance(rows, list):
        raise UpstreamError(f"ab_economic:data returned {type(rows).__name__}, expected a list.")

    def in_range(row: dict[str, Any]) -> bool:
        when = _row_date(row)
        if when is None:
            return not (start or end)
        return (not start or when.date() >= start) and (not end or when.date() <= end)

    matching = sorted((r for r in rows if in_range(r)), key=lambda r: str(r.get("Date") or ""))
    kept = matching[-limit:]
    dates = [d for r in kept if (d := _row_date(r))]
    return TableData(
        table=name,
        filters=filters,
        rows=kept,
        total_rows=len(matching),
        returned_count=len(kept),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/data?table={name}",
            cached=cached,
            schema_name="ab_economic.TableData",
            coverage=f"{len(kept)} most recent of {len(matching)} matching rows",
            limits=f"at most {constants.ROWS_MAX} rows per call; filter to one series",
        ),
    )


async def list_indicators() -> IndicatorList:
    async def fetch() -> Any:
        return await _get(f"api/tile-data/dashboard/{constants.KEY_INDICATORS_CODE}")

    body, cached = await cached_fetch(
        "ab-economic:indicators", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    topics = body.get("data") or []
    indicators = [
        Indicator(
            name=ind["name"],
            topic=topic["name"],
            updated_at=datetime.fromisoformat(ind["updatedAt"]) if ind.get("updatedAt") else None,
        )
        for topic in topics
        for ind in topic.get("indicators") or []
    ]
    return IndicatorList(
        indicators=indicators,
        topics=[t["name"] for t in topics],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.DASHBOARD_URL,
            cached=cached,
            schema_name="ab_economic.IndicatorList",
            freshness="catalogue cached 24h",
        ),
    )
