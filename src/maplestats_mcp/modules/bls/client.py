"""Client for the US Bureau of Labor Statistics Public Data API v2.

Checked live on 2026-11-07 with the project's User-Agent and no key:

- `POST timeseries/data/` with `{"seriesid": [...], "startyear", "endyear"}`
  answers without a key, at the unregistered limits. The body always says
  `"status": "REQUEST_SUCCEEDED"` for a usable request, with problems in
  `message[]`: "Series does not exist for Series XXX123" (that series comes
  back with an empty `data`), and "Year range has been reduced to the
  system-allowed limit of 10 years." A 2012-2026 request returned 2012-2021:
  the API keeps the oldest years, not the newest, so this client asks in
  chunks of the year limit, newest first.
- `catalog: true` without a key is ignored with the message "The catalog has
  been disabled for this request." Some JOLTS ids add "Unable to get Catalog
  Data for series ..." even when no catalog was asked for; the data still
  comes. Titles therefore come from constants.KNOWN_SERIES unless a key is set.
- `value` is a string; "-" marks a missing month (October 2025 for CPS
  series, footnoted "Data unavailable due to the 2025 lapse in
  appropriations."). Rows come newest first; `latest: "true"` marks the
  newest. Footnotes are `[{}]` when empty, `{"code": "P", "text":
  "preliminary"}` for preliminary payrolls, "I" (Initial) for chained CPI.
- `surveys` lists 60-odd surveys (`survey_abbreviation`, `survey_name`);
  `timeseries/popular?survey=CU` lists popular ids (`seriesID` only).
- download.bls.gov's flat files (series titles) answer 403 to automated
  clients, so they are not used.
- The seasonal code is the third character of an id (CES..., CUUR..., LNS...),
  S or U, for every survey this module names.
"""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp import config
from maplestats_mcp.modules.bls import constants
from maplestats_mcp.modules.bls.schemas import (
    IndicatorResult,
    Observation,
    Release,
    SearchResult,
    Series,
    SeriesMatch,
    SeriesResult,
    Survey,
    SurveyList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, api_post, register_secret
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_SERIES_ID = re.compile(r"^[A-Z0-9]{5,30}$")
_SURVEY = re.compile(r"^[A-Z]{2}$")
_PERIOD = re.compile(r"^([MQSA])(\d{2})$")

_FRESHNESS = {
    "en": (
        "Updated on the BLS release schedule: payrolls and unemployment on the first Friday "
        "of most months, the CPI mid-month, JOLTS about five weeks after the month."
    ),
    "fr": (
        "Mis à jour selon le calendrier du BLS : emploi et chômage le premier vendredi de la "
        "plupart des mois, l'IPC au milieu du mois, JOLTS environ cinq semaines après le mois."
    ),
}


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _key() -> str | None:
    key = config.get_bls_api_key()
    if key:
        register_secret(key, "YOUR_BLS_API_KEY")
    return key


def _limits(registered: bool) -> tuple[int, int]:
    if registered:
        return constants.REGISTERED_MAX_SERIES, constants.REGISTERED_MAX_YEARS
    return constants.UNREGISTERED_MAX_SERIES, constants.UNREGISTERED_MAX_YEARS


def _raise_unavailable(exc: Exception, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The BLS Public Data API did not answer: {exc}. Try again in a minute.",
        f"l'API Public Data du BLS n'a pas répondu : {exc}. Réessayez dans une minute.",
        lang,
    )


def _check_status(payload: Any, lang: str) -> list[str]:
    """The API's messages, after raising for a request it did not process."""
    if not isinstance(payload, dict):
        raise_localized(
            UpstreamError,
            "The BLS Public Data API answered with something other than a JSON object.",
            "l'API Public Data du BLS a répondu autre chose qu'un objet JSON.",
            lang,
        )
    messages = [str(m) for m in list_or_empty(payload, "message") if m]
    status = str(payload.get("status") or "")
    if status == "REQUEST_SUCCEEDED":
        return messages
    joined = " ".join(messages) or status
    if "threshold" in joined.lower() or "limit" in joined.lower():
        raise_localized(
            UpstreamUnavailable,
            f"The BLS refused the request: {joined} Without a registration key the BLS "
            "allows 25 queries a day per address; the server operator can set "
            "MAPLE_BLS_API_KEY (free at https://data.bls.gov/registrationEngine/) for 500. "
            "Fix: retrying today will fail too; say the BLS daily limit was reached and the "
            "data can be fetched tomorrow, or from bls.gov. Do not answer from memory.",
            f"le BLS a refusé la requête : {joined} Sans clé d'enregistrement, le BLS "
            "permet 25 requêtes par jour et par adresse ; l'exploitant du serveur peut "
            "définir MAPLE_BLS_API_KEY (gratuite sur https://data.bls.gov/registrationEngine/) "
            "pour en avoir 500. Solution : réessayer aujourd'hui échouera aussi ; dites que la "
            "limite quotidienne du BLS est atteinte et que les données pourront être obtenues "
            "demain, ou sur bls.gov. Ne répondez pas de mémoire.",
            lang,
        )
    raise_localized(
        UpstreamError,
        f"The BLS Public Data API did not process the request ({status}): {joined}",
        f"l'API Public Data du BLS n'a pas traité la requête ({status}) : {joined}",
        lang,
    )


async def _post(body: dict[str, Any], lang: str) -> Any:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    try:
        return await api_post(constants.DATA_URL, json_body=body, timeout=constants.TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429 or status >= 500:
            _raise_unavailable(exc, lang)
        raise_localized(
            UpstreamError,
            f"The BLS Public Data API answered HTTP {status}.",
            f"l'API Public Data du BLS a répondu HTTP {status}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(exc, lang)
    except ValueError as exc:  # not JSON
        raise_localized(
            UpstreamError,
            f"The BLS Public Data API did not answer in JSON: {exc}",
            f"l'API Public Data du BLS n'a pas répondu en JSON : {exc}",
            lang,
        )


async def _get(url: str, params: dict[str, str] | None, lang: str) -> Any:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    try:
        return await api_get(url, params=params, timeout=constants.TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429 or status >= 500:
            _raise_unavailable(exc, lang)
        raise_localized(
            UpstreamError,
            f"The BLS Public Data API answered HTTP {status} for {url}.",
            f"l'API Public Data du BLS a répondu HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(exc, lang)
    except ValueError as exc:
        raise_localized(
            UpstreamError,
            f"The BLS Public Data API did not answer in JSON: {exc}",
            f"l'API Public Data du BLS n'a pas répondu en JSON : {exc}",
            lang,
        )


# ---------------------------------------------------------------- helpers


def _seasonal(series_id: str, catalog: dict[str, Any] | None, lang: str) -> str | None:
    text = str((catalog or {}).get("seasonality") or "").lower()
    if not text:
        code = series_id[2:3]
        text = {"S": "seasonally adjusted", "U": "not seasonally adjusted"}.get(code, "")
    if not text:
        return None
    adjusted = not text.startswith("not")
    if lang == "fr":
        return "désaisonnalisé" if adjusted else "non désaisonnalisé"
    return "seasonally adjusted" if adjusted else "not seasonally adjusted"


def _date(year: int, period: str) -> str:
    match = _PERIOD.match(period)
    if not match:
        return str(year)
    kind, number = match.group(1), int(match.group(2))
    if kind == "M" and number <= 12:
        return f"{year}-{number:02d}"
    if kind == "Q" and number <= 4:
        return f"{year}-Q{number}"
    if kind == "S" and number <= 2:
        return f"{year}-S{number}"
    return str(year)  # M13, Q05, S03 and A01 are annual


def _frequency(periods: list[str], lang: str) -> str | None:
    kinds = {p[:1] for p in periods if p not in {"M13", "Q05", "S03"}}
    names = {
        "M": ("monthly", "mensuelle"),
        "Q": ("quarterly", "trimestrielle"),
        "S": ("semiannual", "semestrielle"),
        "A": ("annual", "annuelle"),
    }
    if len(kinds) != 1:
        return None
    en, fr = names.get(kinds.pop(), ("", ""))
    return (fr if lang == "fr" else en) or None


def _value(raw: Any) -> float | None:
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _observations(rows: list[Any]) -> list[Observation]:
    """Tidy rows, oldest first, with the two changes computed over regular periods."""
    parsed: list[Observation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            year = int(row.get("year"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        period = str(row.get("period") or "")
        notes = [
            str(f.get("text") or "").strip()
            for f in list_or_empty(row, "footnotes")
            if isinstance(f, dict) and f.get("text")
        ]
        codes = {
            str(f.get("code") or "") for f in list_or_empty(row, "footnotes") if isinstance(f, dict)
        }
        parsed.append(
            Observation(
                year=year,
                period=period,
                period_name=str(row.get("periodName") or ""),
                date=_date(year, period),
                value=_value(row.get("value")),
                preliminary=bool(codes & {"P", "I"}),
                footnotes=notes,
            )
        )
    parsed.sort(key=lambda o: (o.year, o.period))
    # Changes only between sub-annual periods; an annual average (M13) is
    # neither the previous month nor compared with one.
    regular = [o for o in parsed if o.date != str(o.year) or o.period == "A01"]
    by_key = {(o.year, o.period): o for o in regular}
    for previous, current in itertools.pairwise(regular):
        if previous.value is not None and current.value is not None:
            current.change_from_previous = round(current.value - previous.value, 6)
    for obs in regular:
        year_ago = by_key.get((obs.year - 1, obs.period))
        if year_ago and year_ago.value and obs.value is not None:
            obs.pct_change_from_year_ago = round((obs.value / year_ago.value - 1) * 100, 2)
    return parsed


def _known_title(series_id: str, lang: str) -> tuple[str | None, str | None]:
    known = constants.KNOWN_SERIES.get(series_id)
    if not known:
        return None, None
    return pick(lang, known.title_en, known.title_fr), pick(lang, known.units_en, known.units_fr)


def _release(survey: str, lang: str) -> Release | None:
    release = constants.RELEASES.get(survey)
    if not release:
        return None
    return Release(
        name=pick(lang, release.name_en, release.name_fr), schedule_url=release.schedule_url
    )


def _series(raw: dict[str, Any], lang: str) -> Series:
    series_id = str(raw.get("seriesID") or "")
    catalog = raw.get("catalog") if isinstance(raw.get("catalog"), dict) else None
    title, units = _known_title(series_id, lang)
    if catalog and catalog.get("series_title") and not title:
        title = str(catalog["series_title"])
    observations = _observations(list_or_empty(raw, "data"))
    valued = [o for o in observations if o.value is not None]
    return Series(
        series_id=series_id,
        title=title,
        survey=series_id[:2],
        survey_name=str(catalog.get("survey_name"))
        if catalog and catalog.get("survey_name")
        else None,
        seasonal_adjustment=_seasonal(series_id, catalog, lang),
        units=units,
        frequency=_frequency([o.period for o in observations], lang),
        release=_release(series_id[:2], lang),
        observations=observations,
        latest_date=valued[-1].date if valued else None,
        latest_value=valued[-1].value if valued else None,
    )


def _years(start_year: int | None, end_year: int | None, lang: str) -> tuple[int, int]:
    this_year = datetime.now(UTC).year
    end = end_year or this_year
    start = start_year or end - constants.DEFAULT_YEARS + 1
    if start > end:
        raise_localized(
            InvalidInput,
            f"start_year ({start}) is after end_year ({end}).",
            f"start_year ({start}) est postérieure à end_year ({end}).",
            lang,
        )
    if start < 1913 or end > this_year + 1:
        raise_localized(
            InvalidInput,
            f"Years must fall between 1913 and {this_year}; got {start} to {end}.",
            f"les années doivent être comprises entre 1913 et {this_year} ; reçu {start} à {end}.",
            lang,
        )
    return start, end


def _clean_ids(series_ids: list[str], lang: str, max_series: int) -> list[str]:
    ids: list[str] = []
    for raw in series_ids:
        sid = str(raw).strip().upper()
        if not _SERIES_ID.match(sid):
            raise_localized(
                InvalidInput,
                f"{raw!r} is not a BLS series id (letters and digits, e.g. CUUR0000SA0).",
                f"{raw!r} n'est pas un identifiant de série du BLS (lettres et chiffres, p. ex. "
                "CUUR0000SA0).",
                lang,
            )
        if sid not in ids:
            ids.append(sid)
    if not ids:
        raise_localized(
            InvalidInput,
            "Give at least one series id.",
            "donnez au moins un identifiant de série.",
            lang,
        )
    if len(ids) > max_series:
        raise_localized(
            InvalidInput,
            f"{len(ids)} series asked for; the BLS takes at most {max_series} per query here.",
            f"{len(ids)} séries demandées ; le BLS en accepte au plus {max_series} par requête ici.",
            lang,
        )
    return ids


# ---------------------------------------------------------------- data


async def get_series(
    series_ids: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    lang: str = "en",
) -> SeriesResult:
    lang = normalize_lang(lang)
    key = _key()
    max_series, max_years = _limits(key is not None)
    ids = _clean_ids(series_ids, lang, max_series)
    start, end = _years(start_year, end_year, lang)
    notes: list[str] = []

    # Newest chunk first, so a range trimmed by MAX_CHUNKS keeps recent years.
    chunks: list[tuple[int, int]] = []
    chunk_end = end
    while chunk_end >= start and len(chunks) < constants.MAX_CHUNKS:
        chunks.append((max(start, chunk_end - max_years + 1), chunk_end))
        chunk_end -= max_years
    if chunk_end >= start:
        first = chunks[-1][0]
        notes.append(
            pick(
                lang,
                f"Years {start} to {first - 1} were left out: one call fetches at most "
                f"{constants.MAX_CHUNKS * max_years} years ({constants.MAX_CHUNKS} queries of "
                f"{max_years}). Ask again for the earlier years.",
                f"Les années {start} à {first - 1} ont été omises : un appel couvre au plus "
                f"{constants.MAX_CHUNKS * max_years} ans ({constants.MAX_CHUNKS} requêtes de "
                f"{max_years}). Redemandez les années antérieures.",
            )
        )
        start = first

    async def fetch() -> dict[str, Any]:
        merged: dict[str, dict[str, Any]] = {}
        messages: list[str] = []
        for chunk_start, chunk_stop in chunks:
            body: dict[str, Any] = {
                "seriesid": ids,
                "startyear": str(chunk_start),
                "endyear": str(chunk_stop),
            }
            if key:
                body["registrationkey"] = key
                body["catalog"] = True
            payload = await _post(body, lang)
            for message in _check_status(payload, lang):
                if message not in messages:
                    messages.append(message)
            results = payload.get("Results") if isinstance(payload.get("Results"), dict) else {}
            for raw in list_or_empty(results or {}, "series"):
                if not isinstance(raw, dict) or not raw.get("seriesID"):
                    continue
                sid = str(raw["seriesID"])
                entry = merged.setdefault(sid, {"seriesID": sid, "data": []})
                entry["data"].extend(list_or_empty(raw, "data"))
                if isinstance(raw.get("catalog"), dict):
                    entry["catalog"] = raw["catalog"]
        return {"series": merged, "messages": messages}

    cache_key = f"bls:data:{','.join(ids)}:{start}:{end}:{int(key is not None)}"
    payload, cached = await cached_fetch(cache_key, constants.CACHE_TTL_DATA_SECONDS, fetch)

    series: list[Series] = []
    missing: list[str] = []
    for sid in ids:
        raw = payload["series"].get(sid)
        if not raw or not raw["data"]:
            missing.append(sid)
            continue
        series.append(_series(raw, lang))
    if not series:
        raise_localized(
            NotFound,
            f"The BLS has no data for {', '.join(ids)} in {start} to {end}. "
            f"BLS messages: {' '.join(payload['messages']) or 'none'}",
            f"le BLS n'a aucune donnée pour {', '.join(ids)} de {start} à {end}. Messages du "
            f"BLS : {' '.join(payload['messages']) or 'aucun'}",
            lang,
        )
    if missing:
        notes.append(
            pick(
                lang,
                f"No data for: {', '.join(missing)} (unknown id, or nothing in these years).",
                f"Aucune donnée pour : {', '.join(missing)} (identifiant inconnu ou rien pour "
                "ces années).",
            )
        )
    # The year-range message is about our own chunks; the catalog ones only
    # say a key is missing. The rest (bad ids, no data for a year) pass on.
    # "No Data Available for Series X Year: 1998" comes once per empty year;
    # one note per series with its first period says the same.
    sparse: list[str] = []
    for message in payload["messages"]:
        lowered = message.lower()
        if "year range" in lowered or "catalog" in lowered or "does not exist" in lowered:
            continue
        if lowered.startswith("no data available for series"):
            sid = message.split()[5] if len(message.split()) > 5 else ""
            if sid and sid not in sparse and sid not in missing:
                sparse.append(sid)
            continue
        notes.append(message)
    for one in series:
        if one.series_id in sparse and one.observations:
            notes.append(
                pick(
                    lang,
                    f"{one.series_id} starts in {one.observations[0].date} in this range.",
                    f"{one.series_id} commence en {one.observations[0].date} dans cet intervalle.",
                )
            )
    if not key:
        notes.append(
            pick(
                lang,
                "Titles come from MapleStats' list of known series: without a registration key "
                "the BLS sends no catalog. Seasonal adjustment is read from the id's third "
                "character (S or U).",
                "Les titres viennent de la liste de séries connues de MapleStats : sans clé, le "
                "BLS n'envoie pas de catalogue. La désaisonnalisation est lue au troisième "
                "caractère de l'identifiant (S ou U).",
            )
        )
    return SeriesResult(
        series=series,
        start_year=start,
        end_year=end,
        registered=key is not None,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=constants.DATA_URL,
            cached=cached,
            schema_name="bls.SeriesResult",
            freshness=_FRESHNESS[lang],
            limits=pick(
                lang,
                f"At most {max_series} series and {max_years} years per BLS query "
                f"({'registered' if key else 'unregistered'} limits).",
                f"Au plus {max_series} séries et {max_years} ans par requête au BLS (limites "
                f"{'enregistrées' if key else 'non enregistrées'}).",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def get_indicator(
    indicator: str,
    seasonally_adjusted: bool = True,
    start_year: int | None = None,
    end_year: int | None = None,
    lang: str = "en",
) -> IndicatorResult:
    lang = normalize_lang(lang)
    preset = constants.INDICATORS.get(indicator)
    if preset is None:
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}; use one of {', '.join(constants.INDICATORS)}.",
            f"indicateur inconnu {indicator!r} ; utilisez l'un de "
            f"{', '.join(constants.INDICATORS)}.",
            lang,
        )
    series_id = (
        preset.seasonally_adjusted if seasonally_adjusted else preset.not_seasonally_adjusted
    )
    result = await get_series([series_id], start_year, end_year, lang)
    notes = list(result.notes)
    if indicator in {"cpi_all_items", "cpi_core"}:
        notes.append(
            pick(
                lang,
                "The BLS's headline 12-month CPI change uses the not seasonally adjusted index "
                "(seasonally_adjusted=False); its monthly change uses the adjusted one.",
                "La variation sur 12 mois de l'IPC annoncée par le BLS utilise l'indice non "
                "désaisonnalisé (seasonally_adjusted=False) ; la variation mensuelle, l'indice "
                "désaisonnalisé.",
            )
        )
    if indicator == "nonfarm_payrolls":
        notes.append(
            pick(
                lang,
                "change_from_previous is the monthly job gain or loss, in thousands.",
                "change_from_previous est le gain ou la perte d'emplois du mois, en milliers.",
            )
        )
    return IndicatorResult(
        indicator=indicator,
        label=pick(lang, preset.label_en, preset.label_fr),
        seasonally_adjusted=(series_id[2:3] == "S"),
        series=result.series[0],
        notes=notes,
        provenance=result.provenance.model_copy(update={"schema_name": "bls.IndicatorResult"}),
    )


# ---------------------------------------------------------------- discovery


async def list_surveys(lang: str = "en") -> SurveyList:
    lang = normalize_lang(lang)

    async def fetch() -> list[dict[str, str]]:
        payload = await _get(constants.SURVEYS_URL, None, lang)
        _check_status(payload, lang)
        results = payload.get("Results") if isinstance(payload.get("Results"), dict) else {}
        return [
            {"code": str(s["survey_abbreviation"]), "name": str(s.get("survey_name") or "")}
            for s in list_or_empty(results or {}, "survey")
            if isinstance(s, dict) and s.get("survey_abbreviation")
        ]

    surveys, cached = await cached_fetch("bls:surveys", constants.CACHE_TTL_LIST_SECONDS, fetch)
    if not surveys:
        raise_localized(
            UpstreamError,
            "The BLS survey list came back empty.",
            "la liste des enquêtes du BLS est revenue vide.",
            lang,
        )
    return SurveyList(
        surveys=[Survey(**s) for s in surveys],
        provenance=make_provenance(
            source=constants.SOURCE,
            url=constants.SURVEYS_URL,
            cached=cached,
            schema_name="bls.SurveyList",
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def _popular(survey: str | None, lang: str) -> tuple[list[str], bool]:
    async def fetch() -> list[str]:
        params = {"survey": survey} if survey else None
        payload = await _get(constants.POPULAR_URL, params, lang)
        _check_status(payload, lang)
        results = payload.get("Results") if isinstance(payload.get("Results"), dict) else {}
        return [
            str(s["seriesID"])
            for s in list_or_empty(results or {}, "series")
            if isinstance(s, dict) and s.get("seriesID")
        ]

    return await cached_fetch(
        f"bls:popular:{survey or ''}", constants.CACHE_TTL_LIST_SECONDS, fetch
    )


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9éèêàçôû-]+", text.lower()) if len(w) > 1}


def _match(series_id: str, popular: bool, lang: str) -> SeriesMatch:
    title, units = _known_title(series_id, lang)
    return SeriesMatch(
        series_id=series_id,
        title=title,
        survey=series_id[:2],
        seasonal_adjustment=_seasonal(series_id, None, lang),
        units=units,
        popular=popular,
    )


async def search_series(
    query: str = "",
    survey: str | None = None,
    lang: str = "en",
) -> SearchResult:
    lang = normalize_lang(lang)
    survey_code = survey.strip().upper() if survey else None
    if survey_code and not _SURVEY.match(survey_code):
        raise_localized(
            InvalidInput,
            f"survey must be a two-letter BLS prefix such as CU or LN; got {survey!r}.",
            f"survey doit être un préfixe du BLS de deux lettres, comme CU ou LN ; reçu "
            f"{survey!r}.",
            lang,
        )
    query = query.strip()
    if not query and not survey_code:
        raise_localized(
            InvalidInput,
            "Give a query, a survey prefix, or both.",
            "donnez une requête, un préfixe d'enquête, ou les deux.",
            lang,
        )
    notes: list[str] = []
    words = _words(query)
    scored: list[tuple[int, str]] = []
    for sid, known in constants.KNOWN_SERIES.items():
        if survey_code and not sid.startswith(survey_code):
            continue
        haystack = _words(f"{sid} {known.title_en} {known.title_fr} {known.keywords}")
        score = len(words & haystack) if words else 1
        if query.upper() == sid:
            score += 10
        if score:
            scored.append((score, sid))
    scored.sort(key=lambda item: (-item[0], item[1]))
    matches = [_match(sid, False, lang) for _, sid in scored]

    url = constants.POPULAR_URL
    cached = False
    if survey_code:
        popular, cached = await _popular(survey_code, lang)
        url = f"{constants.POPULAR_URL}?survey={survey_code}"
        seen = {m.series_id for m in matches}
        for m in matches:
            m.popular = m.series_id in popular
        for sid in popular:
            if sid not in seen:
                matches.append(_match(sid, True, lang))
        if not popular:
            notes.append(
                pick(
                    lang,
                    f"The BLS lists no popular series for survey {survey_code}; check the "
                    "prefix with bls_list_surveys.",
                    f"Le BLS ne liste aucune série populaire pour l'enquête {survey_code} ; "
                    "vérifiez le préfixe avec bls_list_surveys.",
                )
            )
    elif _SERIES_ID.match(query.upper()) and not matches:
        matches.append(_match(query.upper(), False, lang))
        notes.append(
            pick(
                lang,
                "Not in MapleStats' list of known series; fetch it with bls_get_series to see "
                "whether the BLS has it.",
                "Absente de la liste de séries connues de MapleStats ; récupérez-la avec "
                "bls_get_series pour vérifier que le BLS la publie.",
            )
        )
    notes.append(
        pick(
            lang,
            "The BLS API has no keyword search. Matches come from MapleStats' list of about 35 "
            "headline series, plus the BLS's popular series when a survey is given; the BLS "
            "Data Finder (https://data.bls.gov/dataQuery/search) finds any other id.",
            "L'API du BLS n'a pas de recherche par mots-clés. Les résultats viennent de la liste "
            "d'environ 35 séries phares de MapleStats, et des séries populaires du BLS quand "
            "une enquête est donnée ; le Data Finder du BLS "
            "(https://data.bls.gov/dataQuery/search) trouve tout autre identifiant.",
        )
    )
    return SearchResult(
        query=query,
        survey=survey_code,
        matches=matches,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=url,
            cached=cached,
            schema_name="bls.SearchResult",
            licence=_licence(lang),
            lang=lang,
        ),
    )
