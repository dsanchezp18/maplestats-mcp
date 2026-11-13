"""Client for ILOSTAT's SDMX REST API (sdmx.ilo.org/rest), the International
Labour Organization's labour statistics.

Checked live on 2026-11-08 with the project's User-Agent, no key:

- `dataflow/ILO/all/latest` (SDMX-JSON) lists 1,215 dataflows, about 7.7 MB.
  With `Accept-Language: fr` names and descriptions come in French (one
  language per answer). Each flow has a LAST_UPDATE annotation written
  dd/mm/yyyy hh:mm:ss. Names ending "-- ILO modelled estimates, Nov. 2025"
  are the ILO's own model (gaps filled, aggregates, projections to 2027);
  the others are national survey figures harmonised by the ILO.
- `dataflow/ILO/{id}/latest?references=all&detail=referencepartial` gives
  the structure and an "Actual" content constraint listing the codes with
  data (shared/sdmx.py parses it). Keys run REF_AREA.FREQ.MEASURE then the
  breakdowns (SEX, AGE, CUR, ...).
- `data/ILO,{id},/{key}` with the SDMX-CSV 2.0 media type (`labels=both`)
  gives one row per observation with SOURCE ("LFS - Labour Force Survey"),
  notes and OBS_STATUS ("B: Break in series"). Monthly periods are written
  2026-M09; `startPeriod=2026-08` works for them. `format=csvfilewithlabels`
  gives the same as a plain CSV for a browser.
- A key with too few parts answers 422; no data answers 404 "No data is
  found"; an unknown area code answers 500 with an Oracle error (ORA-00936),
  so keys are checked against the constraint before a request.
- Monthly and quarterly series are not seasonally adjusted (Canada's
  unemployment rate: 7.3 in 2026-M08, 6.2 in 2026-M09).

Values checked against the ILO's own data API (rplumber.ilo.org, which feeds
ILOSTAT's data tools) on 2026-11-08: Canada's unemployment rate 6.819 (2025)
and participation rate 65.282 (2025), and US weekly hours 37.54 (2025).

The ILO publishes no rate limit; requests are spaced and cached, and sent
without retries (an unknown code's 500 would only be repeated).
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.ilo import constants
from maplestats_mcp.modules.ilo.schemas import (
    Code,
    ComparisonResult,
    CountrySeries,
    DataResult,
    DataRow,
    DatasetSearch,
    DatasetStructure,
    DatasetSummary,
    Dimension,
    DimensionValue,
    Observation,
    SeriesInfo,
)
from maplestats_mcp.shared import sdmx
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import (
    decode_json,
    new_client,
    raise_if_cloudflare_challenge,
    request_headers,
)
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_client = new_client(timeout=constants.DATA_TIMEOUT_SECONDS)

_FRESHNESS = {
    "en": (
        "ILOSTAT updates each dataset as countries report (LAST_UPDATE on each dataset); "
        "annual national figures usually lag the survey year by several months, and the ILO "
        "modelled estimates are revised once or twice a year."
    ),
    "fr": (
        "ILOSTAT met à jour chaque jeu de données à mesure que les pays transmettent leurs "
        "chiffres (LAST_UPDATE de chaque jeu) ; les chiffres nationaux annuels arrivent "
        "généralement plusieurs mois après l'année de l'enquête, et les estimations modélisées "
        "de l'OIT sont révisées une ou deux fois par an."
    ),
}

_DATASET = re.compile(r"^(?:ILO[,:])?(DF_[A-Za-z0-9_]+)$", re.IGNORECASE)
_AREA = re.compile(r"^[A-Z0-9]{2,4}$")
_AGGREGATE = re.compile(r"^X[0-9A-Z]{2}$")
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"the", "of", "and", "in", "for", "by", "on", "to", "a", "an", "data", "dataset",
     "datasets", "canada", "countries", "country", "ilo", "ilostat", "de", "des", "du", "la",
     "le", "les", "et", "par", "en", "au", "aux", "pays", "oit", "donnees"}
)  # fmt: skip
_SERIES_ATTRIBUTES = ("UNIT_MEASURE", "UNIT_MULT", "SOURCE")
_PRESET_FLOWS = frozenset(spec.dataflow for spec in constants.INDICATORS.values())


# -------------------------------------------------------------------- HTTP


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"ILOSTAT's SDMX API did not answer ({url}): {detail}. Try again in a minute.",
        f"l'API SDMX d'ILOSTAT n'a pas répondu ({url}) : {detail}. Réessayez dans une minute.",
        lang,
    )


async def _get(
    url: str,
    params: dict[str, Any] | None,
    *,
    accept: str,
    timeout: float,
    not_found: tuple[str, str],
    lang: str,
) -> httpx.Response:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    headers = request_headers(url, {"Accept": accept, "Accept-Language": lang})
    try:
        response = await _client.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        _raise_unavailable(url, f"{type(exc).__name__}: {exc}", lang)
    raise_if_cloudflare_challenge(response)
    status = response.status_code
    if status < 400:
        return response
    body = response.text[:300].strip()
    if status == 404:
        raise_localized(NotFound, not_found[0], not_found[1], lang)
    if status == 429 or status >= 502:
        _raise_unavailable(url, f"HTTP {status}", lang)
    # The server answers its IIS "403 - Forbidden: Access is denied" page now and
    # then to requests that pass a moment later (2026-11-08, from three networks):
    # throttling, so retry later rather than treat it as a changed answer.
    if status == 403 and "Access is denied" in response.text[:2000]:
        _raise_unavailable(url, "HTTP 403 (access denied for now)", lang)
    raise_localized(
        UpstreamError,
        f"ILOSTAT's SDMX API answered HTTP {status} for {url}: {body}",
        f"l'API SDMX d'ILOSTAT a répondu HTTP {status} pour {url} : {body}",
        lang,
    )


# --------------------------------------------------------------- catalogue


def _catalogue_url() -> str:
    return f"{constants.BASE_URL}dataflow/{constants.AGENCY}/all/latest"


def _plain(text: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


def _fold(text: str) -> str:
    """Lower case without accents, so "chomage" finds "chômage"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _updated(raw: str | None) -> datetime | None:
    """LAST_UPDATE is written dd/mm/yyyy hh:mm:ss ('25/10/2026 09:02:55')."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _is_modelled(name: str) -> bool:
    # Modelled-estimate flows are named "... -- ILO modelled estimates, Nov. 2025"
    # ("estimations modélisées" in French).
    lowered = _fold(name)
    return "modelled estimates" in lowered or "estimations modelisees" in lowered


def _flows(payload: Any) -> dict[str, dict[str, Any]]:
    """Dataflow id -> name, description, last update, search weight, modelled flag."""
    flows: dict[str, dict[str, Any]] = {}
    for flow in list_or_empty((payload or {}).get("data") or {}, "dataflows"):
        if not isinstance(flow, dict) or not flow.get("id"):
            continue
        notes = {
            str(a.get("type")): str(a.get("title") or "")
            for a in list_or_empty(flow, "annotations")
            if isinstance(a, dict)
        }
        name = str(flow.get("name") or flow["id"])
        try:
            weight = int(notes.get("SEARCH_WEIGHT") or 0)
        except ValueError:
            weight = 0
        flows[str(flow["id"])] = {
            "name": name,
            "description": _plain(str(flow.get("description") or ""))[
                : constants.MAX_DESCRIPTION_CHARS * 3
            ],
            "updated": notes.get("LAST_UPDATE") or None,
            "weight": weight,
            "modelled": _is_modelled(name),
        }
    return flows


async def _flow_info(fid: str, lang: str) -> dict[str, Any] | None:
    """One dataflow's catalogue entry. The 7.7 MB full list is refused now and then
    (403) while one dataflow's own definition still answers, so a lookup by id
    falls back to that instead of failing the whole call."""
    try:
        catalogue, _ = await _catalogue(lang)
    except UpstreamUnavailable:
        url = f"{constants.BASE_URL}dataflow/{constants.AGENCY}/{fid}/latest"

        async def fetch() -> dict[str, dict[str, Any]]:
            response = await _get(
                url,
                None,
                accept=constants.STRUCTURE_ACCEPT,
                timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
                not_found=(
                    f"{fid} is not an ILOSTAT dataset. Search with ilo_search_datasets.",
                    f"{fid} n'est pas un jeu de données d'ILOSTAT. Cherchez avec ilo_search_datasets.",
                ),
                lang=lang,
            )
            return _flows(decode_json(response, url) or {})

        catalogue, _ = await cached_fetch(
            f"ilo:flow:{fid}:{lang}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
        )
    return catalogue.get(fid)


async def _catalogue(lang: str) -> tuple[dict[str, dict[str, Any]], bool]:
    url = _catalogue_url()

    async def fetch() -> dict[str, dict[str, Any]]:
        response = await _get(
            url,
            None,
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
            not_found=(
                "The ILOSTAT dataflow list was not found.",
                "la liste des jeux de données d'ILOSTAT est introuvable.",
            ),
            lang=lang,
        )
        payload = decode_json(response, url) or {}
        catalogue = _flows(payload)
        if not catalogue:
            raise_localized(
                UpstreamError,
                "The ILOSTAT dataflow list came back empty.",
                "la liste des jeux de données d'ILOSTAT est revenue vide.",
                lang,
            )
        return catalogue

    return await cached_fetch(f"ilo:catalogue:{lang}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _short(text: str) -> str:
    if len(text) <= constants.MAX_DESCRIPTION_CHARS:
        return text
    return text[: constants.MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _iso(raw: str | None) -> str | None:
    updated = _updated(raw)
    return updated.isoformat() if updated else None


def _summary(fid: str, info: dict[str, Any]) -> DatasetSummary:
    return DatasetSummary(
        id=fid,
        name=info["name"],
        description=_short(info["description"]),
        last_updated=_iso(info["updated"]),
        modelled=info["modelled"],
    )


def _provenance(
    url: str,
    cached: bool,
    schema: str,
    lang: str,
    coverage: str,
    as_of: datetime | None = None,
    limits: str | None = None,
) -> Any:
    base_limits = pick(lang, constants.LIMITS, constants.LIMITS_FR)
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=schema,
        as_of=as_of,
        freshness=_FRESHNESS[lang],
        coverage=coverage,
        limits=f"{limits} {base_limits}" if limits else base_limits,
        licence=pick(lang, constants.LICENCE, constants.LICENCE_FR),
        commercial_use="allowed",
        lang=lang,
    )


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(_fold(text)) if len(w) > 1 and w not in _STOPWORDS]


async def search_datasets(query: str, limit: int = 10, lang: str = "en") -> DatasetSearch:
    lang = normalize_lang(lang)
    if not 1 <= limit <= constants.MAX_SEARCH_RESULTS:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_SEARCH_RESULTS}.",
            f"limit doit être compris entre 1 et {constants.MAX_SEARCH_RESULTS}.",
            lang,
        )
    words = _tokens(query)
    if not words:
        raise_localized(
            InvalidInput,
            "Give a few words to search for, e.g. 'unemployment rate', 'earnings', "
            "'hours worked', 'informal employment'.",
            "donnez quelques mots à chercher, p. ex. « taux de chômage », « gains », « heures "
            "travaillées », « emploi informel ».",
            lang,
        )
    catalogue, cached = await _catalogue(lang)
    scored = []
    for fid, info in catalogue.items():
        name_words = set(_WORD.findall(_fold(info["name"])))
        text_words = set(_WORD.findall(_fold(info["description"])))
        matched = 0
        score = 0.0
        for word in words:
            hit = False
            if word in name_words:
                score += 3
                hit = True
            elif len(word) >= 4 and any(n.startswith(word) for n in name_words):
                score += 2
                hit = True
            if word in text_words:
                score += 1
                hit = True
            if len(word) >= 3 and word in fid.lower():
                score += 2
                hit = True
            matched += hit
        if not matched:
            continue
        score += 10 * (matched == len(words))
        # The headline series behind the presets, and those ILOSTAT itself
        # weights up, first; long breakdowns (by sex, age and education) after.
        score += 2 * (fid in _PRESET_FLOWS) + info["weight"] / 200_000
        scored.append((-score, len(info["name"]), fid))
    scored.sort()
    return DatasetSearch(
        query=query,
        total_matches=len(scored),
        datasets=[_summary(fid, catalogue[fid]) for _, _, fid in scored[:limit]],
        provenance=_provenance(
            _catalogue_url(),
            cached,
            "ilo.DatasetSearch",
            lang,
            pick(
                lang,
                "Every ILOSTAT dataflow in the SDMX API, ILO modelled estimates included.",
                "Tous les jeux de données de l'API SDMX d'ILOSTAT, estimations modélisées de "
                "l'OIT comprises.",
            ),
        ),
    )


async def _dataflow(dataset: str, lang: str) -> tuple[str, dict[str, Any]]:
    match = _DATASET.match(dataset.strip())
    if not match:
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not an ILOSTAT dataset id (e.g. DF_UNE_DEAP_SEX_AGE_RT). "
            "ilo_search_datasets finds them.",
            f"{dataset!r} n'est pas un identifiant de jeu de données d'ILOSTAT (p. ex. "
            "DF_UNE_DEAP_SEX_AGE_RT). ilo_search_datasets les trouve.",
            lang,
        )
    fid = match.group(1).upper()
    info = await _flow_info(fid, lang)
    if info is None:
        raise_localized(
            NotFound,
            f"{fid} is not an ILOSTAT dataset. Search with ilo_search_datasets.",
            f"{fid} n'est pas un jeu de données d'ILOSTAT. Cherchez avec ilo_search_datasets.",
            lang,
        )
    return fid, info


# ---------------------------------------------------------------- structure


_STRUCTURE_PARAMS = {"references": "all", "detail": "referencepartial"}


def _structure_url(fid: str) -> str:
    return f"{constants.BASE_URL}dataflow/{constants.AGENCY}/{fid}/latest"


async def _structure(fid: str, lang: str) -> tuple[sdmx.Structure, bool]:
    url = _structure_url(fid)

    async def fetch() -> sdmx.Structure:
        response = await _get(
            url,
            _STRUCTURE_PARAMS,
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.STRUCTURE_TIMEOUT_SECONDS,
            not_found=(
                f"No structure for ILOSTAT dataset {fid}.",
                f"aucune structure pour le jeu de données {fid} d'ILOSTAT.",
            ),
            lang=lang,
        )
        try:
            return sdmx.parse_structure(decode_json(response, url), fid)
        except sdmx.SdmxFormatError as exc:
            raise_localized(UpstreamError, str(exc), f"structure de {fid} illisible : {exc}", lang)

    return await cached_fetch(
        f"ilo:structure:{fid}:{lang}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )


def _data_url(fid: str, key: str) -> str:
    return f"{constants.BASE_URL}data/{constants.AGENCY},{fid},/{key}"


def _csv_url(fid: str, key: str, params: dict[str, Any]) -> str:
    # `format=csvfilewithlabels` makes the same URL answer CSV with labels
    # without an Accept header, so it opens in a browser, Excel or read.csv.
    return str(httpx.URL(_data_url(fid, key), params={**params, "format": "csvfilewithlabels"}))


def _citation(name: str, updated: datetime | None, lang: str) -> str:
    year = (updated or datetime.now(UTC)).year
    today = datetime.now(UTC).date().isoformat()
    return pick(
        lang,
        f"International Labour Organization ({year}), {name}, ILOSTAT, "
        f"{constants.ILOSTAT_URL} (accessed on {today}).",
        f"Organisation internationale du Travail ({year}), {name}, ILOSTAT, "
        f"{constants.ILOSTAT_URL} (consulté le {today}).",
    )


async def describe_dataset(dataset: str, lang: str = "en") -> DatasetStructure:
    lang = normalize_lang(lang)
    fid, info = await _dataflow(dataset, lang)
    structure, cached = await _structure(fid, lang)
    dimensions = [
        Dimension(
            id=dim.id,
            name=dim.name,
            position=position,
            codes=[Code(id=c, name=n) for c, n in dim.codes[: constants.MAX_CODES_PER_DIMENSION]],
            total_codes=len(dim.codes),
            truncated=len(dim.codes) > constants.MAX_CODES_PER_DIMENSION,
        )
        for position, dim in enumerate(structure.dimensions, start=1)
    ]
    updated = _updated(structure.annotations.get("LAST_UPDATE") or info["updated"])
    example = sdmx.example_key(structure.dimensions, constants.CANADA)
    return DatasetStructure(
        id=fid,
        name=structure.name,
        description=_short(info["description"]),
        last_updated=updated.isoformat() if updated else None,
        modelled=info["modelled"],
        dimensions=dimensions,
        key_template=".".join(d.id for d in structure.dimensions),
        example_key=example,
        citation=_citation(structure.name, updated, lang),
        csv_url=_csv_url(fid, example, {"lastNObservations": 1}),
        provenance=_provenance(
            str(httpx.URL(_structure_url(fid), params=_STRUCTURE_PARAMS)),
            cached,
            "ilo.DatasetStructure",
            lang,
            pick(
                lang,
                "Codes are those ILOSTAT's availability constraint lists as having data in "
                "this dataset.",
                "Les codes sont ceux que la contrainte de disponibilité d'ILOSTAT déclare comme "
                "ayant des données dans ce jeu.",
            ),
            as_of=updated,
        ),
    )


# --------------------------------------------------------------------- data


async def _fetch(
    fid: str,
    key: str,
    params: dict[str, Any],
    structure: sdmx.Structure,
    lang: str,
) -> tuple[list[sdmx.Series], bool]:
    url = _data_url(fid, key)

    async def fetch() -> str:
        response = await _get(
            url,
            params,
            accept=constants.DATA_ACCEPT,
            timeout=constants.DATA_TIMEOUT_SECONDS,
            not_found=(
                f"No data in ILOSTAT dataset {fid} for key {key!r}"
                + (" in the periods asked for" if params else "")
                + ". Check the codes with ilo_describe_dataset.",
                f"aucune donnée dans le jeu {fid} d'ILOSTAT pour la clé {key!r}"
                + (" pour les périodes demandées" if params else "")
                + ". Vérifiez les codes avec ilo_describe_dataset.",
            ),
            lang=lang,
        )
        return response.text

    text, cached = await cached_fetch(
        f"ilo:data:{fid}:{key}:{sorted(params.items())}:{lang}",
        constants.CACHE_TTL_DATA_SECONDS,
        fetch,
    )
    try:
        return sdmx.parse_csv(text, structure.dimensions, _SERIES_ATTRIBUTES), cached
    except sdmx.SdmxFormatError as exc:
        raise_localized(
            UpstreamError, f"{fid}: {exc}", f"{fid} : colonnes SDMX-CSV inattendues.", lang
        )


def _series_info(series: sdmx.Series) -> SeriesInfo:
    area = series.dim("REF_AREA")
    freq = series.dim("FREQ")
    attrs = series.attributes
    obs = series.observations
    return SeriesInfo(
        key=series.key,
        ref_area=area[0] if area else None,
        ref_area_name=area[1] if area else None,
        frequency=freq[1] if freq else None,
        unit=attrs["UNIT_MEASURE"][1] if "UNIT_MEASURE" in attrs else None,
        unit_multiplier=attrs["UNIT_MULT"][1] if "UNIT_MULT" in attrs else None,
        source=attrs["SOURCE"][1] if "SOURCE" in attrs else None,
        dimensions=[DimensionValue(id=d, code=c, label=label) for d, c, label in series.dims],
        observation_count=len(obs),
        latest_period=obs[-1][0] if obs else None,
        latest_value=obs[-1][1] if obs else None,
    )


def _modelled_note(lang: str) -> str:
    return pick(
        lang,
        "ILO modelled estimates: the ILO's own model fills gaps and projects ahead (the latest "
        "years may be projections); they can differ from national figures.",
        "Estimations modélisées de l'OIT : le modèle de l'OIT comble les lacunes et fait des "
        "projections (les dernières années peuvent être projetées) ; elles peuvent différer "
        "des chiffres nationaux.",
    )


def _definitions_note(lang: str) -> str:
    return pick(
        lang,
        "ILOSTAT harmonises national survey figures to international definitions, so values "
        "can differ from national releases (Statistics Canada's Labour Force Survey for "
        "Canada); monthly and quarterly ILOSTAT series are not seasonally adjusted.",
        "ILOSTAT harmonise les chiffres des enquêtes nationales selon des définitions "
        "internationales : ils peuvent différer des publications nationales (l'Enquête sur la "
        "population active de Statistique Canada pour le Canada) ; les séries mensuelles et "
        "trimestrielles d'ILOSTAT ne sont pas désaisonnalisées.",
    )


async def get_data(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> DataResult:
    lang = normalize_lang(lang)
    sdmx.check_periods(start_period, end_period, last_n, constants.MAX_LAST_N, lang)
    fid, info = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, lang)
    key = sdmx.check_key(
        key, structure.dimensions, fid, "ilo_describe_dataset", constants.CANADA, lang
    )
    # The bound multiplies the codes of every wildcard dimension, far above the
    # series that exist, so it only stops an unbounded history of many series.
    bound = sdmx.max_series(key, structure.dimensions)
    if bound > constants.MAX_KEY_BOUND or (bound > 50 and last_n is None and start_period is None):
        raise_localized(
            InvalidInput,
            f"{fid} key {key!r} can match up to {bound:,} series. Name more codes, or add "
            "last_n or start_period to keep the answer small.",
            f"la clé {key!r} de {fid} peut correspondre à {fr_number(bound)} séries. Précisez "
            "des codes, ou ajoutez last_n ou start_period pour garder la réponse courte.",
            lang,
        )
    params = sdmx.data_params(start_period, end_period, last_n)
    fetched, cached = await _fetch(fid, key, params, structure, lang)
    if not fetched:
        raise_localized(
            NotFound,
            f"ILOSTAT dataset {fid} has no values for key {key!r} in the periods asked for.",
            f"le jeu {fid} d'ILOSTAT n'a aucune valeur pour la clé {key!r} pour les périodes "
            "demandées.",
            lang,
        )
    limits: list[str] = []
    total_series = len(fetched)
    if total_series > constants.MAX_SERIES:
        fetched = fetched[: constants.MAX_SERIES]
        limits.append(
            pick(
                lang,
                f"First {constants.MAX_SERIES} of {total_series} series; csv_url has them all.",
                f"{constants.MAX_SERIES} premières séries sur {total_series} ; csv_url les "
                "contient toutes.",
            )
        )
    total_rows = sum(len(s.observations) for s in fetched)
    if total_rows > constants.MAX_ROWS:
        keep = max(1, constants.MAX_ROWS // len(fetched))
        for s in fetched:
            del s.observations[:-keep]
        limits.append(
            pick(
                lang,
                f"{total_rows:,} observations; only the last {keep:,} of each series are "
                "returned. Narrow the periods, or read csv_url for everything.",
                f"{fr_number(total_rows)} observations ; seules les {fr_number(keep)} "
                "dernières de chaque série sont renvoyées. Réduisez les périodes, ou lisez "
                "csv_url pour tout obtenir.",
            )
        )
    series = [_series_info(s) for s in fetched]
    rows = [
        DataRow(
            series_key=info_row.key,
            ref_area=info_row.ref_area,
            period=period,
            value=value,
            unit=info_row.unit,
            frequency=info_row.frequency,
            status=status,
        )
        for info_row, s in zip(series, fetched, strict=True)
        for period, value, status in s.observations
    ]
    notes = [*limits, _modelled_note(lang) if info["modelled"] else _definitions_note(lang)]
    updated = _updated(structure.annotations.get("LAST_UPDATE") or info["updated"])
    return DataResult(
        dataset=fid,
        dataset_name=structure.name,
        key=key,
        series=series,
        rows=rows,
        csv_url=_csv_url(fid, key, params),
        citation=_citation(structure.name, updated, lang),
        notes=notes,
        provenance=_provenance(
            str(httpx.URL(_data_url(fid, key), params=params)),
            cached,
            "ilo.DataResult",
            lang,
            pick(
                lang,
                f"ILOSTAT dataset {fid} ({structure.name}), key {key}. Periods without a value "
                "are left out.",
                f"Jeu de données {fid} d'ILOSTAT ({structure.name}), clé {key}. Les périodes "
                "sans valeur sont omises.",
            ),
            as_of=updated,
            limits=" ".join(limits) or None,
        ),
    )


# ---------------------------------------------------------------- comparison


def _areas(compare_with: list[str] | None, lang: str) -> list[str]:
    areas = [constants.CANADA]
    for raw in compare_with or []:
        name = raw.strip().upper().replace(" ", "_").replace("-", "_")
        if not name:
            continue
        for code in constants.GROUP_ALIASES.get(name, (constants.ISO2_TO_ISO3.get(name, name),)):
            if not _AREA.match(code):
                raise_localized(
                    InvalidInput,
                    f"{raw!r} is not an ILOSTAT area code or group. Use G7, WORLD, EU27, or "
                    "ISO 3 codes such as USA, GBR, AUS, NZL, DEU (US and UK also work).",
                    f"{raw!r} n'est ni un code de zone d'ILOSTAT ni un groupe. Utilisez G7, "
                    "WORLD, EU27, ou des codes ISO 3 comme USA, GBR, AUS, NZL, DEU (US et UK "
                    "fonctionnent aussi).",
                    lang,
                )
            if code not in areas:
                areas.append(code)
    return areas


def _rank(countries: list[CountrySeries]) -> tuple[int | None, str | None, int | None]:
    """Canada's rank (1 = highest), in the period most compared countries report.

    Countries report on different lags, so Canada's latest period alone would
    rank it against few of them.
    """
    ranked = [c for c in countries if not _AGGREGATE.match(c.area_code)]
    canada = next((c for c in ranked if c.area_code == constants.CANADA), None)
    if canada is None or not canada.observations or len(ranked) < 2:
        return None, None, None
    by_period: dict[str, list[tuple[str, float]]] = {}
    for c in ranked:
        for o in c.observations:
            by_period.setdefault(o.period, []).append((c.area_code, o.value))
    period = max(
        (o.period for o in canada.observations), key=lambda p: (len(by_period.get(p, [])), p)
    )
    values = by_period[period]
    if len(values) < 2:
        return None, period, len(values)
    canada_value = next(v for code, v in values if code == constants.CANADA)
    return 1 + sum(1 for _, v in values if v > canada_value), period, len(values)


async def compare_countries(
    indicator: str,
    compare_with: list[str] | None = None,
    sex: str = "total",
    frequency: str = "annual",
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> ComparisonResult:
    lang = normalize_lang(lang)
    name = indicator.strip().lower()
    spec = constants.INDICATORS.get(name)
    if spec is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other ILOSTAT "
            "series use ilo_search_datasets and ilo_get_data.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série d'ILOSTAT, utilisez ilo_search_datasets et ilo_get_data.",
            lang,
        )
    freq = constants.FREQUENCIES.get(frequency.strip().lower())
    if freq is None or freq not in spec.frequencies:
        offered = ", ".join(k for k, v in constants.FREQUENCIES.items() if v in spec.frequencies)
        raise_localized(
            InvalidInput,
            f"{name} is published at these frequencies: {offered}.",
            f"{name} est publié aux fréquences suivantes : {offered}.",
            lang,
        )
    sex_code = constants.SEXES.get(sex.strip().lower())
    if sex_code is None:
        raise_localized(
            InvalidInput,
            "sex must be total, male or female.",
            "sex doit valoir total, male ou female.",
            lang,
        )
    if not spec.has_sex and sex_code != "SEX_T":
        raise_localized(
            InvalidInput,
            f"{name} has no breakdown by sex; leave sex as total.",
            f"{name} n'est pas ventilé par sexe ; laissez sex à total.",
            lang,
        )
    sdmx.check_periods(start_period, end_period, last_n, constants.MAX_LAST_N, lang)
    if last_n is None and start_period is None:
        last_n = {"A": 10, "Q": 12, "M": 24}[freq]
    areas = _areas(compare_with, lang)
    fid, info = await _dataflow(spec.dataflow, lang)
    structure, _ = await _structure(fid, lang)
    covered = set(structure.dimensions[0].code_ids())
    asked = [a for a in areas if a in covered]
    not_covered = [a for a in areas if a not in covered]
    if constants.CANADA not in asked:
        raise_localized(
            NotFound,
            f"ILOSTAT dataset {fid} has no data for Canada.",
            f"le jeu {fid} d'ILOSTAT n'a pas de données pour le Canada.",
            lang,
        )
    key = sdmx.check_key(
        spec.key.format(area="+".join(asked), freq=freq, sex=sex_code),
        structure.dimensions,
        fid,
        "ilo_describe_dataset",
        constants.CANADA,
        lang,
    )
    params = sdmx.data_params(start_period, end_period, last_n)
    fetched, cached = await _fetch(fid, key, params, structure, lang)

    by_area: dict[str, CountrySeries] = {}
    for series in fetched:
        area = series.dim("REF_AREA")
        if area is None or area[0] in by_area:
            continue
        info_row = _series_info(series)
        by_area[area[0]] = CountrySeries(
            area_code=area[0],
            area_name=area[1],
            key=series.key,
            unit=pick(lang, spec.unit_en, spec.unit_fr or spec.unit_en)
            if spec.unit_en
            else info_row.unit,
            source=info_row.source,
            observations=[
                Observation(period=p, value=v, status=s) for p, v, s in series.observations
            ],
            latest_period=info_row.latest_period,
            latest_value=info_row.latest_value,
        )
    if constants.CANADA not in by_area:
        raise_localized(
            NotFound,
            f"ILOSTAT has no {name} values for Canada in the periods asked for.",
            f"ILOSTAT n'a aucune valeur {name} pour le Canada pour les périodes demandées.",
            lang,
        )
    # lastNObservations counts per series, so a country that stopped reporting
    # long ago still sends its last values; keep only Canada's window.
    first = by_area[constants.CANADA].observations[0].period
    for code in list(by_area):
        kept = [o for o in by_area[code].observations if o.period >= first]
        if not kept:
            del by_area[code]
        else:
            by_area[code].observations = kept
    countries = [by_area[a] for a in areas if a in by_area]

    notes: list[str] = []
    missing = not_covered + [a for a in asked if a not in by_area]
    if missing:
        notes.append(
            pick(
                lang,
                f"No values for: {', '.join(missing)} (not covered by {fid}, or no data in the "
                "periods asked for).",
                f"Aucune valeur pour : {', '.join(missing)} (non couverts par {fid}, ou sans "
                "données pour les périodes demandées).",
            )
        )
    if any(o.status for c in countries for o in c.observations):
        notes.append(
            pick(
                lang,
                "Some observations carry a status (a break in series, an estimate): see each "
                "observation's status before comparing across years.",
                "Certaines observations portent un statut (rupture de série, estimation) : "
                "voyez le statut de chaque observation avant de comparer les années.",
            )
        )
    notes.append(_modelled_note(lang) if spec.modelled else _definitions_note(lang))
    rank, rank_period, ranked = _rank(countries)
    updated = _updated(structure.annotations.get("LAST_UPDATE") or info["updated"])
    frequency_name = next(k for k, v in constants.FREQUENCIES.items() if v == freq)
    return ComparisonResult(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        dataset=fid,
        dataset_name=structure.name,
        frequency=frequency_name,
        sex=next(k for k, v in constants.SEXES.items() if v == sex_code),
        countries=countries,
        canada_rank=rank,
        rank_period=rank_period,
        ranked_countries=ranked,
        csv_url=_csv_url(fid, key, params),
        citation=_citation(structure.name, updated, lang),
        notes=notes,
        provenance=_provenance(
            str(httpx.URL(_data_url(fid, key), params=params)),
            cached,
            "ilo.ComparisonResult",
            lang,
            pick(
                lang,
                f"ILOSTAT dataset {fid} ({structure.name}), key {key}.",
                f"Jeu de données {fid} d'ILOSTAT ({structure.name}), clé {key}.",
            ),
            as_of=updated,
        ),
    )
