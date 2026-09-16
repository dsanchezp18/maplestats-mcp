"""HTTP client for the Bank of Canada Valet API.

Every function wraps `shared.http.api_get` through the boc rate limiter
and either returns a typed model or raises a `shared/errors.py`
exception. The following was confirmed live against
https://www.bankofcanada.ca/valet/ this session (not assumed from
https://www.bankofcanada.ca/valet/docs prose alone):

- `/lists/series/json` -> {"terms", "series": {code: {label,
  description, link}}}. 15,928 entries measured live - large, mostly
  static, so cached for CACHE_TTL_LISTS_SECONDS.
- `/lists/groups/json` -> {"terms", "groups": {code: {label, link,
  description}}}. Same shape/caching story, 2,538 entries.
- `/series/{name}/json` -> {"terms", "seriesDetails": {name, label,
  description}}. 404 for an unknown name, body
  {"message": "Series X not found.", "docs": "..."}.
- `/groups/{name}/json` -> {"terms", "groupDetails": {name, label,
  description, groupSeries: {code: {label, link}}}} - groupSeries
  entries have no description field (confirmed live).
- `/observations/{name1,name2,...}/json` (comma-joined series names in
  one URL, confirmed live) -> {"terms", "seriesDetail": {code: {label,
  description, dimension: {key: "d", name: "Date"}}}, "observations":
  [{"d": "YYYY-MM-DD", code: {"v": "1.234"}, ...}, ...]}.
  * `recent`, `recent_weeks`, `recent_months`, `recent_years`, and the
    `start_date`/`end_date` pair are mutually exclusive - Valet returns
    HTTP 400 with "Bad recent observations request parameters, you can
    not mix start_date or end_date with any of recent, recent_weeks,
    recent_months, recent_years" when both are supplied. Validated
    client-side below to fail fast with the same message.
  * `end_date` before `start_date` also returns HTTP 400 ("The End date
    must be greater than the Start date.").
  * Same-frequency series (e.g. two daily FX rates) are merged into one
    row per date. Series of genuinely different frequencies requested
    together (e.g. a daily FX rate + a monthly CPI series) under
    `recent`/`recent_*` come back as *separate, unmerged rows* - each
    row only carries the series that actually has data for that date.
    schemas.Observation.values is a dict for exactly this reason; do
    not assume every requested series key is present in every row.
  * `v` is always a JSON string, even though every value seen is
    numeric ("1.3917", "169.8") - parsed to float here, with an
    empty/missing value treated as no data rather than a parse error.
- `/observations/group/{name}/json` -> same "observations" shape as
  above, plus "groupDetail" (singular - NOT "groupDetails") holding
  only {label, description, link}, no "name" field at all (confirmed
  live against /observations/group/FX_RATES_DAILY/json). The caller's
  own group_name argument is used to fill GroupInfo.name.
- 404 (unknown series/group name) and 400 (bad date range, mixed
  recent/range params) both return a JSON body shaped
  {"message": str, "docs": str} - surfaced here as NotFound/InvalidInput
  respectively, using Valet's own message text, rather than letting a
  raw HTTPStatusError escape (the StatCan WDS module hit exactly this
  failure mode for 404/406 before it was fixed - see AGENTS.md).
- No numeric rate limit is published, and no X-RateLimit-*/Retry-After
  style header was present on any live response checked this session
  (series/list/observations endpoints) - see constants.py for the
  conservative default used in its place.
"""

from __future__ import annotations

from typing import Any, NoReturn

import httpx

from maple_data_mcp.modules.boc import constants
from maple_data_mcp.modules.boc.schemas import (
    GroupDetail,
    GroupInfo,
    GroupList,
    GroupMemberSeries,
    GroupObservationsResult,
    GroupSummary,
    Observation,
    ObservationsResult,
    SeriesDetail,
    SeriesInfoBrief,
    SeriesList,
    SeriesSummary,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return ""
    return body.get("message", "") if isinstance(body, dict) else ""


def _raise_for_status(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    message = _error_message(exc)
    if status == 404:
        raise NotFound(message or f"{context}: not found.") from exc
    if status == 400:
        raise InvalidInput(message or f"{context}: rejected the request (HTTP 400).") from exc
    raise UpstreamError(f"{context}: upstream returned HTTP {status}: {message}") from exc


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, path)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{path} did not respond in time (already retried by shared/http.py)."
        ) from exc


def _parse_value(raw: str | None) -> float | None:
    """Valet sends "v" as a JSON string even for numeric series; treat a
    missing or empty value as no data rather than a parse failure."""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _require_name(name: str, kind: str) -> str:
    name = name.strip()
    if not name:
        raise InvalidInput(f"{kind} name must not be empty.")
    return name


def _observation_params(
    *,
    start_date: str | None,
    end_date: str | None,
    recent: int | None,
    recent_weeks: int | None,
    recent_months: int | None,
    recent_years: int | None,
) -> dict[str, Any]:
    has_range = start_date is not None or end_date is not None
    has_recent = any(v is not None for v in (recent, recent_weeks, recent_months, recent_years))
    if has_range and has_recent:
        # Mirrors Valet's own HTTP 400 message for this combination
        # (confirmed live), caught here instead of round-tripping.
        raise InvalidInput(
            "Cannot mix start_date/end_date with recent/recent_weeks/recent_months/recent_years."
        )
    params: dict[str, Any] = {}
    if start_date is not None:
        params["start_date"] = start_date
    if end_date is not None:
        params["end_date"] = end_date
    if recent is not None:
        params["recent"] = recent
    if recent_weeks is not None:
        params["recent_weeks"] = recent_weeks
    if recent_months is not None:
        params["recent_months"] = recent_months
    if recent_years is not None:
        params["recent_years"] = recent_years
    return params


