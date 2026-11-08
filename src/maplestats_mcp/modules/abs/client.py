"""Client for the Australian Bureau of Statistics Data API (data.api.abs.gov.au).

Checked live on 2026-11-08 with the project's User-Agent, no key (the user
guide: "As of the 29th of November 2024, Data API keys have been removed"):

- `dataflow/ABS/all/latest` (SDMX-JSON 1.0; structures answer 406 to a CSV
  Accept) lists 1,228 dataflows, English only, about 2.7 MB.
- `dataflow/ABS/{id}/latest?references=all&detail=referencepartial` gives the
  structure and two "Actual" constraints, one per release version (CR_A_CPI,
  CR_B_CPI); shared/sdmx.py merges their codes.
- `data/ABS,{id},/{key}` with `application/vnd.sdmx.data+csv;labels=both`
  gives SDMX-CSV 1.0 (a DATAFLOW column, "code: label" cells), newest first;
  `format=csvfilewithlabels` gives the same as a plain CSV. No data answers
  404 "NoRecordsFound". The CPI writes Australia as 50, other datasets AUS.
- Retail Trade (RT) stops at 2025-06; it is not a preset.

Values checked against the ABS release pages on 2026-11-08: CPI 4.3% and
trimmed mean 3.6% in the 12 months to September 2026; unemployment rate 4.7%
and employment-to-population 63.6% (September 2026, seasonally adjusted);
GDP +0.4% in 2026 Q2.

No rate limit is published; requests are spaced and cached, without retries.
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.abs import constants
from maplestats_mcp.modules.abs.schemas import (
    Code,
    DataResult,
    DataRow,
    DatasetSearch,
    DatasetStructure,
    DatasetSummary,
    Dimension,
    DimensionValue,
    IndicatorResult,
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
        "The ABS loads each dataset after its release (labour force and CPI monthly, national "
        "accounts and wages quarterly); the beta API may lag the ABS website."
    ),
    "fr": (
        "L'ABS charge chaque jeu de données après sa publication (population active et IPC "
        "chaque mois, comptes nationaux et salaires chaque trimestre) ; l'API bêta peut être en "
        "retard sur le site de l'ABS."
    ),
}

_DATASET = re.compile(r"^(?:ABS[,:])?([A-Za-z0-9_]+)$", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"the", "of", "and", "in", "for", "by", "on", "to", "a", "an", "data", "dataset",
     "datasets", "australia", "australian", "abs"}
)  # fmt: skip
_SERIES_ATTRIBUTES = ("UNIT_MEASURE", "BASE_PERIOD")
_PRESET_FLOWS = frozenset(spec.dataflow for spec in constants.INDICATORS.values())


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The ABS Data API did not answer ({url}): {detail}. Try again in a minute.",
        f"l'API de données de l'ABS n'a pas répondu ({url}) : {detail}. Réessayez dans une minute.",
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
    headers = request_headers(url, {"Accept": accept})
    try:
        response = await _client.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        _raise_unavailable(url, f"{type(exc).__name__}: {exc}", lang)
    raise_if_cloudflare_challenge(response)
    status = response.status_code
    if status < 400:
        return response
    if status == 404:
        raise_localized(NotFound, not_found[0], not_found[1], lang)
    if status == 429 or status >= 500:
        _raise_unavailable(url, f"HTTP {status}", lang)
    body = response.text[:300].strip()
    raise_localized(
        UpstreamError,
        f"The ABS Data API answered HTTP {status} for {url}: {body}",
        f"l'API de données de l'ABS a répondu HTTP {status} pour {url} : {body}",
        lang,
    )


def _provenance(
    url: str, cached: bool, schema: str, lang: str, coverage: str, limits: str | None = None
) -> Any:
    base = pick(lang, constants.LIMITS, constants.LIMITS_FR)
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=schema,
        freshness=_FRESHNESS[lang],
        coverage=coverage,
        limits=f"{limits} {base}" if limits else base,
        licence=pick(lang, constants.LICENCE, constants.LICENCE_FR),
        commercial_use="allowed",
        lang=lang,
    )


# --------------------------------------------------------------- catalogue


def _catalogue_url() -> str:
    return f"{constants.BASE_URL}dataflow/{constants.AGENCY}/all/latest"


async def _catalogue(lang: str) -> tuple[dict[str, dict[str, Any]], bool]:
    url = _catalogue_url()

    async def fetch() -> dict[str, dict[str, Any]]:
        response = await _get(
            url,
            None,
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
            not_found=(
                "The ABS dataflow list was not found.",
                "la liste des jeux de données de l'ABS est introuvable.",
            ),
            lang=lang,
        )
        payload = decode_json(response, url) or {}
        catalogue: dict[str, dict[str, Any]] = {}
        for flow in list_or_empty(payload.get("data") or {}, "dataflows"):
            if not isinstance(flow, dict) or not flow.get("id"):
                continue
            description = " ".join(
                html.unescape(_TAG.sub(" ", str(flow.get("description") or ""))).split()
            )
            catalogue[str(flow["id"])] = {
                "version": str(flow.get("version") or ""),
                "name": str(flow.get("name") or flow["id"]),
                "description": description[: constants.MAX_DESCRIPTION_CHARS * 3],
            }
        if not catalogue:
            raise_localized(
                UpstreamError,
                "The ABS dataflow list came back empty.",
                "la liste des jeux de données de l'ABS est revenue vide.",
                lang,
            )
        return catalogue

    return await cached_fetch("abs:catalogue", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _short(text: str) -> str:
    if len(text) <= constants.MAX_DESCRIPTION_CHARS:
        return text
    return text[: constants.MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS]


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
            "Give a few English words to search for, e.g. 'consumer price index', 'labour "
            "force', 'wage price index', 'national accounts'.",
            "donnez quelques mots en anglais à chercher, p. ex. « consumer price index », "
            "« labour force », « wage price index » (l'ABS publie en anglais).",
            lang,
        )
    catalogue, cached = await _catalogue(lang)
    scored = []
    for fid, info in catalogue.items():
        name_words = set(_WORD.findall(info["name"].lower()))
        text_words = set(_WORD.findall(info["description"].lower()))
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
            if word == fid.lower():
                score += 5
                hit = True
            matched += hit
        if not matched:
            continue
        score += 10 * (matched == len(words)) + 2 * (fid in _PRESET_FLOWS)
        scored.append((-score, len(info["name"]), fid))
    scored.sort()
    return DatasetSearch(
        query=query,
        total_matches=len(scored),
        datasets=[
            DatasetSummary(
                id=fid,
                version=catalogue[fid]["version"],
                name=catalogue[fid]["name"],
                description=_short(catalogue[fid]["description"]),
            )
            for _, _, fid in scored[:limit]
        ],
        provenance=_provenance(
            _catalogue_url(),
            cached,
            "abs.DatasetSearch",
            lang,
            pick(
                lang,
                "Every dataflow of the ABS Data API (beta). Names are in English only.",
                "Tous les jeux de données de l'API de l'ABS (bêta). Les noms n'existent qu'en "
                "anglais.",
            ),
        ),
    )


async def _dataflow(dataset: str, lang: str) -> tuple[str, dict[str, Any]]:
    match = _DATASET.match(dataset.strip())
    catalogue, _ = await _catalogue(lang)
    fid = match.group(1) if match else ""
    info = catalogue.get(fid) or next(
        (v for k, v in catalogue.items() if k.upper() == fid.upper()), None
    )
    if info is None:
        raise_localized(
            NotFound,
            f"{dataset!r} is not an ABS dataset id (e.g. CPI, LF, ANA_AGG). Search with "
            "abs_search_datasets.",
            f"{dataset!r} n'est pas un identifiant de jeu de données de l'ABS (p. ex. CPI, LF, "
            "ANA_AGG). Cherchez avec abs_search_datasets.",
            lang,
        )
    fid = next(k for k, v in catalogue.items() if v is info)
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
                f"No structure for ABS dataset {fid}.",
                f"aucune structure pour le jeu de données {fid} de l'ABS.",
            ),
            lang=lang,
        )
        try:
            return sdmx.parse_structure(decode_json(response, url), fid)
        except sdmx.SdmxFormatError as exc:
            raise_localized(UpstreamError, str(exc), f"structure de {fid} illisible : {exc}", lang)

    return await cached_fetch(f"abs:structure:{fid}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch)


def _example_key(structure: sdmx.Structure) -> str:
    key = sdmx.example_key(structure.dimensions, constants.AUSTRALIA[0])
    if constants.AUSTRALIA[0] in key.split("."):
        return key
    return sdmx.example_key(structure.dimensions, constants.AUSTRALIA[1])


def _data_url(fid: str, key: str) -> str:
    return f"{constants.BASE_URL}data/{constants.AGENCY},{fid},/{key}"


def _csv_url(fid: str, key: str, params: dict[str, Any]) -> str:
    return str(httpx.URL(_data_url(fid, key), params={**params, "format": "csvfilewithlabels"}))


def _citation(name: str, lang: str) -> str:
    today = date.today().isoformat()
    return pick(
        lang,
        f"Australian Bureau of Statistics, {name}, ABS Data API, {constants.BASE_URL} "
        f"(accessed on {today}). CC BY 4.0.",
        f"Australian Bureau of Statistics, {name}, API de données de l'ABS, "
        f"{constants.BASE_URL} (consulté le {today}). CC BY 4.0.",
    )


async def describe_dataset(dataset: str, lang: str = "en") -> DatasetStructure:
    lang = normalize_lang(lang)
    fid, info = await _dataflow(dataset, lang)
    structure, cached = await _structure(fid, lang)
    return DatasetStructure(
        id=fid,
        version=structure.version or info["version"],
        name=structure.name,
        description=_short(info["description"]),
        dimensions=[
            Dimension(
                id=dim.id,
                name=dim.name,
                position=position,
                codes=[
                    Code(id=c, name=n) for c, n in dim.codes[: constants.MAX_CODES_PER_DIMENSION]
                ],
                total_codes=len(dim.codes),
                truncated=len(dim.codes) > constants.MAX_CODES_PER_DIMENSION,
            )
            for position, dim in enumerate(structure.dimensions, start=1)
        ],
        key_template=".".join(d.id for d in structure.dimensions),
        example_key=_example_key(structure),
        citation=_citation(structure.name, lang),
        provenance=_provenance(
            str(httpx.URL(_structure_url(fid), params=_STRUCTURE_PARAMS)),
            cached,
            "abs.DatasetStructure",
            lang,
            pick(
                lang,
                "Codes are those the ABS availability constraints list as having data.",
                "Les codes sont ceux que les contraintes de disponibilité de l'ABS déclarent "
                "comme ayant des données.",
            ),
        ),
    )


# --------------------------------------------------------------------- data


async def _fetch(
    fid: str, key: str, params: dict[str, Any], structure: sdmx.Structure, lang: str
) -> tuple[list[sdmx.Series], bool]:
    url = _data_url(fid, key)

    async def fetch() -> str:
        response = await _get(
            url,
            params,
            accept=constants.DATA_ACCEPT,
            timeout=constants.DATA_TIMEOUT_SECONDS,
            not_found=(
                f"No data in ABS dataset {fid} for key {key!r}"
                + (" in the periods asked for" if params else "")
                + ". Check the codes with abs_describe_dataset.",
                f"aucune donnée dans le jeu {fid} de l'ABS pour la clé {key!r}"
                + (" pour les périodes demandées" if params else "")
                + ". Vérifiez les codes avec abs_describe_dataset.",
            ),
            lang=lang,
        )
        return response.text

    text, cached = await cached_fetch(
        f"abs:data:{fid}:{key}:{sorted(params.items())}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )
    try:
        return sdmx.parse_csv(text, structure.dimensions, _SERIES_ATTRIBUTES), cached
    except sdmx.SdmxFormatError as exc:
        raise_localized(
            UpstreamError, f"{fid}: {exc}", f"{fid} : colonnes SDMX-CSV inattendues.", lang
        )


def _series_info(series: sdmx.Series) -> SeriesInfo:
    region = series.dim("REGION")
    freq = series.dim("FREQ")
    adjustment = series.dim("TSEST")
    attrs = series.attributes
    obs = series.observations
    return SeriesInfo(
        key=series.key,
        region=region[1] if region else None,
        frequency=freq[1] if freq else None,
        adjustment=adjustment[1] if adjustment else None,
        unit=attrs["UNIT_MEASURE"][1] if "UNIT_MEASURE" in attrs else None,
        base_period=attrs["BASE_PERIOD"][1] if "BASE_PERIOD" in attrs else None,
        dimensions=[DimensionValue(id=d, code=c, label=label) for d, c, label in series.dims],
        observation_count=len(obs),
        latest_period=obs[-1][0] if obs else None,
        latest_value=obs[-1][1] if obs else None,
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
    fid, _ = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, lang)
    key = sdmx.check_key(
        key, structure.dimensions, fid, "abs_describe_dataset", constants.AUSTRALIA[0], lang
    )
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
            f"ABS dataset {fid} has no values for key {key!r} in the periods asked for.",
            f"le jeu {fid} de l'ABS n'a aucune valeur pour la clé {key!r} pour les périodes "
            "demandées.",
            lang,
        )
    limits: list[str] = []
    if len(fetched) > constants.MAX_SERIES:
        limits.append(
            pick(
                lang,
                f"First {constants.MAX_SERIES} of {len(fetched)} series; csv_url has them all.",
                f"{constants.MAX_SERIES} premières séries sur {len(fetched)} ; csv_url les "
                "contient toutes.",
            )
        )
        fetched = fetched[: constants.MAX_SERIES]
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
    return DataResult(
        dataset=fid,
        dataset_name=structure.name,
        key=key,
        series=series,
        rows=[
            DataRow(series_key=info.key, period=p, value=v, unit=info.unit, status=st)
            for info, s in zip(series, fetched, strict=True)
            for p, v, st in s.observations
        ],
        csv_url=_csv_url(fid, key, params),
        citation=_citation(structure.name, lang),
        notes=limits,
        provenance=_provenance(
            str(httpx.URL(_data_url(fid, key), params=params)),
            cached,
            "abs.DataResult",
            lang,
            pick(
                lang,
                f"ABS dataset {fid} ({structure.name}), key {key}.",
                f"Jeu de données {fid} de l'ABS ({structure.name}), clé {key}.",
            ),
            " ".join(limits) or None,
        ),
    )


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
            "For any other ABS series use abs_search_datasets and abs_get_data.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {', '.join(constants.INDICATORS)}. "
            "Pour toute autre série de l'ABS, utilisez abs_search_datasets et abs_get_data.",
            lang,
        )
    if last_n is None and start_period is None:
        last_n = spec.default_last_n
    data = await get_data(spec.dataflow, spec.key, start_period, end_period, last_n, lang)
    info = data.series[0]
    observations = [
        Observation(period=r.period, value=r.value) for r in data.rows if r.series_key == info.key
    ]
    return IndicatorResult(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        dataset=data.dataset,
        key=data.key,
        unit=info.unit,
        frequency=info.frequency,
        observations=observations,
        latest_period=info.latest_period,
        latest_value=info.latest_value,
        canada_counterpart=pick(lang, spec.canada_en, spec.canada_fr),
        csv_url=data.csv_url,
        citation=data.citation,
        notes=data.notes,
        provenance=data.provenance.model_copy(update={"schema_name": "abs.IndicatorResult"}),
    )
