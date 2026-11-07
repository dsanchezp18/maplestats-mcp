"""Client for the US Bureau of Economic Analysis Data API.

Built on 2026-11-07 from the BEA API user guide (April 20, 2026), not from
live responses: the API answered a request without a UserID with
`{"BEAAPI": {"Request": ..., "Results": {"Error": {"APIErrorCode": "1",
"APIErrorDescription": "Invalid Request - Invalid API UserId."}}}}` (checked
live), and no UserID was available. scripts/smoke_test_bea.py calls every
function once MAPLE_BEA_API_KEY is set; run it before relying on the module.

What the guide documents, and what this client does about it:

- Every method is a GET on /api/data/ with `UserID`, `method` and
  `ResultFormat=JSON`. The UserID travels in the query string, and BEA
  echoes it back in `BEAAPI.Request.RequestParam`, so this client never
  passes the request echo on, masks the key in recorded requests
  (reproduce_code) and builds provenance URLs and error messages with a
  placeholder instead.
- Errors come inside a 200 body as `Results.Error` (`APIErrorCode`,
  `APIErrorDescription`); 1 is a bad UserID, 7 a throttled request (also HTTP
  429 with Retry-After). Some clients report `BEAAPI.Error` at the top level
  as well, so both places are read.
- Data rows: `DataValue` is a string with thousands commas, blank or a
  suppression code such as "(D)" or "(NA)"; `UNIT_MULT` is the power of ten;
  `NoteRef` (comma-separated) points at `Results.Notes[]` (`NoteRef`,
  `NoteText`). NIPA `TimePeriod` is 2026, 2026Q2 or 2026M9 (the guide shows
  "YYYYMx"), so months are padded here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp import config
from maplestats_mcp.modules.bea import constants
from maplestats_mcp.modules.bea.schemas import (
    DataResult,
    Dataset,
    DatasetList,
    ParameterValue,
    ParameterValueList,
    Row,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, redact_secrets, register_secret
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_VALUE = re.compile(r"^[A-Za-z0-9_,. -]{1,200}$")
_YEARS = re.compile(r"^(ALL|X|LAST5|LAST10|\d{4}(,\d{4})*)$", re.IGNORECASE)
_PERIOD = re.compile(r"^(\d{4})(?:([QM])(\d{1,2}))?$")
_MAX_VALUES = 2_000

_FRESHNESS = {
    "en": (
        "Updated on the BEA release schedule (https://www.bea.gov/news/schedule): GDP "
        "quarterly with monthly revisions, personal income and PCE prices monthly, trade "
        "in goods and services monthly, international transactions quarterly."
    ),
    "fr": (
        "Mis à jour selon le calendrier du BEA (https://www.bea.gov/news/schedule) : le PIB "
        "chaque trimestre avec des révisions mensuelles, le revenu personnel et les prix PCE "
        "chaque mois, le commerce de biens et services chaque mois, les transactions "
        "internationales chaque trimestre."
    ),
}


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _key(lang: str) -> str:
    key = config.get_bea_api_key()
    if not key:
        raise_localized(
            UpstreamUnavailable,
            "The BEA tools need a BEA API UserID, and this server has none: its operator "
            f"can register for free at {constants.SIGNUP_URL} and set MAPLE_BEA_API_KEY. "
            "Fix: say the BEA data are not available on this server; the same tables are on "
            "https://apps.bea.gov/iTable/. Do not answer from memory.",
            "les outils du BEA exigent un UserID de l'API du BEA, et ce serveur n'en a pas : "
            f"son exploitant peut s'inscrire gratuitement sur {constants.SIGNUP_URL} et "
            "définir MAPLE_BEA_API_KEY. Solution : dites que les données du BEA ne sont pas "
            "offertes sur ce serveur ; les mêmes tableaux sont sur "
            "https://apps.bea.gov/iTable/. Ne répondez pas de mémoire.",
            lang,
        )
    register_secret(key, constants.KEY_PLACEHOLDER)
    return key


def _public_url(params: dict[str, str]) -> str:
    """The request URL with the UserID replaced by a placeholder."""
    shown = {"UserID": constants.KEY_PLACEHOLDER, **params, "ResultFormat": "JSON"}
    return str(httpx.URL(constants.BASE_URL, params=shown))


def _raise_unavailable(detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The BEA Data API did not answer: {detail}. Try again in a minute.",
        f"l'API de données du BEA n'a pas répondu : {detail}. Réessayez dans une minute.",
        lang,
    )


def _error(payload: Any) -> tuple[str, str] | None:
    root = payload.get("BEAAPI") if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        return None
    results = root.get("Results")
    if isinstance(results, list):
        results = results[0] if results else {}
    for holder in (results, root):
        error = holder.get("Error") if isinstance(holder, dict) else None
        if isinstance(error, dict):
            return str(error.get("APIErrorCode") or ""), str(error.get("APIErrorDescription") or "")
    return None


async def _call(params: dict[str, str], lang: str) -> dict[str, Any]:
    """`BEAAPI.Results` for a request, or a typed error. Never the request echo."""
    key = _key(lang)
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    query = {"UserID": key, **params, "ResultFormat": "JSON"}
    try:
        payload = await api_get(constants.BASE_URL, params=query, timeout=constants.TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429 or status >= 500:
            _raise_unavailable(f"HTTP {status}", lang)
        raise_localized(
            UpstreamError,
            f"The BEA Data API answered HTTP {status}.",
            f"l'API de données du BEA a répondu HTTP {status}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(redact_secrets(type(exc).__name__ + ": " + str(exc)), lang)
    except ValueError:
        raise_localized(
            UpstreamError,
            "The BEA Data API did not answer in JSON.",
            "l'API de données du BEA n'a pas répondu en JSON.",
            lang,
        )
    error = _error(payload)
    if error:
        code, text = error
        text = redact_secrets(text)
        if code == "1":
            raise_localized(
                UpstreamUnavailable,
                f"The BEA refused this server's UserID ({text}). The operator should check "
                "MAPLE_BEA_API_KEY. Fix: say the BEA data are not available on this server "
                "right now. Do not answer from memory.",
                f"le BEA a refusé le UserID de ce serveur ({text}). L'exploitant doit "
                "vérifier MAPLE_BEA_API_KEY. Solution : dites que les données du BEA ne sont "
                "pas offertes sur ce serveur pour le moment. Ne répondez pas de mémoire.",
                lang,
            )
        if code == "7":
            _raise_unavailable(text, lang)
        lowered = text.lower()
        if "no data" in lowered or "not exist" in lowered or "no records" in lowered:
            raise_localized(
                NotFound,
                f"BEA error {code}: {text}",
                f"erreur {code} du BEA : {text}",
                lang,
            )
        raise_localized(
            InvalidInput,
            f"BEA error {code}: {text} Check the values with bea_list_parameter_values.",
            f"erreur {code} du BEA : {text} Vérifiez les valeurs avec bea_list_parameter_values.",
            lang,
        )
    root = payload.get("BEAAPI") if isinstance(payload, dict) else None
    results = root.get("Results") if isinstance(root, dict) else None
    if isinstance(results, list):
        results = results[0] if results else None
    if not isinstance(results, dict):
        raise_localized(
            UpstreamError,
            "The BEA Data API answered without BEAAPI.Results.",
            "l'API de données du BEA a répondu sans BEAAPI.Results.",
            lang,
        )
    return results


def _check(name: str, value: str, pattern: re.Pattern[str], lang: str) -> str:
    value = str(value).strip()
    if not pattern.match(value):
        raise_localized(
            InvalidInput,
            f"{name}={value!r} is not a valid BEA parameter value.",
            f"{name}={value!r} n'est pas une valeur de paramètre valide pour le BEA.",
            lang,
        )
    return value


def _years(years: list[int] | None, default: str, lang: str) -> str:
    if not years:
        return default
    this_year = datetime.now(UTC).year
    bad = [y for y in years if y < 1929 or y > this_year]
    if bad:
        raise_localized(
            InvalidInput,
            f"Years must fall between 1929 and {this_year}; got {bad}.",
            f"les années doivent être comprises entre 1929 et {this_year} ; reçu {bad}.",
            lang,
        )
    return ",".join(str(y) for y in sorted(set(years)))


def _value(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _date(period: str) -> str:
    match = _PERIOD.match(period.strip())
    if not match:
        return period
    year, kind, number = match.groups()
    if kind == "Q":
        return f"{year}-Q{int(number)}"
    if kind == "M":
        return f"{year}-{int(number):02d}"
    return year


def _int(raw: Any) -> int | None:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _text(row: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _production_time(results: dict[str, Any]) -> datetime | None:
    raw = results.get("UTCProductionTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=UTC)
    except ValueError:
        return None


async def _data(
    dataset: str,
    params: dict[str, str],
    title: str | None,
    extra_notes: list[str],
    lang: str,
) -> DataResult:
    request = {"method": "GetData", "DataSetName": dataset, **params}
    cache_key = "bea:data:" + "&".join(f"{k}={v}" for k, v in sorted(request.items()))

    async def fetch() -> dict[str, Any]:
        return await _call(request, lang)

    results, cached = await cached_fetch(cache_key, constants.CACHE_TTL_DATA_SECONDS, fetch)
    notes_by_ref = {
        str(n.get("NoteRef") or ""): str(n.get("NoteText") or "").strip()
        for n in list_or_empty(results, "Notes")
        if isinstance(n, dict)
    }
    data = [r for r in list_or_empty(results, "Data") if isinstance(r, dict)]
    if not data:
        raise_localized(
            NotFound,
            f"The BEA returned no rows for {dataset} {params}.",
            f"le BEA n'a renvoyé aucune ligne pour {dataset} {params}.",
            lang,
        )
    rows: list[Row] = []
    for raw in data[: constants.MAX_ROWS]:
        period = str(raw.get("TimePeriod") or "")
        value_text = str(raw.get("DataValue") if raw.get("DataValue") is not None else "").strip()
        refs = [r.strip() for r in str(raw.get("NoteRef") or "").split(",") if r.strip()]
        rows.append(
            Row(
                series=_text(raw, "SeriesCode", "TimeSeriesId", "Code"),
                description=_text(raw, "LineDescription", "TimeSeriesDescription"),
                line_number=_text(raw, "LineNumber"),
                geo_fips=_text(raw, "GeoFips"),
                geo_name=_text(raw, "GeoName"),
                indicator=_text(raw, "Indicator"),
                area_or_country=_text(raw, "AreaOrCountry"),
                frequency=_text(raw, "Frequency"),
                period=period,
                date=_date(period),
                value=_value(value_text),
                value_text=value_text,
                unit=_text(raw, "CL_UNIT"),
                unit_multiplier=_int(raw.get("UNIT_MULT")),
                metric=_text(raw, "METRIC_NAME", "Metric_Name"),
                notes=[notes_by_ref[r] for r in refs if notes_by_ref.get(r)],
            )
        )
    truncated = len(data) > constants.MAX_ROWS
    notes = [text for text in notes_by_ref.values() if text]
    notes.extend(extra_notes)
    if truncated:
        notes.append(
            pick(
                lang,
                f"First {constants.MAX_ROWS} of {len(data)} rows; ask for fewer years or one "
                "frequency.",
                f"{constants.MAX_ROWS} premières lignes sur {len(data)} ; demandez moins "
                "d'années ou une seule fréquence.",
            )
        )
    title = title or _text(results, "PublicTable", "Statistic")
    production = _production_time(results)
    return DataResult(
        dataset=dataset,
        query={k: v for k, v in request.items() if k != "method"},
        title=title,
        rows=rows,
        total_rows=len(data),
        truncated=truncated,
        notes=notes,
        production_time=production,
        release_schedule_url=constants.SCHEDULE_URL,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_public_url(request),
            cached=cached,
            schema_name="bea.DataResult",
            as_of=production,
            freshness=_FRESHNESS[lang],
            limits=pick(
                lang,
                f"Rows capped at {constants.MAX_ROWS}.",
                f"Lignes plafonnées à {constants.MAX_ROWS}.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# ---------------------------------------------------------------- discovery


async def list_datasets(lang: str = "en") -> DatasetList:
    lang = normalize_lang(lang)
    request = {"method": "GetDatasetList"}

    async def fetch() -> dict[str, Any]:
        return await _call(request, lang)

    results, cached = await cached_fetch("bea:datasets", constants.CACHE_TTL_LIST_SECONDS, fetch)
    datasets = [
        Dataset(name=str(d["DatasetName"]), description=str(d.get("DatasetDescription") or ""))
        for d in list_or_empty(results, "Dataset")
        if isinstance(d, dict) and d.get("DatasetName")
    ]
    if not datasets:
        raise_localized(
            UpstreamError,
            "The BEA dataset list came back empty.",
            "la liste des jeux de données du BEA est revenue vide.",
            lang,
        )
    return DatasetList(
        datasets=datasets,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_public_url(request),
            cached=cached,
            schema_name="bea.DatasetList",
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def list_parameter_values(
    dataset: str,
    parameter: str,
    filters: dict[str, str] | None = None,
    lang: str = "en",
) -> ParameterValueList:
    lang = normalize_lang(lang)
    dataset = _check("dataset", dataset, _NAME, lang)
    parameter = _check("parameter", parameter, _NAME, lang)
    clean = {
        _check("filter name", k, _NAME, lang): _check(k, v, _VALUE, lang)
        for k, v in (filters or {}).items()
    }
    if clean:
        request = {
            "method": "GetParameterValuesFiltered",
            "DataSetName": dataset,
            "TargetParameter": parameter,
            **clean,
        }
    else:
        request = {
            "method": "GetParameterValues",
            "DataSetName": dataset,
            "ParameterName": parameter,
        }
    cache_key = "bea:values:" + "&".join(f"{k}={v}" for k, v in sorted(request.items()))

    async def fetch() -> dict[str, Any]:
        return await _call(request, lang)

    results, cached = await cached_fetch(cache_key, constants.CACHE_TTL_LIST_SECONDS, fetch)
    values: list[ParameterValue] = []
    for item in list_or_empty(results, "ParamValue"):
        if not isinstance(item, dict):
            continue
        # GetParameterValues uses Key/Desc for most parameters; the guide's NIPA
        # TableName list is documented the same way, but some datasets name the
        # pair differently (TableName/Description), so take the first two fields.
        key = _text(item, "Key", "TableName", "Name")
        desc = _text(item, "Desc", "Description") or ""
        if key is None and item:
            first = list(item.values())
            key, desc = str(first[0]), str(first[1]) if len(first) > 1 else ""
        if key is not None:
            values.append(ParameterValue(key=key, description=desc))
    return ParameterValueList(
        dataset=dataset,
        parameter=parameter,
        filters=clean,
        values=values[:_MAX_VALUES],
        total_values=len(values),
        truncated=len(values) > _MAX_VALUES,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_public_url(request),
            cached=cached,
            schema_name="bea.ParameterValueList",
            licence=_licence(lang),
            lang=lang,
        ),
    )


# ---------------------------------------------------------------- data


async def get_nipa(
    table: str = "T10101",
    frequency: str = "Q",
    years: list[int] | None = None,
    lang: str = "en",
) -> DataResult:
    lang = normalize_lang(lang)
    table = _check("table", table.upper(), _NAME, lang)
    freqs = [f.strip().upper() for f in frequency.split(",") if f.strip()]
    if not freqs or any(f not in {"A", "Q", "M"} for f in freqs):
        raise_localized(
            InvalidInput,
            f"frequency must be A, Q, M or a comma list of them; got {frequency!r}.",
            f"frequency doit valoir A, Q, M ou une liste de ces valeurs ; reçu {frequency!r}.",
            lang,
        )
    default_years = ",".join(str(datetime.now(UTC).year - i) for i in range(4, -1, -1))
    known = constants.NIPA_TABLES.get(table)
    notes = [
        pick(
            lang,
            "NIPA quarterly and monthly dollar levels are seasonally adjusted at annual rates; "
            "percent changes are at annual rates unless the table says otherwise. US GDP is "
            "not directly comparable with Canada's in US dollars without a PPP or exchange "
            "rate conversion.",
            "Les niveaux trimestriels et mensuels en dollars des NIPA sont désaisonnalisés et "
            "annualisés ; les variations en pourcentage sont annualisées sauf indication "
            "contraire du tableau. Le PIB américain ne se compare pas directement à celui du "
            "Canada sans conversion à parité de pouvoir d'achat ou au taux de change.",
        )
    ]
    return await _data(
        "NIPA",
        {
            "TableName": table,
            "Frequency": ",".join(freqs),
            "Year": _years(years, default_years, lang),
        },
        pick(lang, known[0], known[1]) if known else None,
        notes,
        lang,
    )


async def get_regional(
    table: str = "SAINC1",
    line_code: str = "1",
    geo_fips: str = "STATE",
    years: list[int] | None = None,
    lang: str = "en",
) -> DataResult:
    lang = normalize_lang(lang)
    table = _check("table", table.upper(), _NAME, lang)
    line_code = _check("line_code", str(line_code).upper(), _NAME, lang)
    geo_fips = _check("geo_fips", geo_fips.upper(), _VALUE, lang)
    return await _data(
        "Regional",
        {
            "TableName": table,
            "LineCode": line_code,
            "GeoFips": geo_fips,
            "Year": _years(years, "LAST5", lang),
        },
        None,
        [],
        lang,
    )


async def get_international_transactions(
    indicators: list[str] | None = None,
    area_or_country: str = "Canada",
    frequency: str = "QSA",
    years: list[int] | None = None,
    lang: str = "en",
) -> DataResult:
    lang = normalize_lang(lang)
    chosen = [
        _check("indicator", i, _NAME, lang) for i in (indicators or constants.TRADE_INDICATORS)
    ]
    area = _check("area_or_country", area_or_country, _VALUE, lang)
    freq = frequency.strip().upper()
    if freq not in {"A", "QSA", "QNSA"}:
        raise_localized(
            InvalidInput,
            f"frequency must be A, QSA (quarterly, seasonally adjusted) or QNSA; got {frequency!r}.",
            f"frequency doit valoir A, QSA (trimestriel désaisonnalisé) ou QNSA ; reçu "
            f"{frequency!r}.",
            lang,
        )
    if len(chosen) > 1 and area.lower() in {"all", "allcountries"}:
        raise_localized(
            InvalidInput,
            "Several indicators need one country or area (BEA rule); give one indicator for "
            "AllCountries or All.",
            "plusieurs indicateurs exigent un seul pays ou une seule zone (règle du BEA) ; "
            "donnez un seul indicateur pour AllCountries ou All.",
            lang,
        )
    default_years = ",".join(str(datetime.now(UTC).year - i) for i in range(4, -1, -1))
    notes = [
        pick(
            lang,
            "International transactions are on a balance-of-payments basis, in US dollars; "
            "Statistics Canada's trade with the United States (cimt_ tools, customs basis, "
            "Canadian dollars) differs by definition and currency, so compare with care.",
            "Les transactions internationales sont établies selon la balance des paiements, en "
            "dollars américains ; le commerce du Canada avec les États-Unis selon Statistique "
            "Canada (outils cimt_, base douanière, dollars canadiens) diffère par la définition "
            "et la monnaie : comparez avec prudence.",
        )
    ]
    if freq != "A":
        notes.append(
            pick(
                lang,
                "QSA is seasonally adjusted, QNSA is not.",
                "QSA est désaisonnalisé, QNSA ne l'est pas.",
            )
        )
    return await _data(
        "ITA",
        {
            "Indicator": ",".join(chosen),
            "AreaOrCountry": area,
            "Frequency": freq,
            "Year": _years(years, default_years, lang),
        },
        None,
        notes,
        lang,
    )