def _observations_from_json(rows: list[dict[str, Any]]) -> list[Observation]:
    observations = []
    for row in rows:
        ref_date = row["d"]
        values = {
            code: _parse_value(entry.get("v"))
            for code, entry in row.items()
            if code != "d" and isinstance(entry, dict)
        }
        observations.append(Observation(ref_date=ref_date, values=values))
    return observations


def _series_info_from_json(series_detail: dict[str, Any]) -> dict[str, SeriesInfoBrief]:
    return {
        code: SeriesInfoBrief(
            name=code,
            label=obj.get("label", ""),
            description=obj.get("description", ""),
        )
        for code, obj in series_detail.items()
    }


async def list_series() -> SeriesList:
    cache_key = "boc:lists/series"

    async def fetch() -> dict[str, Any]:
        return await _get("lists/series/json")

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LISTS_SECONDS, fetch)
    series = [
        SeriesSummary(name=code, label=e.get("label", ""), description=e.get("description", ""))
        for code, e in obj["series"].items()
    ]
    return SeriesList(
        series=series,
        total_count=len(series),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}lists/series/json",
            cached=was_cached,
            schema_name="boc.SeriesList",
        ),
    )


async def search_series(query: str, *, limit: int = 25) -> SeriesList:
    """Client-side substring search over the cached series inventory."""
    all_series = await list_series()
    needle = query.lower()
    matches = [
        s
        for s in all_series.series
        if needle in s.name.lower() or needle in s.label.lower() or needle in s.description.lower()
    ][:limit]
    return SeriesList(
        series=matches,
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}lists/series/json",
            cached=all_series.provenance.cached,
            schema_name="boc.SeriesList",
            coverage=f"top {limit} matches of {len(all_series.series)} series searched",
        ),
    )


async def list_groups() -> GroupList:
    cache_key = "boc:lists/groups"

    async def fetch() -> dict[str, Any]:
        return await _get("lists/groups/json")

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LISTS_SECONDS, fetch)
    groups = [
        GroupSummary(name=code, label=e.get("label", ""), description=e.get("description", ""))
        for code, e in obj["groups"].items()
    ]
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}lists/groups/json",
            cached=was_cached,
            schema_name="boc.GroupList",
        ),
    )


async def search_groups(query: str, *, limit: int = 25) -> GroupList:
    """Client-side substring search over the cached group inventory."""
    all_groups = await list_groups()
    needle = query.lower()
    matches = [
        g
        for g in all_groups.groups
        if needle in g.name.lower() or needle in g.label.lower() or needle in g.description.lower()
    ][:limit]
    return GroupList(
        groups=matches,
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}lists/groups/json",
            cached=all_groups.provenance.cached,
            schema_name="boc.GroupList",
            coverage=f"top {limit} matches of {len(all_groups.groups)} groups searched",
        ),
    )


async def get_series(name: str) -> SeriesDetail:
    name = _require_name(name, "Series")
    cache_key = f"boc:series/{name}"

    async def fetch() -> dict[str, Any]:
        return await _get(f"series/{name}/json")

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    detail = obj["seriesDetails"]
    return SeriesDetail(
        name=detail["name"],
        label=detail.get("label", ""),
        description=detail.get("description", ""),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}series/{name}/json",
            cached=was_cached,
            schema_name="boc.SeriesDetail",
        ),
    )


async def get_group(name: str) -> GroupDetail:
    name = _require_name(name, "Group")
    cache_key = f"boc:group/{name}"

    async def fetch() -> dict[str, Any]:
        return await _get(f"groups/{name}/json")

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    detail = obj["groupDetails"]
    members = [
        GroupMemberSeries(name=code, label=e.get("label", ""))
        for code, e in detail.get("groupSeries", {}).items()
    ]
    return GroupDetail(
        name=detail["name"],
        label=detail.get("label", ""),
        description=detail.get("description", ""),
        series=members,
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}groups/{name}/json",
            cached=was_cached,
            schema_name="boc.GroupDetail",
        ),
    )


async def get_observations(
    series_names: list[str],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
) -> ObservationsResult:
    if not series_names:
        raise InvalidInput("series_names must contain at least one series name.")
    names = [_require_name(n, "Series") for n in series_names]
    params = _observation_params(
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
    )
    joined = ",".join(names)
    path = f"observations/{joined}/json"
    cache_key = f"boc:{path}:{sorted(params.items())}"

    async def fetch() -> dict[str, Any]:
        return await _get(path, params=params)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    return ObservationsResult(
        series=_series_info_from_json(obj.get("seriesDetail", {})),
        observations=_observations_from_json(obj.get("observations", [])),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}{path}",
            cached=was_cached,
            schema_name="boc.ObservationsResult",
        ),
    )


async def get_group_observations(
    group_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
) -> GroupObservationsResult:
    group_name = _require_name(group_name, "Group")
    params = _observation_params(
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
    )
    path = f"observations/group/{group_name}/json"
    cache_key = f"boc:{path}:{sorted(params.items())}"

    async def fetch() -> dict[str, Any]:
        return await _get(path, params=params)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    group_detail = obj.get("groupDetail", {})
    return GroupObservationsResult(
        # "groupDetail" (unlike GroupDetail's "groupDetails") has no
        # "name" field - see this module's docstring and schemas.py's.
        group=GroupInfo(
            name=group_name,
            label=group_detail.get("label", ""),
            description=group_detail.get("description", ""),
            link=group_detail.get("link"),
        ),
        series=_series_info_from_json(obj.get("seriesDetail", {})),
        observations=_observations_from_json(obj.get("observations", [])),
        provenance=make_provenance(
            source="boc",
            url=f"{constants.BASE_URL}{path}",
            cached=was_cached,
            schema_name="boc.GroupObservationsResult",
        ),
    )
