"""Client for the UK Office for National Statistics' time series.

Checked live on 2026-11-08 with the project's User-Agent, no key (the
Developer Hub says the API "is open and unrestricted - no API keys"):

- Search: `api.beta.ons.gov.uk/v1/search?q=...&content_type=timeseries`
  (the Search API the Developer Hub documents) returns items with `cdid`,
  `dataset_id`, `title`, `uri` and `release_date`; `dataset_ids=LMS` filters.
  Its ranking is loose ("cpih annual rate" puts fish first), so the client
  reranks by title words. Searching a CDID ("d7g7") finds that series in
  every dataset that publishes it (IHYQ: QNA, PN2, UKEA).
- Data: the series page plus `/data` on www.ons.gov.uk
  (`/economy/inflationandpriceindices/timeseries/d7g7/mm23/data`) gives JSON
  with `description` (title, unit, releaseDate, nextRelease) and `months`,
  `quarters`, `years` lists of {date: "2026 SEP" | "2026 Q3" | "2026",
  value: "3.5"}. The Developer Hub's retirement page keeps the `/data`
  endpoints of time series pages (it retires those of articles, bulletins and
  other content pages, and the old v0 `/timeseries` API, which answers 404).
  `/generator?format=csv&uri=...` gives the same series as CSV.
- An unknown series page answers 404 with an HTML page; a search with no
  match answers 200 with no items.

Values checked against ons.gov.uk on 2026-11-08: CPI annual rate (D7G7) 3.5
for September 2026, unemployment rate (MGSX) 4.7 for June-August 2026, GDP
quarterly growth (IHYQ) 0.5 for 2026 Q2.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.ons import constants
from maplestats_mcp.modules.ons.schemas import (
    IndicatorResult,
    Observation,
    SeriesResult,
    SeriesSearch,
    SeriesSummary,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import (
    decode_json,
    new_client,
    raise_if_cloudflare_challenge,
    request_headers,
    retry_after_seconds,
)
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_client = new_client(timeout=constants.TIMEOUT_SECONDS)

_CDID = re.compile(r"^[A-Za-z0-9]{4}$")
_DATASET = re.compile(r"^[A-Za-z0-9]{2,12}$")
_PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|\d{2}))?$")
_WORD = re.compile(r"[a-z0-9]+")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_STOPWORDS = frozenset({"the", "of", "and", "in", "for", "uk", "ons", "a", "an", "by", "to"})

_FRESHNESS = {
    "en": (
        "Updated at 07:00 UK time on each release day: labour market and inflation monthly, "
        "GDP monthly and quarterly; next_release gives the next date."
    ),
    "fr": (
        "Mis à jour à 7 h (heure du Royaume-Uni) chaque jour de publication : marché du travail "
        "et inflation chaque mois, PIB chaque mois et chaque trimestre ; next_release donne la "
        "prochaine date."
    ),
}


class _Block:
    """After a 429 no request is sent until Retry-After (or COOLDOWN_SECONDS)."""

    def __init__(self) -> None:
        self.until = 0.0

    def reset(self) -> None:
        self.until = 0.0


BLOCK = _Block()


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The ONS did not answer ({url}): {detail}. Try again in a minute.",
        f"l'ONS n'a pas répondu ({url}) : {detail}. Réessayez dans une minute.",
        lang,
    )


async def _get(url: str, params: dict[str, Any] | None, lang: str) -> httpx.Response | None:
    """The response, or None for a 404."""
    now = time.monotonic()
    if now < BLOCK.until:
        minutes = max(1, round((BLOCK.until - now) / 60))
        raise_localized(
            UpstreamUnavailable,
            f"The ONS asked this server to slow down (HTTP 429); try again in about {minutes} "
            "minute(s).",
            f"l'ONS a demandé à ce serveur de ralentir (HTTP 429) ; réessayez dans environ "
            f"{minutes} minute(s).",
            lang,
        )
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    headers = request_headers(url, {"Accept": "application/json"})
    try:
        response = await _client.get(url, params=params, headers=headers, follow_redirects=True)
    except httpx.HTTPError as exc:
        _raise_unavailable(url, f"{type(exc).__name__}: {exc}", lang)
    raise_if_cloudflare_challenge(response)
    status = response.status_code
    if status < 400:
        return response
    if status == 404:
        return None
    if status == 429:
        wait = retry_after_seconds(response.headers.get("Retry-After", ""))
        BLOCK.until = time.monotonic() + (wait if wait is not None else constants.COOLDOWN_SECONDS)
        _raise_unavailable(url, "HTTP 429, the ONS rate limit", lang)
    if status >= 500:
        _raise_unavailable(url, f"HTTP {status}", lang)
    raise_localized(
        UpstreamError,
        f"The ONS answered HTTP {status} for {url}: {response.text[:200].strip()}",
        f"l'ONS a répondu HTTP {status} pour {url} : {response.text[:200].strip()}",
        lang,
    )


def _provenance(
    url: str, cached: bool, schema: str, lang: str, coverage: str, as_of: datetime | None = None
) -> Any:
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=schema,
        as_of=as_of,
        freshness=_FRESHNESS[lang],
        coverage=coverage,
        limits=pick(lang, constants.LIMITS, constants.LIMITS_FR),
        licence=pick(lang, constants.LICENCE, constants.LICENCE_FR),
        commercial_use="allowed",
        lang=lang,
    )


def _release(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _uk_date(raw: str | None) -> str | None:
    """The release day as the ONS means it: 2026-10-20T23:00Z is 21 October (UK time)."""
    when = _release(raw)
    if when is None:
        return None
    return when.astimezone(ZoneInfo("Europe/London")).date().isoformat()


# ----------------------------------------------------------------- search


async def _search(params: dict[str, Any], lang: str) -> tuple[list[dict[str, Any]], int, bool]:
    key = f"ons:search:{sorted(params.items())}"

    async def fetch() -> tuple[list[dict[str, Any]], int]:
        response = await _get(constants.SEARCH_URL, params, lang)
        payload = decode_json(response, constants.SEARCH_URL) if response else {}
        items = [
            i
            for i in list_or_empty(payload or {}, "items")
            if isinstance(i, dict) and i.get("type") == "timeseries" and i.get("cdid")
        ]
        return items, int((payload or {}).get("count") or 0)

    (items, count), cached = await cached_fetch(key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    return items, count, cached


def _summary(item: dict[str, Any]) -> SeriesSummary:
    return SeriesSummary(
        series_id=str(item["cdid"]).upper(),
        dataset=str(item.get("dataset_id") or "").upper(),
        title=str(item.get("title") or item["cdid"]),
        release_date=_uk_date(item.get("release_date")),
        url=f"{constants.SITE_URL}{item.get('uri') or ''}",
    )


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


async def search_series(
    query: str, dataset: str | None = None, limit: int = 10, lang: str = "en"
) -> SeriesSearch:
    lang = normalize_lang(lang)
    if not 1 <= limit <= constants.MAX_SEARCH_RESULTS:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_SEARCH_RESULTS}.",
            f"limit doit être compris entre 1 et {constants.MAX_SEARCH_RESULTS}.",
            lang,
        )
    words = _words(query)
    if not words:
        raise_localized(
            InvalidInput,
            "Give a few English words to search for, e.g. 'CPIH annual rate', 'unemployment "
            "rate', 'average weekly earnings'.",
            "donnez quelques mots en anglais à chercher, p. ex. « CPIH annual rate », "
            "« unemployment rate », « average weekly earnings » (l'ONS publie en anglais).",
            lang,
        )
    params: dict[str, Any] = {
        "q": " ".join(words),
        "content_type": "timeseries",
        "limit": constants.SEARCH_FETCH,
    }
    if dataset:
        params["dataset_ids"] = _dataset(dataset, lang)
    items, count, cached = await _search(params, lang)
    # Rerank: titles holding every query word first, then the most words, then
    # the shortest title (an "all items" headline before its sub-indices).
    preset = {(s.series_id, s.dataset) for s in constants.INDICATORS.values()}

    def score(item: dict[str, Any]) -> tuple[int, int, int, int]:
        title = set(_WORD.findall(str(item.get("title") or "").lower()))
        hits = sum(1 for w in words if w in title or w == str(item["cdid"]).lower())
        is_preset = (str(item["cdid"]).upper(), str(item.get("dataset_id") or "").upper()) in preset
        return (-(hits == len(words)), -hits, -is_preset, len(str(item.get("title") or "")))

    ranked = sorted(items, key=score)
    url = str(httpx.URL(constants.SEARCH_URL, params=params))
    return SeriesSearch(
        query=query,
        total_matches=count,
        series=[_summary(i) for i in ranked[:limit]],
        provenance=_provenance(
            url,
            cached,
            "ons.SeriesSearch",
            lang,
            pick(
                lang,
                f"ONS time series matching the query (first {constants.SEARCH_FETCH} reranked by "
                "title).",
                f"Séries chronologiques de l'ONS correspondant à la requête (les "
                f"{constants.SEARCH_FETCH} premières, reclassées selon le titre).",
            ),
        ),
    )


# ------------------------------------------------------------------- data


def _dataset(dataset: str, lang: str) -> str:
    if not _DATASET.match(dataset.strip()):
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not an ONS dataset id (e.g. MM23, LMS, QNA).",
            f"{dataset!r} n'est pas un identifiant de jeu de données de l'ONS (p. ex. MM23, "
            "LMS, QNA).",
            lang,
        )
    return dataset.strip().upper()


async def _locate(
    series_id: str, dataset: str | None, lang: str
) -> tuple[dict[str, Any], list[str]]:
    """The search item for the series (in `dataset` when given) and the other
    datasets publishing it."""
    if not _CDID.match(series_id.strip()):
        raise_localized(
            InvalidInput,
            f"{series_id!r} is not an ONS series id: four letters or digits, e.g. D7G7 (CPI "
            "annual rate) or MGSX (unemployment rate). ons_search_series finds them.",
            f"{series_id!r} n'est pas un identifiant de série de l'ONS : quatre lettres ou "
            "chiffres, p. ex. D7G7 (taux annuel de l'IPC) ou MGSX (taux de chômage). "
            "ons_search_series les trouve.",
            lang,
        )
    cdid = series_id.strip().upper()
    wanted = _dataset(dataset, lang) if dataset else None
    items, _, _ = await _search({"q": cdid.lower(), "content_type": "timeseries"}, lang)
    matches = [i for i in items if str(i["cdid"]).upper() == cdid and i.get("uri")]
    if not matches:
        raise_localized(
            NotFound,
            f"No ONS time series has the id {cdid}. Search with ons_search_series.",
            f"aucune série chronologique de l'ONS n'a l'identifiant {cdid}. Cherchez avec "
            "ons_search_series.",
            lang,
        )
    datasets = [str(i.get("dataset_id") or "").upper() for i in matches]
    if wanted:
        if wanted not in datasets:
            raise_localized(
                NotFound,
                f"Series {cdid} is not in ONS dataset {wanted}; it is in {', '.join(datasets)}.",
                f"la série {cdid} n'est pas dans le jeu {wanted} de l'ONS ; elle est dans "
                f"{', '.join(datasets)}.",
                lang,
            )
        chosen = matches[datasets.index(wanted)]
    else:
        chosen = matches[0]
    others = [d for d in datasets if d != str(chosen.get("dataset_id") or "").upper()]
    return chosen, others


def _period(raw: str, kind: str) -> str | None:
    """'2026 SEP' -> '2026-09'; '2026 Q3' -> '2026-Q3'; '2026' -> '2026'."""
    parts = raw.strip().upper().split()
    if not parts or not parts[0].isdigit():
        return None
    if kind == "years":
        return parts[0]
    if len(parts) != 2:
        return None
    if kind == "quarters" and re.fullmatch(r"Q[1-4]", parts[1]):
        return f"{parts[0]}-{parts[1]}"
    if kind == "months" and parts[1][:3] in _MONTHS:
        return f"{parts[0]}-{_MONTHS[parts[1][:3]]:02d}"
    return None


async def _page(uri: str, lang: str) -> tuple[dict[str, Any], bool]:
    url = f"{constants.SITE_URL}{uri}/data"

    async def fetch() -> dict[str, Any]:
        response = await _get(url, None, lang)
        if response is None:
            raise_localized(
                NotFound,
                f"The ONS has no time series page at {uri}.",
                f"l'ONS n'a pas de page de série chronologique à {uri}.",
                lang,
            )
        payload = decode_json(response, url)
        if not isinstance(payload, dict) or not isinstance(payload.get("description"), dict):
            raise_localized(
                UpstreamError,
                f"The ONS page {url} is not a time series.",
                f"la page {url} de l'ONS n'est pas une série chronologique.",
                lang,
            )
        return payload

    return await cached_fetch(f"ons:page:{uri}", constants.CACHE_TTL_SERIES_SECONDS, fetch)


def _check_periods(
    start_period: str | None, end_period: str | None, last_n: int | None, lang: str
) -> None:
    for name, value in (("start_period", start_period), ("end_period", end_period)):
        if value is not None and not _PERIOD.match(value.strip()):
            raise_localized(
                InvalidInput,
                f"{name} {value!r} is not a period: use 2026, 2026-Q3 or 2026-09.",
                f"{name} {value!r} n'est pas une période : utilisez 2026, 2026-Q3 ou 2026-09.",
                lang,
            )
    if last_n is not None and not 1 <= last_n <= constants.MAX_LAST_N:
        raise_localized(
            InvalidInput,
            f"last_n must be between 1 and {constants.MAX_LAST_N}.",
            f"last_n doit être compris entre 1 et {constants.MAX_LAST_N}.",
            lang,
        )


async def _series(
    series_id: str,
    dataset: str | None,
    frequency: str | None,
    start_period: str | None,
    end_period: str | None,
    last_n: int | None,
    lang: str,
) -> tuple[SeriesResult, Any]:
    _check_periods(start_period, end_period, last_n, lang)
    item, others = await _locate(series_id, dataset, lang)
    uri = str(item["uri"])
    page, cached = await _page(uri, lang)
    description = page["description"]
    available = [
        name
        for name, kind in constants.FREQUENCIES.items()
        if any(
            isinstance(o, dict) and str(o.get("value") or "").strip()
            for o in list_or_empty(page, kind)
        )
    ]
    if not available:
        raise_localized(
            NotFound,
            f"ONS series {item['cdid']} has no values.",
            f"la série {item['cdid']} de l'ONS n'a aucune valeur.",
            lang,
        )
    if frequency is None:
        chosen = available[0]
    elif frequency in available:
        chosen = frequency
    else:
        raise_localized(
            InvalidInput,
            f"Series {item['cdid']} is published {', '.join(available)}, not {frequency}.",
            f"la série {item['cdid']} est publiée ({', '.join(available)}), pas {frequency}.",
            lang,
        )
    kind = constants.FREQUENCIES[chosen]
    observations: list[Observation] = []
    for obs in list_or_empty(page, kind):
        if not isinstance(obs, dict):
            continue
        period = _period(str(obs.get("date") or ""), kind)
        try:
            value = float(str(obs.get("value") or "").strip())
        except ValueError:
            continue
        if period is None:
            continue
        observations.append(Observation(period=period, value=value))
    observations.sort(key=lambda o: o.period)
    # Periods compare as text: 2026-09 >= 2026-01, 2026-Q3 >= 2026-Q1, and a
    # year bound "2026" keeps every 2026-.. period at the start.
    if start_period:
        observations = [o for o in observations if o.period >= start_period.strip()]
    if end_period:
        end = end_period.strip()
        observations = [o for o in observations if o.period <= end or o.period.startswith(end)]
    notes: list[str] = []
    if last_n is not None:
        observations = observations[-last_n:]
    elif len(observations) > constants.MAX_ROWS:
        observations = observations[-constants.MAX_ROWS :]
        notes.append(
            pick(
                lang,
                f"Only the last {constants.MAX_ROWS} observations; csv_url has them all.",
                f"Seules les {constants.MAX_ROWS} dernières observations ; csv_url les contient "
                "toutes.",
            )
        )
    if not observations:
        raise_localized(
            NotFound,
            f"ONS series {item['cdid']} has no {chosen} values in the periods asked for.",
            f"la série {item['cdid']} de l'ONS n'a aucune valeur ({chosen}) pour les périodes "
            "demandées.",
            lang,
        )
    if others:
        notes.append(
            pick(
                lang,
                f"The same series id is also published in {', '.join(others)}; pass dataset to "
                "choose (values are usually identical).",
                f"Le même identifiant est aussi publié dans {', '.join(others)} ; passez dataset "
                "pour choisir (les valeurs sont en général identiques).",
            )
        )
    title = str(description.get("title") or item.get("title") or item["cdid"])
    unit = " ".join(
        p for p in (str(description.get("preUnit") or ""), str(description.get("unit") or "")) if p
    ).strip()
    released = _release(description.get("releaseDate"))
    dataset_id = str(description.get("datasetId") or item.get("dataset_id") or "").upper()
    cdid = str(description.get("cdid") or item["cdid"]).upper()
    today = date.today().isoformat()
    result = SeriesResult(
        series_id=cdid,
        dataset=dataset_id,
        title=title,
        unit=unit or None,
        frequency=chosen,
        available_frequencies=available,
        release_date=_uk_date(description.get("releaseDate")),
        next_release=str(description.get("nextRelease") or "") or None,
        observations=observations,
        latest_period=observations[-1].period,
        latest_value=observations[-1].value,
        other_datasets=others,
        url=f"{constants.SITE_URL}{uri}",
        csv_url=str(
            httpx.URL(f"{constants.SITE_URL}/generator", params={"format": "csv", "uri": uri})
        ),
        citation=pick(
            lang,
            f"Office for National Statistics, {title} ({cdid}, dataset {dataset_id}), "
            f"{constants.SITE_URL}{uri} (accessed on {today}). Open Government Licence v3.0.",
            f"Office for National Statistics, {title} ({cdid}, jeu {dataset_id}), "
            f"{constants.SITE_URL}{uri} (consulté le {today}). Open Government Licence v3.0.",
        ),
        notes=notes,
        provenance=_provenance(
            f"{constants.SITE_URL}{uri}/data",
            cached,
            "ons.SeriesResult",
            lang,
            pick(
                lang,
                f"ONS series {cdid} ({title}), {chosen} values.",
                f"Série {cdid} de l'ONS ({title}), valeurs ({chosen}).",
            ),
            as_of=released,
        ),
    )
    return result, released


async def get_series(
    series_id: str,
    dataset: str | None = None,
    frequency: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesResult:
    lang = normalize_lang(lang)
    result, _ = await _series(series_id, dataset, frequency, start_period, end_period, last_n, lang)
    return result


async def get_indicator(
    indicator: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> IndicatorResult:
    lang = normalize_lang(lang)
    name = indicator.strip().lower()
    spec = constants.INDICATORS.get(name)
    if spec is None:
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {', '.join(constants.INDICATORS)}. "
            "For any other ONS series use ons_search_series and ons_get_series.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {', '.join(constants.INDICATORS)}. "
            "Pour toute autre série de l'ONS, utilisez ons_search_series et ons_get_series.",
            lang,
        )
    if last_n is None and start_period is None:
        last_n = {"monthly": 24, "quarterly": 12, "annual": 10}[spec.frequency]
    series, _ = await _series(
        spec.series_id, spec.dataset, spec.frequency, start_period, end_period, last_n, lang
    )
    if spec.dataset == "LMS":
        series.notes.append(
            pick(
                lang,
                "Labour market (LMS) months are three-month periods: 2026-07 is May to July 2026.",
                "Les mois du marché du travail (LMS) sont des périodes de trois mois : 2026-07 "
                "va de mai à juillet 2026.",
            )
        )
    data = series.model_dump(exclude={"available_frequencies", "other_datasets"})
    data["provenance"] = series.provenance
    data["observations"] = series.observations
    return IndicatorResult(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        canada_counterpart=pick(lang, spec.canada_en, spec.canada_fr),
        **data,
    )
