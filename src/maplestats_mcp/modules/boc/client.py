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

import itertools
import math
import re
from collections.abc import Callable, Sequence
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
from maplestats_mcp.shared.limits import fit_to_budget, join_limits, truncation_note
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.newer_data import newer_data_note, today
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


# --- Discontinued series and the exchange-rate caveat ----------------------
#
# Valet keeps legacy series beside the current ones: the old noon USD/CAD rate
# IEXE0101 (label USD_NOON) has its last value on 2017-04-28 and is still listed,
# searchable and served (checked live 2026-11-09), as are 3-month bankers'
# acceptance rates that end on 2018-12-31. Valet's metadata has no end date or
# status, so a series counts as discontinued when its newest observation is far
# older than its frequency allows. The newest dates come from `recent=1`, which
# accepts many comma-joined names and returns each series' own newest row
# (checked live on daily, monthly, quarterly and annual series together).

# Days without a new observation after which a series counts as discontinued, by
# frequency word (dateFormat or metadata.frequency, English or French): several
# periods plus the longest publication lag seen. "business daily" contains
# "daily", "quotidienne" contains "quotidien", and so on, so order matters only
# for "semi-annual", which falls under annual.
_STALE_AFTER_DAYS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("daily", "quotidien"), 90),
    (("weekly", "hebdomadaire"), 120),
    (("monthly", "mensuel"), 400),
    (("quarterly", "trimestriel"), 730),
    (("annual", "annuel", "yearly"), 1461),
)

