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
- `lang="fr"` sends every request to the Bank's French domain
  (constants.BASE_URL_FR), which returns French labels, descriptions and
  error messages with the same JSON shapes. French responses are cached
  under their own keys so the two languages never mix.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Any, NoReturn, Protocol
from urllib.parse import quote

import httpx

from maplestats_mcp.modules.boc import constants
from maplestats_mcp.modules.boc.schemas import (
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
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import NBSP, french_spacing
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.limits import fit_to_budget, truncation_note
from maplestats_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _error(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> ValueError:
    """The error to raise: English as before, French through the shared typed template.

    Returned rather than raised so a caller can chain it (`raise ... from exc`).
    """
    if lang != "fr":
        return exc_cls(en)
    try:
        raise_typed(exc_cls, fr, "fr")
    except ValueError as err:
        return err


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise _error(exc_cls, en, fr, lang)


def _base(lang: str) -> str:
    """Valet's French domain answers in French; read at call time so tests can patch it."""
    return constants.BASE_URL_FR if lang == "fr" else constants.BASE_URL


def _cache_key(key: str, lang: str) -> str:
    """English keys stay as they were; French responses get their own entries."""
    return key.replace("boc:", "boc:fr:", 1) if lang == "fr" else key


def _fr_count(n: int) -> str:
    """French thousands separator is a (no-break) space, not a comma."""
    return f"{n:,}".replace(",", NBSP)


def _error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return ""
    return body.get("message", "") if isinstance(body, dict) else ""


def _raise_for_status(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    # On the French domain Valet's own message is already French.
    message = _error_message(exc)
    if status == 404:
        raise _error(
            NotFound,
            message or f"{context}: not found.",
            message or f"{context} : introuvable.",
            lang,
        ) from exc
    if status == 400:
        raise _error(
            InvalidInput,
            message or f"{context}: rejected the request (HTTP 400).",
            message or f"{context} : requête refusée (HTTP 400).",
            lang,
        ) from exc
    raise _error(
        UpstreamError,
        f"{context}: upstream returned HTTP {status}: {message}",
        f"{context} : la source a renvoyé le code HTTP {status} : {message}",
        lang,
    ) from exc


async def _get(path: str, params: dict[str, Any] | None = None, lang: str = "en") -> Any:
    await _limiter().acquire()
    url = f"{_base(lang)}{path}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, path, lang)
    except httpx.HTTPError as exc:
        raise _error(
            UpstreamUnavailable,
            f"{path} did not respond in time (already retried by shared/http.py).",
            f"{path} n'a pas répondu à temps (déjà relancé par shared/http.py).",
            lang,
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


_KIND_FR = {"Series": "Le nom de la série", "Group": "Le nom du groupe"}


def _require_name(name: str, kind: str, lang: str = "en") -> str:
    name = name.strip()
    if not name:
        _raise(
            InvalidInput,
            f"{kind} name must not be empty.",
            f"{_KIND_FR.get(kind, kind)} ne doit pas être vide.",
            lang,
        )
    return name


def _path_segment(name: str) -> str:
    """Percent-encode a name before splicing it into a URL path.

    Query params are encoded automatically by httpx, but series/group
    names go directly into the path (e.g. observations/{name}/json),
    which is not — a name containing '/', '?', or '#' would otherwise
    produce a malformed or unintended request instead of a clean 404.
    """
    return quote(name, safe="")


def _observation_params(
    *,
    start_date: str | None,
    end_date: str | None,
    recent: int | None,
    recent_weeks: int | None,
    recent_months: int | None,
    recent_years: int | None,
    lang: str = "en",
) -> dict[str, Any]:
    has_range = start_date is not None or end_date is not None
    has_recent = any(v is not None for v in (recent, recent_weeks, recent_months, recent_years))
    if has_range and has_recent:
        # Mirrors Valet's own HTTP 400 message for this combination
        # (confirmed live), caught here instead of round-tripping.
        _raise(
            InvalidInput,
            "Cannot mix start_date/end_date with recent/recent_weeks/recent_months/recent_years.",
            "start_date/end_date ne peuvent pas être combinés avec "
            "recent/recent_weeks/recent_months/recent_years.",
            lang,
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


def _latest_date(observations: list[Observation]) -> datetime | None:
    """The newest observation date, as provenance as_of."""
    if not observations:
        return None
    return datetime.combine(max(o.ref_date for o in observations), time(), tzinfo=UTC)


def _series_info_from_json(series_detail: dict[str, Any]) -> dict[str, SeriesInfoBrief]:
    return {
        code: SeriesInfoBrief(
            name=code,
            label=obj.get("label", ""),
            description=obj.get("description", ""),
        )
        for code, obj in series_detail.items()
    }


class _NamedEntry(Protocol):
    """Structural shape shared by SeriesSummary and GroupSummary.

    Lets list_series/list_groups and search_series/search_groups share
    one cached-inventory-fetch and one substring-filter implementation
    instead of two near-identical copies.
    """

    name: str
    label: str
    description: str


async def _cached_inventory[Entry: _NamedEntry](
    cache_key: str,
    path: str,
    container_key: str,
    item_type: Callable[..., Entry],
    lang: str = "en",
) -> tuple[list[Entry], bool]:
    """Fetch+parse `path` once per TTL window, caching the parsed models
    themselves (not the raw JSON) - list_series/list_groups return
    15k+/2.5k+ entries that would otherwise be re-validated on every
    call, cache hit or not."""

    async def fetch() -> list[Entry]:
        obj = await _get(path, lang=lang)
        return [
            item_type(name=code, label=e.get("label", ""), description=e.get("description", ""))
            for code, e in obj[container_key].items()
        ]

    return await cached_fetch(_cache_key(cache_key, lang), constants.CACHE_TTL_LISTS_SECONDS, fetch)


def _filter_inventory[Entry: _NamedEntry](items: list[Entry], query: str) -> list[Entry]:
    needle = query.lower()
    return [
        item
        for item in items
        if needle in item.name.lower()
        or needle in item.label.lower()
        or needle in item.description.lower()
    ]


def _check_limit(limit: int, maximum: int, lang: str = "en") -> None:
    if not 1 <= limit <= maximum:
        _raise(
            InvalidInput,
            f"limit must be between 1 and {maximum}, got {limit}.",
            f"limit doit être compris entre 1 et {maximum} ; valeur reçue : {limit}.",
            lang,
        )


def _url(path: str, params: dict[str, Any] | None = None, lang: str = "en") -> str:
    """The request URL with its query string, so provenance reproduces the call."""
    return str(httpx.URL(f"{_base(lang)}{path}", params=params or None))


def _keep_latest(observations: list[Observation]) -> list[Observation]:
    """Valet lists oldest first; when the byte budget cuts, keep the newest dates."""
    kept = fit_to_budget(observations[::-1], constants.OBSERVATIONS_MAX_BYTES)
    return kept[::-1]


def _observation_limits(returned: int, total: int, lang: str = "en") -> str | None:
    if lang == "fr":
        if returned >= total:
            return None
        return french_spacing(
            f"Seules les {_fr_count(returned)} dates d'observation les plus récentes sur "
            f"{_fr_count(total)} sont renvoyées ; passez start_date/end_date ou recent_* "
            "pour choisir la période."
        )
    return truncation_note(
        returned=returned,
        total=total,
        unit="observation dates",
        order="latest",
        how_to_get_more="pass start_date/end_date or recent_* to choose the window",
    )


def _fr_cut(returned: int, total: int, kind: str, *, matching: bool) -> str:
    """French "only the first N of M ..." with the agreement each noun needs
    (séries is feminine, groupes masculine)."""
    if kind == "series":
        extra = " correspondantes" if matching else ""
        return (
            f"Seules les {_fr_count(returned)} premières séries{extra} sur "
            f"{_fr_count(total)} sont renvoyées"
        )
    extra = " correspondants" if matching else ""
    return (
        f"Seuls les {_fr_count(returned)} premiers groupes{extra} sur "
        f"{_fr_count(total)} sont renvoyés"
    )


def _search_limits(returned: int, total: int, kind: str, lang: str) -> str | None:
    """The cut a keyword search made; `kind` is "series" or "groups"."""
    if lang == "fr":
        if returned >= total:
            return None
        return french_spacing(
            f"{_fr_cut(returned, total, kind, matching=True)} ; précisez la requête ou "
            f"augmentez limit (max. {constants.SEARCH_LIMIT_MAX})."
        )
    return truncation_note(
        returned=returned,
        total=total,
        unit=f"matching {kind}",
        how_to_get_more=f"refine the query or raise limit (max {constants.SEARCH_LIMIT_MAX})",
    )


def _page_limits(returned: int, total: int, kind: str, lang: str) -> str | None:
    """The cut a no-query listing made; `kind` is "series" or "groups"."""
    if lang == "fr":
        if returned >= total:
            return None
        return french_spacing(
            f"{_fr_cut(returned, total, kind, matching=False)} ; cherchez avec query ou "
            f"augmentez limit (max. {constants.LIST_LIMIT_MAX})."
        )
    return truncation_note(
        returned=returned,
        total=total,
        unit=kind,
        how_to_get_more=f"search with query, or raise limit (max {constants.LIST_LIMIT_MAX})",
    )


def _search_coverage(count: int, kind: str, lang: str) -> str:
    if lang == "fr":
        what = "séries" if kind == "series" else "groupes"
        return french_spacing(
            f"recherche de sous-chaîne parmi {_fr_count(count)} {what} "
            "(libellés et descriptions en français de la Banque du Canada)"
        )
    return f"substring search over {count} {kind}"


async def list_series(lang: str = "en") -> SeriesList:
    series, was_cached = await _cached_inventory(
        "boc:lists/series", "lists/series/json", "series", SeriesSummary, lang
    )
    return SeriesList(
        series=series,
        total_count=len(series),
        provenance=make_provenance(
            source="boc",
            url=f"{_base(lang)}lists/series/json",
            cached=was_cached,
            schema_name="boc.SeriesList",
            lang=lang,
        ),
    )


async def search_series(
    query: str, *, limit: int = constants.SEARCH_LIMIT_DEFAULT, lang: str = "en"
) -> SeriesList:
    """Client-side substring search over the cached series inventory."""
    _check_limit(limit, constants.SEARCH_LIMIT_MAX, lang)
    all_series = await list_series(lang)
    matches = _filter_inventory(all_series.series, query)
    return SeriesList(
        series=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=_url("lists/series/json", lang=lang),
            cached=all_series.provenance.cached,
            schema_name="boc.SeriesList",
            coverage=_search_coverage(len(all_series.series), "series", lang),
            limits=_search_limits(min(limit, len(matches)), len(matches), "series", lang),
            lang=lang,
        ),
    )


def page_series(result: SeriesList, limit: int, lang: str = "en") -> SeriesList:
    """The first `limit` series of the full inventory, with the cut recorded."""
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)
    series = result.series[:limit]
    note = _page_limits(len(series), len(result.series), "series", lang)
    provenance = result.provenance.model_copy(update={"limits": note})
    return result.model_copy(
        update={"series": series, "total_count": len(result.series), "provenance": provenance}
    )


async def list_groups(lang: str = "en") -> GroupList:
    groups, was_cached = await _cached_inventory(
        "boc:lists/groups", "lists/groups/json", "groups", GroupSummary, lang
    )
    return GroupList(
        groups=groups,
        total_count=len(groups),
        provenance=make_provenance(
            source="boc",
            url=f"{_base(lang)}lists/groups/json",
            cached=was_cached,
            schema_name="boc.GroupList",
            lang=lang,
        ),
    )


async def search_groups(
    query: str, *, limit: int = constants.SEARCH_LIMIT_DEFAULT, lang: str = "en"
) -> GroupList:
    """Client-side substring search over the cached group inventory."""
    _check_limit(limit, constants.SEARCH_LIMIT_MAX, lang)
    all_groups = await list_groups(lang)
    matches = _filter_inventory(all_groups.groups, query)
    return GroupList(
        groups=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=_url("lists/groups/json", lang=lang),
            cached=all_groups.provenance.cached,
            schema_name="boc.GroupList",
            coverage=_search_coverage(len(all_groups.groups), "groups", lang),
            limits=_search_limits(min(limit, len(matches)), len(matches), "groups", lang),
            lang=lang,
        ),
    )


def page_groups(result: GroupList, limit: int, lang: str = "en") -> GroupList:
    """The first `limit` groups of the full inventory, with the cut recorded."""
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)
    groups = result.groups[:limit]
    note = _page_limits(len(groups), len(result.groups), "groups", lang)
    provenance = result.provenance.model_copy(update={"limits": note})
    return result.model_copy(
        update={"groups": groups, "total_count": len(result.groups), "provenance": provenance}
    )


async def get_series(name: str, lang: str = "en") -> SeriesDetail:
    name = _require_name(name, "Series", lang)
    cache_key = _cache_key(f"boc:series/{name}", lang)

    async def fetch() -> dict[str, Any]:
        return await _get(f"series/{_path_segment(name)}/json", lang=lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    detail = obj["seriesDetails"]
    return SeriesDetail(
        name=detail["name"],
        label=detail.get("label", ""),
        description=detail.get("description", ""),
        provenance=make_provenance(
            source="boc",
            url=f"{_base(lang)}series/{name}/json",
            cached=was_cached,
            schema_name="boc.SeriesDetail",
            lang=lang,
        ),
    )


async def get_group(name: str, lang: str = "en") -> GroupDetail:
    name = _require_name(name, "Group", lang)
    cache_key = _cache_key(f"boc:group/{name}", lang)

    async def fetch() -> dict[str, Any]:
        return await _get(f"groups/{_path_segment(name)}/json", lang=lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    detail = obj["groupDetails"]
    members = [
        GroupMemberSeries(name=code, label=e.get("label", ""), link=e.get("link"))
        # `or {}`: an explicit null would otherwise crash .items().
        for code, e in (detail.get("groupSeries") or {}).items()
    ]
    return GroupDetail(
        name=detail["name"],
        label=detail.get("label", ""),
        description=detail.get("description", ""),
        series=members,
        provenance=make_provenance(
            source="boc",
            url=f"{_base(lang)}groups/{name}/json",
            cached=was_cached,
            schema_name="boc.GroupDetail",
            lang=lang,
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
    lang: str = "en",
) -> ObservationsResult:
    if not series_names:
        _raise(
            InvalidInput,
            "series_names must contain at least one series name.",
            "series_names doit contenir au moins un nom de série.",
            lang,
        )
    names = [_require_name(n, "Series", lang) for n in series_names]
    params = _observation_params(
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
        lang=lang,
    )
    joined = ",".join(_path_segment(n) for n in names)
    path = f"observations/{joined}/json"
    cache_key = _cache_key(f"boc:{path}:{sorted(params.items())}", lang)

    async def fetch() -> dict[str, Any]:
        return await _get(path, params=params, lang=lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    observations = _observations_from_json(list_or_empty(obj, "observations"))
    kept = _keep_latest(observations)
    return ObservationsResult(
        series=_series_info_from_json(obj.get("seriesDetail", {}) or {}),
        observations=kept,
        provenance=make_provenance(
            source="boc",
            url=_url(path, params, lang),
            cached=was_cached,
            as_of=_latest_date(observations),
            schema_name="boc.ObservationsResult",
            limits=_observation_limits(len(kept), len(observations), lang),
            lang=lang,
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
    lang: str = "en",
) -> GroupObservationsResult:
    group_name = _require_name(group_name, "Group", lang)
    params = _observation_params(
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
        lang=lang,
    )
    path = f"observations/group/{_path_segment(group_name)}/json"
    cache_key = _cache_key(f"boc:{path}:{sorted(params.items())}", lang)

    async def fetch() -> dict[str, Any]:
        return await _get(path, params=params, lang=lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    group_detail = obj.get("groupDetail", {}) or {}
    observations = _observations_from_json(list_or_empty(obj, "observations"))
    kept = _keep_latest(observations)
    return GroupObservationsResult(
        # "groupDetail" (unlike GroupDetail's "groupDetails") has no
        # "name" field - see this module's docstring and schemas.py's.
        group=GroupInfo(
            name=group_name,
            label=group_detail.get("label", ""),
            description=group_detail.get("description", ""),
            link=group_detail.get("link"),
        ),
        series=_series_info_from_json(obj.get("seriesDetail", {}) or {}),
        observations=kept,
        provenance=make_provenance(
            source="boc",
            url=_url(path, params, lang),
            cached=was_cached,
            as_of=_latest_date(observations),
            schema_name="boc.GroupObservationsResult",
            limits=_observation_limits(len(kept), len(observations), lang),
            lang=lang,
        ),
    )
