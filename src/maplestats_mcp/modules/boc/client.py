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
- `/groups/{name}/json` -> {"terms", "groupDetail": {name, label,
  description, link, metadata, groupSeries: {code: {label, description,
  dateFormat, link}}}}. Until October 2026 the key was "groupDetails"
  (plural) and groupSeries entries had no description; both keys are
  accepted.
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
  above, plus "groupDetail" holding only {label, description, link},
  no "name" field at all (confirmed
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

import math
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time
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
from maplestats_mcp.shared.transform import (
    PERIODS_PER_YEAR,
    TransformedSeries,
    TransformRequest,
    extra_months,
    infer_periods_per_year,
    is_rate_unit,
    parse_period,
    shift_months,
    transform_series,
)


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


def _shape_error(where: str, field: str, lang: str = "en") -> ValueError:
    """An UpstreamError naming the field a 200 payload lacks.

    A changed Valet payload would otherwise surface as a bare KeyError, which
    is not a ValueError and so bypasses the typed-error mapping.
    """
    return _error(
        UpstreamError,
        f"{where}: the Valet response has no usable {field!r} field; its payload may have changed.",
        f"{where} : la réponse de Valet n'a pas de champ {field!r} utilisable ; son format "
        "a peut-être changé.",
        lang,
    )


def _require_mapping(obj: Any, field: str, where: str, lang: str = "en") -> dict[str, Any]:
    """`obj[field]` as a dict, or an UpstreamError naming `field`."""
    value = obj.get(field) if isinstance(obj, dict) else None
    if not isinstance(value, dict):
        raise _shape_error(where, field, lang)
    return value


def _check_observation_rows(obj: Any, where: str, lang: str = "en") -> dict[str, Any]:
    """The observations payload, after checking every row carries its date "d".

    Run inside the cached fetch, so a malformed payload is never cached.
    """
    if not isinstance(obj, dict):
        raise _shape_error(where, "observations", lang)
    for row in list_or_empty(obj, "observations"):
        if not isinstance(row, dict) or "d" not in row:
            raise _shape_error(where, "d", lang)
    return obj


def _parse_value(raw: str | None) -> float | None:
    """Valet sends "v" as a JSON string even for numeric series; treat a
    missing or empty value as no data rather than a parse failure. Text that
    is not a number is None here too; _observations_from_json keeps that text
    beside it, so a note is never lost as a silent null."""
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


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


def _observations_from_json(
    rows: list[dict[str, Any]], where: str = "observations", lang: str = "en"
) -> list[Observation]:
    observations = []
    for row in rows:
        if not isinstance(row, dict) or "d" not in row:
            raise _shape_error(where, "d", lang)
        ref_date = row["d"]
        values: dict[str, float | None] = {}
        non_numeric: dict[str, str] = {}
        for code, entry in row.items():
            if code == "d" or not isinstance(entry, dict):
                continue
            raw = entry.get("v")
            values[code] = _parse_value(raw)
            if values[code] is None and raw not in (None, "") and str(raw).strip():
                non_numeric[code] = str(raw)
        observations.append(
            Observation(ref_date=ref_date, values=values, non_numeric=non_numeric or None)
        )
    return observations


def _non_numeric_note(observations: list[Observation], lang: str) -> str | None:
    count = sum(len(o.non_numeric or {}) for o in observations)
    if not count:
        return None
    if lang == "fr":
        return french_spacing(
            f"{count} valeur(s) envoyée(s) par Valet sous forme de texte non numérique sont "
            "nulles dans `values` ; le texte reçu est dans `non_numeric` de la ligne."
        )
    return (
        f"{count} value(s) Valet sent as text that is not a number are null in `values`; the "
        "text as sent is in the row's `non_numeric`."
    )


def _latest_date(observations: list[Observation]) -> datetime | None:
    """The newest observation date, as provenance as_of."""
    if not observations:
        return None
    return datetime.combine(max(o.ref_date for o in observations), time(), tzinfo=UTC)


def _series_info_from_json(series_detail: dict[str, Any]) -> dict[str, SeriesInfoBrief]:
    briefs = {}
    for code, obj in series_detail.items():
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        briefs[code] = SeriesInfoBrief(
            name=code,
            label=obj.get("label", ""),
            description=obj.get("description", ""),
            unit=metadata.get("unit") or None,
            frequency=metadata.get("frequency") or None,
        )
    return briefs


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
        container = _require_mapping(obj, container_key, path, lang)
        return [
            item_type(name=code, label=e.get("label", ""), description=e.get("description", ""))
            for code, e in container.items()
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

    path = f"series/{_path_segment(name)}/json"

    async def fetch() -> dict[str, Any]:
        obj = await _get(path, lang=lang)
        detail = _require_mapping(obj, "seriesDetails", path, lang)
        if not detail.get("name"):
            raise _shape_error(path, "seriesDetails.name", lang)
        return detail

    detail, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
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

    path = f"groups/{_path_segment(name)}/json"

    async def fetch() -> dict[str, Any]:
        obj = await _get(path, lang=lang)
        # Valet renamed "groupDetails" to "groupDetail" in October 2026;
        # the old key is still read in case a mirror or cache serves it.
        field = "groupDetails" if isinstance(obj, dict) and "groupDetails" in obj else "groupDetail"
        detail = _require_mapping(obj, field, path, lang)
        if not detail.get("name"):
            raise _shape_error(path, f"{field}.name", lang)
        return detail

    detail, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
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


# dateFormat words (English and French domains, seen live 2026-10-27) -> periods
# per year. "daily"/"quotidien" and "weekly" have no calendar step.
_DATE_FORMAT_PPY = {
    "monthly": 12,
    "mensuel": 12,
    "quarterly": 4,
    "trimestriel": 4,
    "annual": 1,
    "annuel": 1,
}
# Without metadata.unit: words that make a series a percentage or an interest
# rate. "Exchange rate" alone is a price, not a percentage, so bare "rate" is
# not enough.
_RATE_WORDS = re.compile(
    r"percent|pourcent|\byields?\b|rendement|interest rate|taux d.int[ée]r[êe]t|policy rate|"
    r"taux directeur|prime rate|taux pr[ée]f[ée]rentiel|bank rate|taux officiel",
    re.IGNORECASE,
)


def _series_ppy(detail: dict[str, Any], days: list[date]) -> int | None:
    word = str(detail.get("dateFormat") or "").strip().lower()
    return _DATE_FORMAT_PPY.get(word) if word else infer_periods_per_year(days)


def _is_rate(info: SeriesInfoBrief) -> bool:
    if info.unit:
        return is_rate_unit(info.unit)
    return bool(_RATE_WORDS.search(f"{info.label} {info.description}"))


def _points(observations: list[Observation], code: str) -> list[tuple[date, float | None]]:
    """The series' own rows: with mixed frequencies a row may not carry it at all."""
    return [(o.ref_date, o.values[code]) for o in observations if code in o.values]


def history_window(
    window: list[date], ppys: list[int | None], request: TransformRequest
) -> dict[str, str]:
    """start_date/end_date reaching back far enough before the window's first
    date for the transform's lag (and index base). reproduce_code asks the same."""
    out_ppys = [PERIODS_PER_YEAR[request.frequency] if request.frequency else p for p in ppys]
    # An unknown or daily frequency counts as annual here: over-fetching
    # costs only bytes, under-fetching would leave the first values null.
    months = max(
        (
            extra_months(
                request.transform,
                ppy or 1,
                aggregating=request.frequency is not None,
                window=request.window,
            )
            for ppy in out_ppys
        ),
        default=0,
    )
    first = min(window)
    start = shift_months(first, -months) if months else first
    if request.index_base:
        try:
            start = min(start, parse_period(request.index_base)[0])
        except ValueError:
            pass  # transform_series rejects it with a clear message
    return {"start_date": start.isoformat(), "end_date": max(window).isoformat()}


async def _transformed(
    names: list[str],
    params: dict[str, Any],
    payload: dict[str, Any],
    observations: list[Observation],
    kept: list[Observation],
    request: TransformRequest,
    lang: str,
) -> tuple[dict[str, TransformedSeries], str | None]:
    """Computed values per series, and the request that fetched their history.

    The window is what Valet returned for the caller's own parameters. For
    the lag, the same series are fetched again from earlier (by start_date),
    so a year-over-year change at the window's first date has its year-ago
    level. With no window the full history was already fetched.
    """
    details = payload.get("seriesDetail", {}) or {}
    infos = _series_info_from_json(details)
    codes = [c for c in infos if any(c in o.values for o in kept)] or list(infos)
    history, fetched = observations, None
    if params and kept:
        history_params = history_window(
            [o.ref_date for o in kept],
            [
                _series_ppy(details.get(c, {}), [d for d, _ in _points(observations, c)])
                for c in codes
            ],
            request,
        )
        joined = ",".join(_path_segment(n) for n in names)
        path = f"observations/{joined}/json"
        cache_key = _cache_key(f"boc:{path}:{sorted(history_params.items())}", lang)

        async def fetch() -> dict[str, Any]:
            return _check_observation_rows(
                await _get(path, params=history_params, lang=lang), path, lang
            )

        obj, _ = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
        history = _observations_from_json(list_or_empty(obj, "observations"), path, lang)
        fetched = _url(path, history_params, lang)
    result: dict[str, TransformedSeries] = {}
    for code in codes:
        info = infos[code]
        window = [d for d, _ in _points(kept, code)]
        points = _points(history, code)
        result[code] = transform_series(
            points,
            source_ppy=_series_ppy(details.get(code, {}), [d for d, _ in points]),
            transform=request.transform,
            frequency=request.frequency,
            aggregation=request.aggregation,
            index_base=request.index_base,
            window=request.window,
            rate_unit=_is_rate(info),
            units=info.unit,
            window_start=min(window) if window else None,
            window_end=max(window) if window else None,
            lang=lang,
        )
    return result, fetched


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
    request: TransformRequest | None = None,
) -> ObservationsResult:
    if not series_names:
        _raise(
            InvalidInput,
            "series_names must contain at least one series name.",
            "series_names doit contenir au moins un nom de série.",
            lang,
        )
    names = [_require_name(n, "Series", lang) for n in series_names]
    if request is not None:
        request.check(lang)
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
        return _check_observation_rows(await _get(path, params=params, lang=lang), path, lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    observations = _observations_from_json(list_or_empty(obj, "observations"), path, lang)
    kept = _keep_latest(observations)
    transformed: dict[str, TransformedSeries] | None = None
    coverage = [_non_numeric_note(kept, lang)]
    if request is not None and request.active:
        transformed, fetched = await _transformed(
            names, params, obj, observations, kept, request, lang
        )
        coverage.append(_transform_note(fetched, lang))
    return ObservationsResult(
        series=_series_info_from_json(obj.get("seriesDetail", {}) or {}),
        observations=kept,
        transformed=transformed,
        provenance=make_provenance(
            source="boc",
            url=_url(path, params, lang),
            cached=was_cached,
            as_of=_latest_date(observations),
            schema_name="boc.ObservationsResult",
            coverage=" ".join(c for c in coverage if c) or None,
            limits=_observation_limits(len(kept), len(observations), lang),
            lang=lang,
        ),
    )


def _transform_note(fetched: str | None, lang: str) -> str:
    if lang == "fr":
        history = f" ; l'historique du décalage vient de {fetched}" if fetched else ""
        return french_spacing(
            "`transformed` est calculé par MapleStats à partir des valeurs publiées (voir sa "
            f"formula){history}. `observations` restent telles que publiées."
        )
    history = f"; the history for the lag came from {fetched}" if fetched else ""
    return (
        "`transformed` is computed by MapleStats from the published values (see its "
        f"formula){history}. `observations` stay as published."
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
        return _check_observation_rows(await _get(path, params=params, lang=lang), path, lang)

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
    group_detail = obj.get("groupDetail", {}) or {}
    observations = _observations_from_json(list_or_empty(obj, "observations"), path, lang)
    kept = _keep_latest(observations)
    return GroupObservationsResult(
        # This endpoint's "groupDetail" has no "name" field - see this
        # module's docstring and schemas.py's.
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
            coverage=_non_numeric_note(kept, lang),
            limits=_observation_limits(len(kept), len(observations), lang),
            lang=lang,
        ),
    )