# Curated successors, only for the well-known replacement: the Bank stopped its
# noon and closing exchange rates after 2017-04-28 and has published one
# indicative daily average per currency since 2017-05-01, FX{ccy}CAD, with its
# monthly and annual averages FXM{ccy}CAD and FXA{ccy}CAD. Valet still lists the
# legacy rates (checked live 2026-11-09), named in three shapes, the same on the
# English and French domains:
# - daily: label "{CCY}_NOON" or "{CCY}_CLOSE" (IEXE0101 USD_NOON, IEXE1201.CL
#   GBP_CLOSE, EUROCAE01 EUR_NOON);
# - monthly averages: IEXM{nnnn}[_AVG], label "{CCY}" (IEXM0101 USD);
# - annual averages: label "STATIC_XAVG_A_{daily series}" (IEXA0101
#   STATIC_XAVG_A_IEXE0101), the currency read from the daily series' label.
# Forward rates share these labels (IEXE0105 "U.S. dollar noon, 90-day"), so a
# description naming a term gets no successor. A successor is named only when the
# inventory has it (no FXDKKCAD exists for the Danish krone noon rate).
_LEGACY_FX_LABEL = re.compile(r"^([A-Z]{3})_(NOON|CLOSE)$")
_LEGACY_FX_MONTHLY = re.compile(r"^IEXM\d{4}(?:_AVG)?$")
_LEGACY_FX_ANNUAL = re.compile(r"^STATIC_XAVG_A_(IEXE\d{4})$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_NOT_SPOT = re.compile(r"\d+.?(?:day|jour)|forward|à terme|month|mois", re.IGNORECASE)
_SUCCESSORS = {"IEXE0101_RECIPROCAL": "FXCADUSD"}  # the CAD/USD noon rate
# Bank of Canada exchange rates since 2017-05-01: FX{ccy}CAD (or FXCAD{ccy}) daily,
# FXM.../FXA... their monthly and annual averages (checked in the inventory
# 2026-11-09: 54 daily, 27 monthly, 27 annual).
_FX_DAILY = re.compile(r"^FX[A-Z]{6}$")
_FX_AVERAGE = re.compile(r"^FX[AM][A-Z]{6}$")
_FX_DAILY_NOTE = (
    "Indicative rate: one Bank of Canada daily average per currency, published by about "
    "16:30 ET each business day. It is not a transactional rate; banks and dealers trade "
    "at their own rates."
)
_FX_DAILY_NOTE_FR = (
    "Taux indicatif : une moyenne quotidienne par devise, publiée par la Banque du Canada "
    "vers 16 h 30 (heure de l'Est) chaque jour ouvrable. Ce n'est pas un taux de "
    "transaction ; les banques et les courtiers appliquent leurs propres taux."
)
_FX_AVERAGE_NOTE = (
    "Average of the Bank of Canada's indicative daily average rates (each published by "
    "about 16:30 ET); not a transactional rate."
)
_FX_AVERAGE_NOTE_FR = (
    "Moyenne des taux moyens quotidiens indicatifs de la Banque du Canada (chacun publié "
    "vers 16 h 30, heure de l'Est) ; ce n'est pas un taux de transaction."
)


def fx_note(name: str, lang: str = "en") -> str | None:
    """The indicative-rate caveat for a Bank of Canada exchange rate series, else None."""
    if _FX_DAILY.match(name):
        return french_spacing(_FX_DAILY_NOTE_FR) if lang == "fr" else _FX_DAILY_NOTE
    if _FX_AVERAGE.match(name):
        return french_spacing(_FX_AVERAGE_NOTE_FR) if lang == "fr" else _FX_AVERAGE_NOTE
    return None


def _stale_after(frequency: str | None) -> int | None:
    word = (frequency or "").lower()
    for words, days in _STALE_AFTER_DAYS:
        if any(w in word for w in words):
            return days
    return None


def _frequency_of(detail: Any) -> str | None:
    """metadata.frequency ("Business daily"), else dateFormat ("daily"), else None."""
    if not isinstance(detail, dict):
        return None
    metadata = detail.get("metadata")
    frequency = metadata.get("frequency") if isinstance(metadata, dict) else None
    return frequency or detail.get("dateFormat") or None


def _is_legacy_fx(name: str, label: str) -> bool:
    """A noon or closing exchange rate, or an average of one (see _LEGACY_FX_LABEL)."""
    label = label.strip()
    return (
        name in _SUCCESSORS
        or bool(_LEGACY_FX_LABEL.match(label) or _LEGACY_FX_ANNUAL.match(label))
        or bool(_LEGACY_FX_MONTHLY.match(name) and _CURRENCY.match(label))
    )


def _successor(
    name: str, label: str, description: str, inventory: dict[str, str] | None
) -> str | None:
    """The daily-average series that replaced a legacy exchange rate, else None.

    `inventory` maps series names to labels; None (not read) names the
    candidate unchecked, which an annual average cannot have.
    """
    label = label.strip()
    if name in _SUCCESSORS:
        candidate: str | None = _SUCCESSORS[name]
    elif not _is_legacy_fx(name, label) or _NOT_SPOT.search(description):
        return None
    elif match := _LEGACY_FX_LABEL.match(label):
        candidate = f"FX{match.group(1)}CAD"
    elif _LEGACY_FX_MONTHLY.match(name):
        candidate = f"FXM{label}CAD"
    elif (match := _LEGACY_FX_ANNUAL.match(label)) and inventory:
        daily = _LEGACY_FX_LABEL.match(inventory.get(match.group(1), ""))
        candidate = f"FXA{daily.group(1)}CAD" if daily else None
    else:
        candidate = None
    if candidate and inventory is not None and candidate not in inventory:
        return None
    return candidate


class _StatusEntry(Protocol):
    """What status_fields fills: SeriesSummary, SeriesDetail, SeriesInfoBrief."""

    name: str
    label: str
    description: str


def status_fields(
    entry: _StatusEntry,
    latest: date | None,
    frequency: str | None,
    known: dict[str, str] | None,
    lang: str = "en",
    *,
    with_fx: bool = True,
) -> dict[str, Any]:
    """status, last_observation, successor and note for one series.

    `latest` is its newest observation date (None when unknown), `known` the
    inventory's labels by series name (a successor is named only when it exists
    there; None skips that check). With `with_fx` the note also carries the
    exchange-rate caveat (an observations result puts it in provenance.caveats).
    """
    fields: dict[str, Any] = {"last_observation": latest}
    notes: list[str] = []
    stale = _is_stale(latest, frequency)
    if stale is not None:
        fields["status"] = "discontinued" if stale else "active"
        if stale and latest is not None:
            successor = _successor(entry.name, entry.label, entry.description, known)
            fields["successor"] = successor
            notes.append(_discontinued_note(entry, latest, frequency or "", successor, lang))
    fx = fx_note(entry.name, lang) if with_fx else None
    if fx:
        notes.append(fx)
    fields["note"] = " ".join(notes) or None
    return fields


def _is_stale(latest: date | None, frequency: str | None) -> bool | None:
    """Whether the newest observation is too old for the frequency; None when unknown."""
    limit = _stale_after(frequency)
    if latest is None or limit is None:
        return None
    return (today() - latest).days > limit


async def _known_for(
    entries: Sequence[_StatusEntry],
    latest: dict[str, tuple[date | None, str | None]],
    lang: str,
) -> dict[str, str] | None:
    """The inventory's labels, read only when a stale series may have a successor."""
    for entry in entries:
        day, frequency = latest.get(entry.name, (None, None))
        if _is_stale(day, frequency) and _is_legacy_fx(entry.name, entry.label):
            return await _known_names(lang)
    return None


def _discontinued_note(
    entry: _StatusEntry, latest: date, frequency: str, successor: str | None, lang: str
) -> str:
    noon = _is_legacy_fx(entry.name, entry.label)
    if lang == "fr":
        if noon:
            text = (
                f"Série abandonnée : dernière observation le {latest.isoformat()}. La Banque a "
                "cessé de publier ses taux de change à midi et de clôture après le 28 avril "
                "2017 et publie depuis un seul taux moyen quotidien indicatif par devise"
            )
            text += f" ; série qui la remplace : {successor}." if successor else "."
        else:
            text = (
                f"Série abandonnée : aucune observation depuis le {latest.isoformat()}, bien "
                f"plus longtemps que sa fréquence ({frequency}) ne le laisse attendre. Valet la "
                "conserve pour son historique, mais elle n'est plus mise à jour"
            )
            text += f" ; série qui la remplace : {successor}." if successor else "."
        return french_spacing(text)
    if noon:
        text = (
            f"Discontinued: last observation {latest.isoformat()}. The Bank stopped publishing "
            "noon and closing exchange rates after 2017-04-28 and has since published one "
            "indicative daily average rate per currency"
        )
        tail = f"; successor: {successor}." if successor else " (none for this series)."
        return text + tail
    text = (
        f"Discontinued: no observation since {latest.isoformat()}, far longer than its "
        f"{frequency.lower()} frequency allows. Valet keeps it for its history, but it is no "
        "longer updated"
    )
    return text + (f"; successor: {successor}." if successor else ".")


async def latest_dates(
    names: list[str], lang: str = "en"
) -> dict[str, tuple[date | None, str | None]]:
    """Newest observation date and frequency per series, one request per chunk.

    A series whose rows are not dated (Valet keys some by "k" or "orr_id",
    seen live on CORRA_NOTE_* and ORR_KEY) gets a None date; a chunk whose
    request fails leaves its series out, since a status is only a hint.
    """
    found: dict[str, tuple[date | None, str | None]] = {}
    size = constants.STATUS_CHUNK
    for start in range(0, len(names), size):
        chunk = names[start : start + size]
        path = f"observations/{','.join(_path_segment(n) for n in chunk)}/json"
        params = {"recent": 1}

        async def fetch(path: str = path, params: dict[str, int] = params) -> Any:
            return await _get(path, params=params, lang=lang)

        try:
            obj, _ = await cached_fetch(
                _cache_key(f"boc:latest:{path}", lang),
                constants.CACHE_TTL_OBSERVATIONS_SECONDS,
                fetch,
            )
        except (InvalidInput, NotFound, UpstreamError, UpstreamUnavailable, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        details = obj.get("seriesDetail") or {}
        newest: dict[str, date] = {}
        for row in list_or_empty(obj, "observations"):
            if not isinstance(row, dict) or "d" not in row:
                continue
            try:
                day = date.fromisoformat(str(row["d"]))
            except ValueError:
                continue
            for code, entry in row.items():
                if code != "d" and isinstance(entry, dict):
                    newest[code] = max(day, newest.get(code, day))
        for code in chunk:
            if code in details or code in newest:
                found[code] = (newest.get(code), _frequency_of(details.get(code)))
    return found


async def _known_names(lang: str) -> dict[str, str] | None:
    """The inventory's labels by series name (cached for a day), None when unreadable."""
    try:
        inventory = await list_series(lang)
    except (InvalidInput, NotFound, UpstreamError, UpstreamUnavailable, ValueError):
        return None
    return {s.name: s.label for s in inventory.series}


async def _statuses(entries: Sequence[_StatusEntry], lang: str) -> dict[str, dict[str, Any]]:
    """status_fields for each entry, from one recent=1 request per chunk."""
    latest = await latest_dates([e.name for e in entries], lang)
    known = await _known_for(entries, latest, lang)
    fields: dict[str, dict[str, Any]] = {}
    for entry in entries:
        day, frequency = latest.get(entry.name, (None, None))
        fields[entry.name] = status_fields(entry, day, frequency, known, lang)
    return fields


async def annotate_series(result: SeriesList, lang: str = "en") -> SeriesList:
    """The listed series with their status, last observation, successor and note.

    Only the first STATUS_CHECK_MAX are checked (provenance.coverage says so).
    """
    checked = result.series[: constants.STATUS_CHECK_MAX]
    fields = await _statuses(list(checked), lang)
    series = [s.model_copy(update=fields[s.name]) if s.name in fields else s for s in result.series]
    coverage = [result.provenance.coverage, _status_coverage(len(checked), len(series), lang)]
    provenance = result.provenance.model_copy(
        update={"coverage": " ".join(c for c in coverage if c) or None}
    )
    return result.model_copy(update={"series": series, "provenance": provenance})


def _status_coverage(checked: int, total: int, lang: str) -> str:
    if lang == "fr":
        text = (
            "`status` (active ou discontinued) vient de la date de la plus récente "
            "observation de chaque série, comparée à sa fréquence"
        )
        if checked < total:
            text += f" ; vérifié pour les {checked} premières séries seulement"
        return french_spacing(text + ".")
    text = "`status` (active or discontinued) compares each series' newest observation with its frequency"
    if checked < total:
        text += f"; checked for the first {checked} series only"
    return text + "."


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


_DROPPED = re.compile(r"[.'’()]")
_SEPARATORS = re.compile(r"[\W_]+")


def _words(text: str) -> list[str]:
    """Lower-case words with dots, apostrophes and brackets dropped: "U.S. dollar
    (noon)" reads us, dollar, noon, so the words a user types match Valet's own
    spelling; "_" and "/" separate words too (USD_NOON, USD/CAD)."""
    return [w for w in _SEPARATORS.split(_DROPPED.sub("", text.lower())) if w]


def _entry_words(item: _NamedEntry) -> list[str]:
    """An entry's words plus each adjacent pair run together, so "cpitrim" or
    "cpixfet" typed as one word still finds the label "CPI-trim" / "CPI-XFET"."""
    words = _words(f"{item.name} {item.label} {item.description}")
    return words + [a + b for a, b in itertools.pairwise(words)]


def _has_all(text: list[str], words: list[str]) -> bool:
    # Each query word starts a word of the entry: "rate" finds "rates".
    return all(any(t.startswith(w) for t in text) for w in words)


def _filter_inventory[Entry: _NamedEntry](
    items: list[Entry], query: str
) -> tuple[list[Entry], bool]:
    """Entries holding the query as typed first, then those with every word of it.

    When no entry holds every word, the query is read again with each
    hyphenated chunk run together ("CPI-X" as cpix), then, failing that,
    entries are ranked by the rarer query words they hold: exam agents asked
    for "CPI-trim inflation" and "core inflation CPI-trim" and got nothing,
    because no Valet entry for CPI-trim says "inflation" (checked live
    2026-11-09). The flag says the result is that ranked partial match.
    """
    needle = query.lower()
    exact = [
        item
        for item in items
        if needle in item.name.lower()
        or needle in item.label.lower()
        or needle in item.description.lower()
    ]
    words = _words(query)
    if not words:
        return exact, False
    seen = {id(item) for item in exact}
    texts = [(item, _entry_words(item)) for item in items if id(item) not in seen]
    by_words = [item for item, text in texts if _has_all(text, words)]
    if exact or by_words:
        return exact + by_words, False
    joined = [w for w in ("".join(_words(chunk)) for chunk in query.split()) if w]
    if joined != words:
        by_joined = [item for item, text in texts if _has_all(text, joined)]
        if by_joined:
            return by_joined, False
    return _ranked_partial(texts, list(dict.fromkeys(words))), True


def _ranked_partial[Entry: _NamedEntry](
    texts: list[tuple[Entry, list[str]]], words: list[str]
) -> list[Entry]:
    """Entries ranked by the squared inverse document frequency of the query
    words they hold, kept while within half the best score.

    Squaring lets a rare word ("trim", in 27 of ~16,000 series) outweigh two
    common ones ("year", "over"), so "CPI-trim year-over-year" ranks CPI_TRIM
    above every series that only says year-over-year.
    """
    if not texts:
        return []
    hits = {w: [any(t.startswith(w) for t in text) for _, text in texts] for w in words}
    weight = {
        w: math.log(len(texts) / count) ** 2
        for w, row in hits.items()
        if (count := sum(row)) and count < len(texts)
    }
    if not weight:
        return []
    scores = [sum(weight[w] for w in weight if hits[w][i]) for i in range(len(texts))]
    best = max(scores)
    if best <= 0:
        return []
    ranked = sorted(
        (i for i, score in enumerate(scores) if score >= best / 2), key=lambda i: -scores[i]
    )
    return [texts[i][0] for i in ranked]


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


def _keep_latest(observations: list[Observation], windowless: bool = False) -> list[Observation]:
    """Valet lists oldest first; when the byte budget cuts, keep the newest dates.

    A call with no window keeps at most NO_WINDOW_DATES of them.
    """
    newest = observations[::-1]
    if windowless:
        newest = newest[: constants.NO_WINDOW_DATES]
    kept = fit_to_budget(newest, constants.OBSERVATIONS_MAX_BYTES)
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


def _search_coverage(count: int, kind: str, lang: str, *, partial: bool = False) -> str:
    if lang == "fr":
        what = "séries" if kind == "series" else "groupes"
        text = (
            f"recherche de sous-chaîne ou de tous les mots parmi {_fr_count(count)} {what} "
            "(libellés et descriptions en français de la Banque du Canada)"
        )
        if partial:
            text += (
                " ; aucune entrée ne contient tous les mots : correspondance partielle, "
                "classée selon les mots les plus rares trouvés"
            )
        return french_spacing(text)
    text = f"substring or all-words search over {count} {kind}"
    if partial:
        text += (
            "; no entry holds every word, so this is a partial match ranked by the "
            "rarer query words each entry holds"
        )
    return text


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
    """Client-side search over the cached series inventory, each match with its status.

    Legacy series stay in the results (Valet still serves them), marked
    discontinued with their last date and successor, not hidden.
    """
    _check_limit(limit, constants.SEARCH_LIMIT_MAX, lang)
    all_series = await list_series(lang)
    matches, partial = _filter_inventory(all_series.series, query)
    result = SeriesList(
        series=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=_url("lists/series/json", lang=lang),
            cached=all_series.provenance.cached,
            schema_name="boc.SeriesList",
            coverage=_search_coverage(len(all_series.series), "series", lang, partial=partial),
            limits=_search_limits(min(limit, len(matches)), len(matches), "series", lang),
            lang=lang,
        ),
    )
    return await annotate_series(result, lang)


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


# The Bank's Banking and Financial Statistics tables are Valet groups named by
# table code (A4_RATES_MONTHLY, C1_MONTHLY, E1_MONTHLY, G4_MONTHLY...; 85 groups
# when checked live 2026-11-09), and no label names the publication, so a search
# for it found speeches and Financial System Review charts instead.
_BFS_QUERY = re.compile(
    r"banking\s+and\s+financial\s+statistics|statistiques\s+bancaires\s+et\s+financi[eè]res"
    r"|\bbfs\b|\bsbf\b",
    re.IGNORECASE,
)
_BFS_GROUP = re.compile(r"^(?:[A-H]\d{1,2}|[A-H]TABLE)_")
# Words beside the publication's name that name no table.
_BFS_FILLER = re.compile(
    r"\b(?:bank\s+of\s+canada|banque\s+du\s+canada|boc|valet|tables?|tableaux?|de\s+la|the)\b",
    re.IGNORECASE,
)


async def search_groups(
    query: str, *, limit: int = constants.SEARCH_LIMIT_DEFAULT, lang: str = "en"
) -> GroupList:
    """Client-side substring search over the cached group inventory.

    "Banking and Financial Statistics" (or BFS) narrows the search to the
    groups named by a BFS table code, since no group's label says so.
    """
    _check_limit(limit, constants.SEARCH_LIMIT_MAX, lang)
    all_groups = await list_groups(lang)
    if _BFS_QUERY.search(query):
        tables = [g for g in all_groups.groups if _BFS_GROUP.match(g.name)]
        rest = _BFS_FILLER.sub(" ", _BFS_QUERY.sub(" ", query))
        matches, partial = _filter_inventory(tables, rest) if _words(rest) else (tables, False)
    else:
        matches, partial = _filter_inventory(all_groups.groups, query)
    return GroupList(
        groups=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source="boc",
            url=_url("lists/groups/json", lang=lang),
            cached=all_groups.provenance.cached,
            schema_name="boc.GroupList",
            coverage=_search_coverage(len(all_groups.groups), "groups", lang, partial=partial),
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
    result = SeriesDetail(
        name=detail["name"],
        label=detail.get("label", ""),
        description=detail.get("description", ""),
        frequency=_frequency_of(detail),
        provenance=make_provenance(
            source="boc",
            url=f"{_base(lang)}series/{name}/json",
            cached=was_cached,
            schema_name="boc.SeriesDetail",
            lang=lang,
        ),
    )
    latest = await latest_dates([result.name], lang)
    day, frequency = latest.get(result.name, (None, None))
    frequency = result.frequency or frequency
    known = await _known_for([result], {result.name: (day, frequency)}, lang)
    update = status_fields(result, day, frequency, known, lang)
    return result.model_copy(update={**update, "frequency": frequency})


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
        link=detail.get("link") or None,
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
    kept = _keep_latest(observations, windowless=not params)
    transformed: dict[str, TransformedSeries] | None = None
    coverage = [_non_numeric_note(kept, lang)]
    if request is not None and request.active:
        transformed, fetched = await _transformed(
            names, params, obj, observations, kept, request, lang
        )
        coverage.append(_transform_note(fetched, lang))
    details = obj.get("seriesDetail", {}) or {}
    series = await _with_status(
        _series_info_from_json(details), details, observations, path, end_date, lang
    )
    provenance = make_provenance(
        source="boc",
        url=_url(path, params, lang),
        cached=was_cached,
        as_of=_latest_date(observations),
        schema_name="boc.ObservationsResult",
        coverage=" ".join(c for c in coverage if c) or None,
        limits=join_limits(
            await _newer_data(path, end_date, lang),
            _observation_limits(len(kept), len(observations), lang),
        ),
        lang=lang,
    )
    return ObservationsResult(
        series=series,
        observations=kept,
        transformed=transformed,
        provenance=_with_fx_caveats(provenance, list(series), lang),
    )


def _with_fx_caveats(provenance: Provenance, codes: list[str], lang: str) -> Provenance:
    """provenance with the indicative-rate caveat of any FX* series among `codes`."""
    notes = [n for n in dict.fromkeys(fx_note(c, lang) for c in codes) if n]
    if not notes:
        return provenance
    caveats = list(dict.fromkeys([*provenance.caveats, *notes]))
    return provenance.model_copy(update={"caveats": caveats})


def _reaches_latest(end_date: str | None) -> bool:
    """Whether the returned rows run to each series' newest date (no end before today)."""
    if not end_date:
        return True
    try:
        return date.fromisoformat(end_date) >= today()
    except ValueError:
        return False


async def _with_status(
    infos: dict[str, SeriesInfoBrief],
    details: dict[str, Any],
    observations: list[Observation],
    path: str,
    end_date: str | None,
    lang: str,
) -> dict[str, SeriesInfoBrief]:
    """Each series' info with status, last_observation and successor.

    The rows already hold a series' newest date when they run to today. When
    they stop earlier (an end_date before today) or hold nothing for a
    series, its newest date comes from the same `recent=1` request
    _newer_data makes (cached, so one request serves both).
    """
    latest: dict[str, tuple[date | None, str | None]] = {}
    if _reaches_latest(end_date):
        for code in infos:
            days = [o.ref_date for o in observations if code in o.values]
            if days:
                latest[code] = (max(days), _frequency_of(details.get(code)))
    missing = [code for code in infos if code not in latest]
    if missing:
        recent = await _recent_one(path, lang)
        if recent is not None:
            for code in missing:
                days = [o.ref_date for o in recent if code in o.values]
                latest[code] = (max(days) if days else None, _frequency_of(details.get(code)))
    known = await _known_for(list(infos.values()), latest, lang)
    result: dict[str, SeriesInfoBrief] = {}
    for code, info in infos.items():
        day, frequency = latest.get(code, (None, None))
        update = status_fields(info, day, frequency, known, lang, with_fx=False)
        result[code] = info.model_copy(update=update)
    return result


async def _recent_one(path: str, lang: str) -> list[Observation] | None:
    """The newest observation of each series on `path` (`recent=1`), None on failure."""
    params = {"recent": 1}
    cache_key = _cache_key(f"boc:{path}:{sorted(params.items())}", lang)

    async def fetch() -> dict[str, Any]:
        return _check_observation_rows(await _get(path, params=params, lang=lang), path, lang)

    try:
        obj, _ = await cached_fetch(cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch)
        return _observations_from_json(list_or_empty(obj, "observations"), path, lang)
    except (InvalidInput, NotFound, UpstreamError, UpstreamUnavailable, ValueError):
        # A status or a newer-data note is a hint; the requested data were answered.
        return None


async def _newer_data(path: str, end_date: str | None, lang: str) -> str | None:
    """A note when the series has dates after `end_date` (see shared/newer_data).

    Valet gives no series end date in its metadata, so this asks for the one
    newest observation (`recent=1`, cached like any observations call). A range
    that reaches today needs no check and makes no request.
    """
    if not end_date:
        return None
    try:
        requested_end = date.fromisoformat(end_date)
    except ValueError:
        return None
    if requested_end >= today():
        return None
    recent = await _recent_one(path, lang)
    if recent is None:
        return None
    latest = _latest_date(recent)
    return newer_data_note(
        requested_end=requested_end,
        latest=latest.date() if latest else None,
        latest_args=(
            "recent, recent_months ou recent_years"
            if lang == "fr"
            else "recent, recent_months or recent_years"
        ),
        lang=lang,
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
    kept = _keep_latest(observations, windowless=not params)
    series = _series_info_from_json(obj.get("seriesDetail", {}) or {})
    return GroupObservationsResult(
        # This endpoint's "groupDetail" has no "name" field - see this
        # module's docstring and schemas.py's.
        group=GroupInfo(
            name=group_name,
            label=group_detail.get("label", ""),
            description=group_detail.get("description", ""),
            link=group_detail.get("link"),
        ),
        series=series,
        observations=kept,
        provenance=_with_fx_caveats(
            make_provenance(
                source="boc",
                url=_url(path, params, lang),
                cached=was_cached,
                as_of=_latest_date(observations),
                schema_name="boc.GroupObservationsResult",
                coverage=_non_numeric_note(kept, lang),
                limits=join_limits(
                    await _newer_data(path, end_date, lang),
                    _observation_limits(len(kept), len(observations), lang),
                ),
                lang=lang,
            ),
            list(series),
            lang,
        ),
    )
