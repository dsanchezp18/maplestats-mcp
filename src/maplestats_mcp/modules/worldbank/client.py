"""Client for the World Bank Indicators API (v2), World Development Indicators only.

Checked live on 2026-10-03 with the project's User-Agent:

- `/v2/{lang}/sources/2/indicators?format=json&per_page=2000` lists all
  1,498 WDI indicators in one page (1.5 MB English, 1.1 MB French; the
  French page took 40 s). Names and topics are translated under `/fr/`;
  `sourceNote` (the definition) stays English, `sourceOrganization` is
  translated. `unit` is always "". 134 indicators have `topics: []`, and
  topic names carry trailing spaces ("Education ").
- `/v2/{lang}/country/CAN;USA;OED/indicator/{id}?format=json` returns
  `[header, rows]`: header has `page`, `pages`, `total`, `lastupdated`;
  each row has `countryiso3code`, `country.value`, `date` (a year string),
  `value` (null for a year without data, e.g. most years of SI.POV.GINI
  for Canada) and `decimal`. Rows come newest first, 50 per page unless
  `per_page` is raised. Semicolons join countries; `OED` is the World
  Bank's "OECD members" aggregate. `G7` is not a code (rejected).
- An unknown indicator, an unknown country code or a malformed `date`
  answers HTTP 200 with `[{"message": [{"id": "120", "key": "Invalid
  value", ...}]}]` instead of an error status.
- `date=2030:2031` (a range with no data) is ignored and every year comes
  back, and `frequency=Q` is ignored (WDI is annual), so the year range
  is also applied here rather than trusted to the API.
- The edge answered HTTP 502 (a Cloudflare "bad gateway" page) to most
  calls for several minutes after a burst; `api_get` retries 502 and the
  rate limit in constants.py keeps the pace low.
"""

from __future__ import annotations

from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.worldbank import constants
from maplestats_mcp.modules.worldbank.schemas import (
    CanadaSeriesResult,
    CountrySeries,
    IndicatorDetail,
    IndicatorSearchResult,
    IndicatorSummary,
    Observation,
    Topic,
    TopicList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import ERROR_KEYS, french_spacing
from maplestats_mcp.shared.i18n import t as i18n_text
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.search import tokenize

_FRESHNESS = {
    "en": "WDI is revised a few times a year; values are annual.",
    "fr": french_spacing(
        "Les WDI sont révisés quelques fois par année ; les valeurs sont annuelles."
    ),
}


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _text(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


def _error(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> ValueError:
    """The error to raise with `from`: English as before, French in the typed template."""
    return exc_cls(i18n_text(ERROR_KEYS[exc_cls.__name__], "fr", detail=fr) if lang == "fr" else en)


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _lang(lang: str) -> str:
    return "fr" if lang == "fr" else "en"


def _is_api_message(payload: Any) -> bool:
    """The API's error shape: HTTP 200 with [{"message": [...]}]."""
    return (
        isinstance(payload, list)
        and len(payload) >= 1
        and isinstance(payload[0], dict)
        and "message" in payload[0]
    )


def _api_message_text(payload: list[Any]) -> str:
    messages = list_or_empty(payload[0], "message")
    parts = [str(m.get("value") or m.get("key") or "") for m in messages if isinstance(m, dict)]
    return "; ".join(p for p in parts if p) or "the request was rejected"


def _raise_unavailable(url: str, exc: Exception, lang: str = "en") -> NoReturn:
    raise _error(
        UpstreamUnavailable,
        f"The World Bank API did not answer ({url}): {exc}. It is often slow or briefly "
        "unavailable; try again in a minute.",
        f"l'API de la Banque mondiale n'a pas répondu ({url}) : {exc}. Elle est souvent lente "
        "ou brièvement indisponible ; réessayez dans une minute.",
        lang,
    ) from exc


async def _get(url: str, params: dict[str, Any], timeout: float, lang: str = "en") -> Any:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    try:
        return await api_get(url, params=params, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500 or status == 429:
            _raise_unavailable(url, exc, lang)
        raise _error(
            UpstreamError,
            f"The World Bank API answered HTTP {status} for {url}.",
            f"l'API de la Banque mondiale a répondu HTTP {status} pour {url}.",
            lang,
        ) from exc
    except httpx.HTTPError as exc:
        _raise_unavailable(url, exc, lang)


# ---------------------------------------------------------------- catalogue


def _catalogue_url(lang: str) -> str:
    return f"{constants.BASE_URL}{lang}/sources/{constants.WDI_SOURCE_ID}/indicators"


async def _catalogue(lang: str) -> tuple[list[dict[str, Any]], bool]:
    lang = _lang(lang)
    url = _catalogue_url(lang)

    async def fetch() -> list[dict[str, Any]]:
        payload = await _get(
            url,
            {"format": "json", "per_page": 2000},
            constants.CATALOGUE_TIMEOUT_SECONDS,
            lang,
        )
        if _is_api_message(payload):
            message = _api_message_text(payload)
            _raise(
                UpstreamError,
                f"WDI indicator list: {message}",
                f"liste des indicateurs WDI : {message} (message de la source, en anglais)",
                lang,
            )
        if not isinstance(payload, list) or len(payload) < 2:
            _raise(
                UpstreamError,
                "WDI indicator list: unexpected response shape.",
                "liste des indicateurs WDI : forme de réponse inattendue.",
                lang,
            )
        rows = [r for r in (payload[1] or []) if isinstance(r, dict) and r.get("id")]
        if not rows:
            _raise(
                UpstreamError,
                "WDI indicator list came back empty.",
                "la liste des indicateurs WDI est revenue vide.",
                lang,
            )
        return rows

    return await cached_fetch(f"worldbank:wdi:{lang}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _topic_names(row: dict[str, Any]) -> list[str]:
    return [
        str(t.get("value") or "").strip()
        for t in list_or_empty(row, "topics")
        if isinstance(t, dict) and str(t.get("value") or "").strip()
    ]


def _topic_ids(row: dict[str, Any]) -> set[str]:
    return {str(t.get("id")) for t in list_or_empty(row, "topics") if isinstance(t, dict)}


async def list_topics(lang: str = "en") -> TopicList:
    lang = _lang(lang)
    rows, cached = await _catalogue(lang)
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for row in rows:
        for topic in list_or_empty(row, "topics"):
            if not isinstance(topic, dict) or not topic.get("id"):
                continue
            topic_id = str(topic["id"])
            counts[topic_id] = counts.get(topic_id, 0) + 1
            names[topic_id] = str(topic.get("value") or "").strip()
    topics = [
        Topic(id=tid, name=f"{names[tid]} ({counts[tid]})")
        for tid in sorted(counts, key=lambda t: int(t) if t.isdigit() else 999)
    ]
    return TopicList(
        topics=topics,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_catalogue_url(lang) + "?format=json&per_page=2000",
            cached=cached,
            schema_name="worldbank.TopicList",
            freshness=_FRESHNESS[lang],
            coverage=_text(
                "Topics of World Development Indicators; the number of indicators is in "
                "brackets. 134 indicators have no topic and are found by words only.",
                "Thèmes des Indicateurs du développement dans le monde ; le nombre "
                "d'indicateurs est entre parenthèses. 134 indicateurs n'ont aucun thème et ne "
                "se trouvent que par mots.",
                lang,
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


def _resolve_topic(rows: list[dict[str, Any]], topic: str, lang: str = "en") -> tuple[str, str]:
    """Match `topic` to a topic id, by id or by words of its name."""
    wanted = topic.strip()
    names: dict[str, str] = {}
    for row in rows:
        for t in list_or_empty(row, "topics"):
            if isinstance(t, dict) and t.get("id"):
                names[str(t["id"])] = str(t.get("value") or "").strip()
    if wanted in names:
        return wanted, names[wanted]
    words = set(tokenize(wanted))
    for tid, name in names.items():
        if words and words <= set(tokenize(name)):
            return tid, name
    choices = ", ".join(
        f"{tid} {name}" for tid, name in sorted(names.items(), key=lambda x: int(x[0]))
    )
    _raise(
        InvalidInput,
        f"Unknown WDI topic {topic!r}. Topics: {choices}.",
        f"thème WDI inconnu {topic!r}. Thèmes : {choices}.",
        lang,
    )


def _score(row: dict[str, Any], words: list[str]) -> tuple[int, int]:
    name_words = set(tokenize(str(row.get("name") or "")))
    note_words = set(tokenize(str(row.get("sourceNote") or "")))
    code_words = set(tokenize(str(row.get("id") or "").replace(".", " ")))
    matched = sum(1 for w in words if w in name_words or w in note_words or w in code_words)
    in_name = sum(1 for w in words if w in name_words or w in code_words)
    return matched, in_name


async def search_indicators(
    query: str | None = None,
    topic: str | None = None,
    limit: int = 25,
    lang: str = "en",
) -> IndicatorSearchResult:
    lang = _lang(lang)
    if not (query and query.strip()) and not (topic and topic.strip()):
        _raise(
            InvalidInput,
            "Give words to search for (query), a topic, or both.",
            "donnez des mots à chercher (query), un thème (topic), ou les deux.",
            lang,
        )
    if limit < 1:
        _raise(
            InvalidInput,
            "limit must be at least 1.",
            "limit doit valoir au moins 1.",
            lang,
        )
    limit = min(limit, constants.MAX_SEARCH_RESULTS)
    rows, cached = await _catalogue(lang)

    topic_label: str | None = None
    if topic and topic.strip():
        topic_id, topic_label = _resolve_topic(rows, topic, lang)
        rows = [r for r in rows if topic_id in _topic_ids(r)]

    exact = None
    if query and query.strip():
        code = query.strip().upper()
        exact = next((r for r in rows if str(r.get("id")).upper() == code), None)
        words = tokenize(query)
        scored = []
        for row in rows:
            matched, in_name = _score(row, words)
            # Every word must appear somewhere: "GDP growth" must not list all
            # 250 GDP indicators ahead of the growth rate.
            if words and matched == len(words):
                scored.append((-in_name, len(str(row.get("name") or "")), row))
        scored.sort(key=lambda item: (item[0], item[1]))
        matches = [row for _, _, row in scored]
        if exact is not None:
            matches = [exact] + [r for r in matches if r is not exact]
    else:
        matches = sorted(rows, key=lambda r: str(r.get("name") or ""))

    indicators = [
        IndicatorSummary(id=str(r["id"]), name=str(r.get("name") or ""), topics=_topic_names(r))
        for r in matches[:limit]
    ]
    return IndicatorSearchResult(
        query=query,
        topic=topic_label,
        indicators=indicators,
        total_matches=len(matches),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_catalogue_url(lang) + "?format=json&per_page=2000",
            cached=cached,
            schema_name="worldbank.IndicatorSearchResult",
            freshness=_FRESHNESS[lang],
            limits=_text(
                f"First {len(indicators)} of {len(matches)} matches.",
                f"{len(indicators)} premiers résultats sur {len(matches)}.",
                lang,
            ),
            coverage=_text(
                "World Development Indicators only (1,498 indicators); every word must "
                "appear in the name, code or definition.",
                "Indicateurs du développement dans le monde seulement (1\u00a0498 "
                "indicateurs) ; chaque mot doit figurer dans le nom, le code ou la "
                "définition (définitions en anglais).",
                lang,
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def _indicator_row(indicator: str, lang: str) -> tuple[dict[str, Any], bool]:
    code = indicator.strip().upper()
    if not code:
        _raise(
            InvalidInput,
            "indicator must not be empty (e.g. NY.GDP.MKTP.KD.ZG).",
            "indicator ne doit pas être vide (p. ex. NY.GDP.MKTP.KD.ZG).",
            lang,
        )
    rows, cached = await _catalogue(lang)
    row = next((r for r in rows if str(r.get("id")).upper() == code), None)
    if row is None:
        _raise(
            NotFound,
            f"{indicator!r} is not a World Development Indicators code. Find one with "
            "worldbank_search_indicators (e.g. NY.GDP.MKTP.KD.ZG for real GDP growth).",
            f"{indicator!r} n'est pas un code des Indicateurs du développement dans le monde. "
            "Trouvez-en un avec worldbank_search_indicators (p. ex. NY.GDP.MKTP.KD.ZG pour "
            "la croissance du PIB réel).",
            lang,
        )
    return row, cached


async def get_indicator(indicator: str, lang: str = "en") -> IndicatorDetail:
    lang = _lang(lang)
    row, cached = await _indicator_row(indicator, lang)
    note = str(row.get("sourceNote") or "").strip()
    return IndicatorDetail(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        definition=note,
        source_organization=str(row.get("sourceOrganization") or "").strip(),
        topics=_topic_names(row),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}{lang}/indicator/{row['id']}?format=json",
            cached=cached,
            schema_name="worldbank.IndicatorDetail",
            freshness=_FRESHNESS[lang],
            coverage=None
            if lang == "en"
            else "La définition n'existe qu'en anglais chez la Banque mondiale.",
            licence=_licence(lang),
            lang=lang,
        ),
    )


# --------------------------------------------------------------------- data


def _comparison_codes(compare_with: list[str] | None, lang: str = "en") -> list[str]:
    codes: list[str] = [constants.CANADA]
    allowed = set(constants.OECD_MEMBERS) | {constants.OECD_AGGREGATE}
    for raw in compare_with or []:
        key = raw.strip().upper().replace(" ", "_").replace("-", "_")
        if not key:
            continue
        expanded = constants.GROUP_ALIASES.get(key, (key,))
        for code in expanded:
            if code not in allowed:
                _raise(
                    InvalidInput,
                    f"{raw!r} is not a comparison this tool offers. Use G7, OECD (the "
                    "World Bank's OECD members aggregate), OECD_MEMBERS, or the ISO3 "
                    "code of an OECD member country (e.g. USA, GBR, AUS, MEX).",
                    f"{raw!r} n'est pas une comparaison offerte par cet outil. Utilisez G7, "
                    "OECD (l'agrégat de la Banque mondiale pour les membres de l'OCDE), "
                    "OECD_MEMBERS, ou le code ISO3 d'un pays membre de l'OCDE (p. ex. USA, "
                    "GBR, AUS, MEX).",
                    lang,
                )
            if code not in codes:
                codes.append(code)
    return codes


def _year(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _validate_years(
    start_year: int | None, end_year: int | None, most_recent: int | None, lang: str = "en"
) -> None:
    if most_recent is not None and (start_year is not None or end_year is not None):
        _raise(
            InvalidInput,
            "Use most_recent or start_year/end_year, not both.",
            "utilisez most_recent ou start_year/end_year, pas les deux.",
            lang,
        )
    if most_recent is not None and not 1 <= most_recent <= 100:
        _raise(
            InvalidInput,
            "most_recent must be between 1 and 100 years.",
            "most_recent doit être compris entre 1 et 100 ans.",
            lang,
        )
    for name, year in (("start_year", start_year), ("end_year", end_year)):
        if year is not None and not 1900 <= year <= 2100:
            _raise(
                InvalidInput,
                f"{name} must be a four-digit year, got {year}.",
                f"{name} doit être une année à quatre chiffres, reçu {year}.",
                lang,
            )
    if start_year is not None and end_year is not None and start_year > end_year:
        _raise(
            InvalidInput,
            "start_year is after end_year.",
            "start_year est postérieur à end_year.",
            lang,
        )


async def get_canada_series(
    indicator: str,
    compare_with: list[str] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    most_recent: int | None = None,
    lang: str = "en",
) -> CanadaSeriesResult:
    lang = _lang(lang)
    _validate_years(start_year, end_year, most_recent, lang)
    codes = _comparison_codes(compare_with, lang)
    row, _ = await _indicator_row(indicator, lang)
    code = str(row["id"])

    url = f"{constants.BASE_URL}{lang}/country/{';'.join(codes)}/indicator/{code}"
    params: dict[str, Any] = {
        "format": "json",
        "per_page": constants.PER_PAGE,
        "source": constants.WDI_SOURCE_ID,
    }
    if start_year is not None or end_year is not None:
        params["date"] = f"{start_year or 1960}:{end_year or 2100}"

    async def fetch() -> Any:
        payload = await _get(url, params, constants.DATA_TIMEOUT_SECONDS, lang)
        if _is_api_message(payload):
            message = _api_message_text(payload)
            _raise(
                InvalidInput,
                f"The World Bank API rejected the request: {message}.",
                f"l'API de la Banque mondiale a refusé la requête : {message} (message de la "
                "source).",
                lang,
            )
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict):
            _raise(
                UpstreamError,
                f"{code}: unexpected response shape from the World Bank API.",
                f"{code} : forme de réponse inattendue de l'API de la Banque mondiale.",
                lang,
            )
        header = payload[0]
        pages = _year(header.get("pages")) or 1
        if pages > 1:
            # Never seen with per_page=5000 (39 countries x 66 years is 2,574
            # rows), so a second page means the API changed; fail loudly.
            _raise(
                UpstreamError,
                f"{code}: the API split the series over {pages} pages.",
                f"{code} : l'API a réparti la série sur {pages} pages.",
                lang,
            )
        return payload

    payload, cached = await cached_fetch(
        f"worldbank:data:{lang}:{code}:{';'.join(codes)}:{params.get('date', '')}",
        constants.CACHE_TTL_DATA_SECONDS,
        fetch,
    )
    header: dict[str, Any] = payload[0]
    rows = [r for r in (payload[1] or []) if isinstance(r, dict)]

    by_country: dict[str, CountrySeries] = {}
    for r in rows:
        iso = str(r.get("countryiso3code") or "").upper()
        year = _year(r.get("date"))
        if iso not in codes or year is None:
            continue
        country = r.get("country") if isinstance(r.get("country"), dict) else {}
        series = by_country.setdefault(
            iso,
            CountrySeries(
                country_code=iso,
                country_name=str((country or {}).get("value") or iso),
                observations=[],
            ),
        )
        value = r.get("value")
        if value is None:
            continue
        # The API ignores a date range with no data and sends every year.
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        series.observations.append(Observation(year=year, value=float(value)))

    countries: list[CountrySeries] = []
    for iso in codes:
        series = by_country.get(iso)
        if series is None:
            continue
        series.observations.sort(key=lambda o: o.year)
        if most_recent is not None:
            series.observations = series.observations[-most_recent:]
        if series.observations:
            series.latest_year = series.observations[-1].year
            series.latest_value = series.observations[-1].value
        countries.append(series)

    canada = next((c for c in countries if c.country_code == constants.CANADA), None)
    if canada is None or not canada.observations:
        narrowed = bool(start_year or end_year or most_recent)
        _raise(
            NotFound,
            f"{code} ({row.get('name')}) has no value for Canada"
            + (" in the years asked for." if narrowed else ".")
            + " Try another indicator or a wider year range.",
            f"{code} ({row.get('name')}) n'a aucune valeur pour le Canada"
            + (" pour les années demandées." if narrowed else ".")
            + " Essayez un autre indicateur ou une période plus large.",
            lang,
        )

    notes: list[str] = []
    missing = [iso for iso in codes if iso not in by_country or not by_country[iso].observations]
    if missing:
        notes.append(
            _text(
                f"No values for: {', '.join(missing)}.",
                f"Aucune valeur pour : {', '.join(missing)}.",
                lang,
            )
        )
    if constants.OECD_AGGREGATE in codes:
        notes.append(
            "OED is the World Bank's aggregate for OECD members (weighted as the World Bank "
            "computes it), not a simple average and not the OECD's own figure."
            if lang == "en"
            else "OED est l'agrégat de la Banque mondiale pour les pays membres de l'OCDE "
            "(pondéré selon la Banque mondiale), et non une moyenne simple ni le chiffre de "
            "l'OCDE elle-même."
        )

    rank, rank_year, ranked = _rank(countries)
    as_of = header.get("lastupdated")
    return CanadaSeriesResult(
        indicator_id=code,
        indicator_name=str(row.get("name") or code),
        countries=countries,
        canada_rank=rank,
        rank_year=rank_year,
        ranked_countries=ranked,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(url, params=params)),
            cached=cached,
            schema_name="worldbank.CanadaSeriesResult",
            freshness=(
                f"Annual. WDI last updated {as_of}."
                if lang == "en"
                else f"Annuel. WDI mis à jour le {as_of}."
            )
            if as_of
            else _FRESHNESS[lang],
            coverage=(
                "Years without a value are left out."
                if lang == "en"
                else "Les années sans valeur sont omises."
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


def _rank(countries: list[CountrySeries]) -> tuple[int | None, int | None, int | None]:
    """Canada's rank (1 = highest), in the latest year most compared countries report.

    Canada's newest year often comes before its peers' (2025 for Canada while
    several OECD members stop at 2024), so ranking on Canada's latest year
    alone would compare it with only a few countries.
    """
    ranked = [c for c in countries if c.country_code != constants.OECD_AGGREGATE]
    canada = next((c for c in ranked if c.country_code == constants.CANADA), None)
    if canada is None or not canada.observations or len(ranked) < 2:
        return None, None, None
    by_year: dict[int, list[tuple[str, float]]] = {}
    for c in ranked:
        for o in c.observations:
            by_year.setdefault(o.year, []).append((c.country_code, o.value))
    canada_years = {o.year for o in canada.observations}
    year = max(canada_years, key=lambda y: (len(by_year.get(y, [])), y))
    values = by_year[year]
    if len(values) < 2:
        return None, year, len(values)
    canada_value = next(v for iso, v in values if iso == constants.CANADA)
    rank = 1 + sum(1 for _, v in values if v > canada_value)
    return rank, year, len(values)
