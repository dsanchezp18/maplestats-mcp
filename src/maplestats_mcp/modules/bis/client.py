"""Client for the Bank for International Settlements statistics API (SDMX REST v2).

Checked live on 2026-10-26 with the project's User-Agent, no key:

- `structure/dataflow/BIS/*/*` lists 29 dataflows (28 datasets and the
  release calendar), each with `id`, `name` (English only), `version`
  (WS_TC is 2.0, the rest 1.0) and `structure`, the URN of its DSD. Only
  SDMX-JSON `version=1.0.0` is served; `version=1.0` answers 406.
- `structure/dataflow/BIS/{id}/{version}?references=all&detail=referencepartial`
  returns the DSD with its codelists cut to the codes that have data
  (WS_DSR's CL_AREA has 32 codes, the full list far more) and the concept
  schemes that name the dimensions. The cut is not exact: WS_CBPOL's
  frequency codelist lists only M, yet `D.CA` returns daily rates, so keys
  are not checked code by code against it. Several dataflows share one
  DSD (WS_LONG_CPI's call returned four dataflows), so the DSD is picked
  by the dataflow's own `structure` URN.
- `data/dataflow/BIS/{id}/{version}/{key}` with the SDMX-CSV 2.0 media
  type and `labels=both` gives one row per observation: headers like
  `REF_AREA:Reference area`, cells like `CA: Canada`. SDMX-JSON data
  answers 406. Some flows (WS_TC, WS_EER) also send series-level rows
  with an empty TIME_PERIOD and, for WS_TC, an empty FREQ, which carry
  attributes only. `c[TIME_PERIOD]=ge:2020-Q1+le:2020-Q2` filters periods
  (a bare year works on monthly data), `lastNObservations=n` keeps the
  last n per series, `*` or an empty part is a wildcard and `+` joins
  codes.
- A key with too few parts is not refused: `Q.CA` on WS_DSR returned every
  borrower sector, so the number of parts is checked here.
- No data for a key, an unknown code and an unknown dataflow all answer
  HTTP 404 with an SDMX-ML error ("No results for query", "No structures
  match query parameters").
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.bis import constants
from maplestats_mcp.modules.bis.schemas import (
    Code,
    ComparisonResult,
    CountrySeries,
    Dataset,
    DatasetList,
    DatasetStructure,
    Dimension,
    DimensionValue,
    Observation,
    Series,
    SeriesResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import decode_json, get_raw
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = {
    "en": (
        "Updated on the BIS release calendar: most datasets quarterly, policy rates and "
        "exchange rates weekly."
    ),
    "fr": (
        "Mis à jour selon le calendrier de diffusion de la BRI : la plupart des jeux de "
        "données chaque trimestre, les taux directeurs et les taux de change chaque semaine."
    ),
}

# SDMX reporting periods: 2026, 2026-Q1, 2026-S1, 2026-09, 2026-W40, 2026-09-30.
_PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|S[12]|W\d{2}|\d{2}(-\d{2})?))?$")
_DATASET_ID = re.compile(r"^[A-Z0-9_]+$")
_AREA = re.compile(r"^[A-Z0-9]{2}$")
_KEY_PART = re.compile(r"^(\*|[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*)?$")

# Aggregates are compared but never ranked against countries.
_AGGREGATES = {"XM", "1X", "4T", "5A", "5R"}


def _lang(lang: str) -> str:
    return normalize_lang(lang)


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _raise_unavailable(url: str, exc: Exception, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The BIS statistics API did not answer ({url}): {exc}. Try again in a minute.",
        f"l'API des statistiques de la BRI n'a pas répondu ({url}) : {exc}. Réessayez dans "
        "une minute.",
        lang,
    )


async def _get(
    url: str,
    params: dict[str, Any] | None,
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
    try:
        response = await get_raw(url, params=params, headers={"Accept": accept}, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(NotFound, not_found[0], not_found[1], lang)
        if status >= 500 or status == 429:
            _raise_unavailable(url, exc, lang)
        raise_localized(
            UpstreamError,
            f"The BIS statistics API answered HTTP {status} for {url}.",
            f"l'API des statistiques de la BRI a répondu HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(url, exc, lang)
    if response.status_code == 406:
        # get_raw hands 406 back unraised; here it means the media type was refused.
        raise_localized(
            UpstreamError,
            f"The BIS statistics API refused the requested format (HTTP 406) for {url}.",
            f"l'API des statistiques de la BRI a refusé le format demandé (HTTP 406) pour {url}.",
            lang,
        )
    return response


# ---------------------------------------------------------------- catalogue


def _catalogue_url() -> str:
    return f"{constants.BASE_URL}structure/dataflow/{constants.AGENCY}/*/*"


async def _catalogue(lang: str) -> tuple[dict[str, dict[str, str]], bool]:
    url = _catalogue_url()

    async def fetch() -> dict[str, dict[str, str]]:
        response = await _get(
            url,
            None,
            constants.STRUCTURE_ACCEPT,
            constants.STRUCTURE_TIMEOUT_SECONDS,
            (
                "The BIS dataflow list was not found.",
                "la liste des jeux de données de la BRI est introuvable.",
            ),
            lang,
        )
        payload = decode_json(response, url)
        flows = list_or_empty((payload or {}).get("data") or {}, "dataflows")
        catalogue = {
            str(f["id"]): {
                "name": str(f.get("name") or f["id"]),
                "version": str(f.get("version") or "1.0"),
                "structure": str(f.get("structure") or ""),
            }
            for f in flows
            if isinstance(f, dict) and f.get("id")
        }
        if not catalogue:
            raise_localized(
                UpstreamError,
                "The BIS dataflow list came back empty.",
                "la liste des jeux de données de la BRI est revenue vide.",
                lang,
            )
        return catalogue

    return await cached_fetch("bis:catalogue", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _note(dataset: str, lang: str) -> str:
    en, fr = constants.DATASET_NOTES.get(dataset, ("", ""))
    return pick(lang, en, fr) if en else ""


async def list_datasets(lang: str = "en") -> DatasetList:
    lang = _lang(lang)
    catalogue, cached = await _catalogue(lang)
    datasets = [
        Dataset(id=fid, name=info["name"], version=info["version"], description=_note(fid, lang))
        for fid, info in sorted(catalogue.items())
    ]
    return DatasetList(
        datasets=datasets,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_catalogue_url(),
            cached=cached,
            schema_name="bis.DatasetList",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Every dataflow of the BIS statistics API. Dataset names and codes are in "
                "English only upstream.",
                "Tous les jeux de données de l'API des statistiques de la BRI. Les noms et "
                "les libellés des codes n'existent qu'en anglais à la source.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def _dataflow(dataset: str, lang: str) -> tuple[str, dict[str, str]]:
    fid = dataset.strip().upper()
    if not fid or not _DATASET_ID.match(fid):
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not a BIS dataset id (e.g. WS_DSR, WS_SPP, WS_CBPOL).",
            f"{dataset!r} n'est pas un identifiant de jeu de données de la BRI (p. ex. "
            "WS_DSR, WS_SPP, WS_CBPOL).",
            lang,
        )
    catalogue, _ = await _catalogue(lang)
    info = catalogue.get(fid)
    if info is None:
        choices = ", ".join(sorted(catalogue))
        raise_localized(
            NotFound,
            f"{fid} is not a BIS dataset. Datasets: {choices}.",
            f"{fid} n'est pas un jeu de données de la BRI. Jeux de données : {choices}.",
            lang,
        )
    return fid, info


# ---------------------------------------------------------------- structure


def _urn_key(urn: str) -> str:
    """'urn:...Codelist=BIS:CL_AREA(1.0)' -> 'BIS:CL_AREA(1.0)'."""
    return urn.split("=", 1)[-1]


def _structure_url(fid: str, version: str) -> str:
    return f"{constants.BASE_URL}structure/dataflow/{constants.AGENCY}/{fid}/{version}"


async def _structure(fid: str, info: dict[str, str], lang: str) -> tuple[dict[str, Any], bool]:
    url = _structure_url(fid, info["version"])
    params = {"references": "all", "detail": "referencepartial"}

    async def fetch() -> dict[str, Any]:
        response = await _get(
            url,
            params,
            constants.STRUCTURE_ACCEPT,
            constants.STRUCTURE_TIMEOUT_SECONDS,
            (
                f"No structure for BIS dataset {fid}.",
                f"aucune structure pour le jeu de données {fid} de la BRI.",
            ),
            lang,
        )
        data = (decode_json(response, url) or {}).get("data") or {}
        wanted = _urn_key(info["structure"])
        structures = [s for s in list_or_empty(data, "dataStructures") if isinstance(s, dict)]
        dsd = next(
            (
                s
                for s in structures
                if f"{s.get('agencyID')}:{s.get('id')}({s.get('version')})" == wanted
            ),
            structures[0] if len(structures) == 1 else None,
        )
        if dsd is None:
            raise_localized(
                UpstreamError,
                f"{fid}: the structure response has no data structure {wanted}.",
                f"{fid} : la réponse ne contient pas la structure {wanted}.",
                lang,
            )
        codelists = {
            f"{c.get('agencyID')}:{c.get('id')}({c.get('version')})": c
            for c in list_or_empty(data, "codelists")
            if isinstance(c, dict)
        }
        concepts: dict[str, str] = {}
        for scheme in list_or_empty(data, "conceptSchemes"):
            for concept in list_or_empty(scheme, "concepts"):
                if isinstance(concept, dict) and concept.get("id"):
                    concepts.setdefault(str(concept["id"]), str(concept.get("name") or ""))
        components = dsd.get("dataStructureComponents") or {}
        dims = list_or_empty(components.get("dimensionList") or {}, "dimensions")
        dimensions = []
        for dim in sorted(
            (d for d in dims if isinstance(d, dict)), key=lambda d: int(d.get("position") or 0)
        ):
            enumeration = (dim.get("localRepresentation") or {}).get("enumeration") or ""
            codelist = codelists.get(_urn_key(enumeration)) or {}
            codes = [
                [str(c["id"]), str(c.get("name") or c["id"])]
                for c in list_or_empty(codelist, "codes")
                if isinstance(c, dict) and c.get("id")
            ]
            dim_id = str(dim.get("id") or "")
            dimensions.append(
                {"id": dim_id, "name": concepts.get(dim_id) or dim_id, "codes": codes}
            )
        if not dimensions:
            raise_localized(
                UpstreamError,
                f"{fid}: the data structure lists no dimensions.",
                f"{fid} : la structure ne contient aucune dimension.",
                lang,
            )
        return {"dimensions": dimensions}

    return await cached_fetch(
        f"bis:structure:{fid}:{info['version']}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )


def _example_key(dimensions: list[dict[str, Any]]) -> str:
    """A key for Canada: the CA code where a dimension has one, the first code of
    a one-code dimension, a wildcard elsewhere."""
    parts = []
    for dim in dimensions:
        ids = [c[0] for c in dim["codes"]]
        if constants.CANADA in ids:
            parts.append(constants.CANADA)
        elif len(ids) == 1:
            parts.append(ids[0])
        else:
            parts.append("*")
    return ".".join(parts)


async def describe_dataset(dataset: str, lang: str = "en") -> DatasetStructure:
    lang = _lang(lang)
    fid, info = await _dataflow(dataset, lang)
    structure, cached = await _structure(fid, info, lang)
    dimensions = []
    for position, dim in enumerate(structure["dimensions"], start=1):
        codes = dim["codes"]
        dimensions.append(
            Dimension(
                id=dim["id"],
                name=dim["name"],
                position=position,
                codes=[
                    Code(id=c[0], name=c[1]) for c in codes[: constants.MAX_CODES_PER_DIMENSION]
                ],
                total_codes=len(codes),
                truncated=len(codes) > constants.MAX_CODES_PER_DIMENSION,
            )
        )
    return DatasetStructure(
        id=fid,
        name=info["name"],
        version=info["version"],
        description=_note(fid, lang),
        dimensions=dimensions,
        key_template=".".join(d["id"] for d in structure["dimensions"]),
        example_key=_example_key(structure["dimensions"]),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(
                httpx.URL(
                    _structure_url(fid, info["version"]),
                    params={"references": "all", "detail": "referencepartial"},
                )
            ),
            cached=cached,
            schema_name="bis.DatasetStructure",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Codes are those the BIS lists as having data in this dataset; the list can "
                "miss a few (WS_CBPOL lists monthly only, but D gives daily rates). Labels are "
                "English only.",
                "Les codes sont ceux que la BRI déclare comme ayant des données dans ce jeu ; "
                "la liste peut en omettre quelques-uns (WS_CBPOL n'indique que M, mais D donne "
                "les taux quotidiens). Libellés en anglais seulement.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# --------------------------------------------------------------------- data


def _check_periods(
    start_period: str | None, end_period: str | None, last_n: int | None, lang: str
) -> None:
    for name, value in (("start_period", start_period), ("end_period", end_period)):
        if value is not None and not _PERIOD.match(value.strip()):
            raise_localized(
                InvalidInput,
                f"{name} {value!r} is not an SDMX period (2026, 2026-Q1, 2026-09 or 2026-09-30).",
                f"{name} {value!r} n'est pas une période SDMX (2026, 2026-Q1, 2026-09 ou "
                "2026-09-30).",
                lang,
            )
    if last_n is not None and not 1 <= last_n <= constants.MAX_LAST_N:
        raise_localized(
            InvalidInput,
            f"last_n must be between 1 and {constants.MAX_LAST_N}.",
            f"last_n doit être compris entre 1 et {constants.MAX_LAST_N}.",
            lang,
        )


def _data_params(
    start_period: str | None, end_period: str | None, last_n: int | None
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    bounds = []
    if start_period:
        bounds.append(f"ge:{start_period.strip()}")
    if end_period:
        bounds.append(f"le:{end_period.strip()}")
    if bounds:
        params["c[TIME_PERIOD]"] = "+".join(bounds)
    if last_n is not None:
        params["lastNObservations"] = last_n
    return params


def _data_url(fid: str, version: str, key: str) -> str:
    return f"{constants.BASE_URL}data/dataflow/{constants.AGENCY}/{fid}/{version}/{key}"


def _check_key(key: str, dimensions: list[dict[str, Any]], fid: str, lang: str) -> str:
    template = ".".join(d["id"] for d in dimensions)
    parts = key.strip().split(".")
    if len(parts) != len(dimensions) or not all(_KEY_PART.match(p) for p in parts):
        raise_localized(
            InvalidInput,
            f"{key!r} is not a key for {fid}: it needs {len(dimensions)} parts in the order "
            f"{template}, each a code, codes joined by + or * for all (e.g. "
            f"{_example_key(dimensions)}). bis_describe_dataset lists the codes.",
            f"{key!r} n'est pas une clé de {fid} : il faut {len(dimensions)} parties dans "
            f"l'ordre {template}, chacune un code, des codes joints par + ou * pour tous "
            f"(p. ex. {_example_key(dimensions)}). bis_describe_dataset donne les codes.",
            lang,
        )
    return ".".join(p.upper() if p != "*" else p for p in parts)


def _max_series(key: str, dimensions: list[dict[str, Any]]) -> int:
    """Upper bound on the number of series a key can match (codes with data)."""
    total = 1
    for part, dim in zip(key.split("."), dimensions, strict=True):
        total *= len(part.split("+")) if part and part != "*" else max(1, len(dim["codes"]))
    return total


def _split(cell: str) -> tuple[str, str]:
    """'CA: Canada' -> ('CA', 'Canada'); a cell without a label is its own label."""
    code, sep, label = cell.partition(": ")
    return (code.strip(), label.strip()) if sep else (cell.strip(), cell.strip())


def _parse_csv(
    text: str, dimensions: list[dict[str, Any]]
) -> list[tuple[list[DimensionValue], dict[str, str], list[Observation]]]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return []
    columns = [h.split(":", 1)[0] for h in header]
    index = {c: i for i, c in enumerate(columns)}
    dim_ids = [d["id"] for d in dimensions]
    if (
        "TIME_PERIOD" not in index
        or "OBS_VALUE" not in index
        or any(d not in index for d in dim_ids)
    ):
        raise UpstreamError(f"unexpected SDMX-CSV columns: {', '.join(columns)}")

    series: dict[tuple[str, ...], tuple[list[DimensionValue], dict[str, str], list[Observation]]]
    series = {}
    attribute_rows: list[tuple[tuple[str, ...], dict[str, str]]] = []
    attribute_columns = ("TITLE_TS", "TITLE", "UNIT_MEASURE", "UNIT_MULT")

    for row in reader:
        if len(row) < len(columns):
            row = row + [""] * (len(columns) - len(row))
        values = [_split(row[index[d]]) for d in dim_ids]
        codes = tuple(v[0] for v in values)
        attrs = {
            c: row[index[c]].strip() for c in attribute_columns if c in index and row[index[c]]
        }
        period = row[index["TIME_PERIOD"]].strip()
        if not period:
            # A series-level row (attributes only); FREQ can be empty in it.
            attribute_rows.append((codes, attrs))
            continue
        entry = series.get(codes)
        if entry is None:
            dims = [
                DimensionValue(id=d, code=code, label=label)
                for d, (code, label) in zip(dim_ids, values, strict=True)
            ]
            entry = series[codes] = (dims, {}, [])
        for name, value in attrs.items():
            entry[1].setdefault(name, value)
        raw = row[index["OBS_VALUE"]].strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        if math.isfinite(value):
            entry[2].append(Observation(period=period, value=value))

    for codes, attrs in attribute_rows:
        for key, entry in series.items():
            if all(not a or a == b for a, b in zip(codes, key, strict=True)):
                for name, value in attrs.items():
                    entry[1].setdefault(name, value)
    return list(series.values())


async def _fetch_series(
    fid: str,
    info: dict[str, str],
    key: str,
    params: dict[str, Any],
    dimensions: list[dict[str, Any]],
    lang: str,
) -> tuple[list[Series], bool, str]:
    url = _data_url(fid, info["version"], key)
    # `format=csv` makes the same URL answer plain CSV (codes only) with no
    # Accept header, so it opens in a browser, Excel or read.csv as is.
    csv_url = str(httpx.URL(url, params={**params, "format": "csv"}))

    async def fetch() -> str:
        response = await _get(
            url,
            params,
            constants.DATA_ACCEPT,
            constants.DATA_TIMEOUT_SECONDS,
            (
                f"No data in BIS dataset {fid} for key {key}"
                + (" in the periods asked for" if params else "")
                + ". Check the codes with bis_describe_dataset.",
                f"aucune donnée dans le jeu {fid} de la BRI pour la clé {key}"
                + (" pour les périodes demandées" if params else "")
                + ". Vérifiez les codes avec bis_describe_dataset.",
            ),
            lang,
        )
        return response.text

    text, cached = await cached_fetch(
        f"bis:data:{fid}:{info['version']}:{key}:{sorted(params.items())}",
        constants.CACHE_TTL_DATA_SECONDS,
        fetch,
    )
    try:
        parsed = _parse_csv(text, dimensions)
    except UpstreamError as exc:
        raise_localized(
            UpstreamError,
            f"{fid}: {exc}",
            f"{fid} : colonnes SDMX-CSV inattendues.",
            lang,
        )
    result = []
    for dims, attrs, observations in parsed:
        observations.sort(key=lambda o: o.period)
        unit = attrs.get("UNIT_MEASURE")
        multiplier = attrs.get("UNIT_MULT")
        result.append(
            Series(
                key=".".join(d.code for d in dims),
                title=attrs.get("TITLE_TS") or attrs.get("TITLE"),
                dimensions=dims,
                unit=_split(unit)[1] if unit else None,
                unit_multiplier=_split(multiplier)[1] if multiplier else None,
                observations=observations,
                latest_period=observations[-1].period if observations else None,
                latest_value=observations[-1].value if observations else None,
            )
        )
    return result, cached, csv_url


def _too_broad(fid: str, key: str, bound: int, lang: str) -> NoReturn:
    raise_localized(
        InvalidInput,
        f"{fid} key {key} can match up to {bound:,} series. Name more codes, or add last_n or "
        "start_period to keep the answer small.",
        f"la clé {key} de {fid} peut correspondre à {fr_number(bound)} séries. Précisez des "
        "codes, ou ajoutez last_n ou start_period pour garder la réponse courte.",
        lang,
    )


async def get_series(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesResult:
    lang = _lang(lang)
    _check_periods(start_period, end_period, last_n, lang)
    fid, info = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, info, lang)
    dimensions = structure["dimensions"]
    key = _check_key(key, dimensions, fid, lang)
    # The bound multiplies the codes of every wildcard dimension, far above
    # the series that exist (A.CA.*.*.*.*.*.* on WS_CPMI_SYSTEMS bounds at
    # 13,248), so it only stops an unbounded history of many series, or a
    # key so open that even one period per series would be huge.
    bound = _max_series(key, dimensions)
    if bound > constants.MAX_KEY_BOUND or (bound > 50 and last_n is None and start_period is None):
        _too_broad(fid, key, bound, lang)

    params = _data_params(start_period, end_period, last_n)
    series, cached, csv_url = await _fetch_series(fid, info, key, params, dimensions, lang)
    series = [s for s in series if s.observations]
    if not series:
        raise_localized(
            NotFound,
            f"BIS dataset {fid} has no values for key {key} in the periods asked for.",
            f"le jeu {fid} de la BRI n'a aucune valeur pour la clé {key} pour les périodes "
            "demandées.",
            lang,
        )

    notes: list[str] = []
    total_series = len(series)
    if total_series > constants.MAX_SERIES:
        series = series[: constants.MAX_SERIES]
        notes.append(
            pick(
                lang,
                f"First {constants.MAX_SERIES} of {total_series} series; csv_url has them all.",
                f"{constants.MAX_SERIES} premières séries sur {total_series} ; csv_url les "
                "contient toutes.",
            )
        )
    total_obs = sum(len(s.observations) for s in series)
    if total_obs > constants.MAX_OBSERVATIONS:
        keep = max(1, constants.MAX_OBSERVATIONS // len(series))
        for s in series:
            s.observations = s.observations[-keep:]
        notes.append(
            pick(
                lang,
                f"{total_obs:,} observations; only the last {keep:,} of each series are "
                "returned. Narrow the periods, or read csv_url for everything.",
                f"{fr_number(total_obs)} observations ; seules les {fr_number(keep)} "
                "dernières de chaque série sont renvoyées. Réduisez les périodes, ou lisez "
                "csv_url pour tout obtenir.",
            )
        )

    return SeriesResult(
        dataset=fid,
        dataset_name=info["name"],
        key=key,
        series=series,
        csv_url=csv_url,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(fid, info["version"], key), params=params)),
            cached=cached,
            schema_name="bis.SeriesResult",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Periods without a value are left out. Code labels are English only.",
                "Les périodes sans valeur sont omises. Libellés des codes en anglais seulement.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# ---------------------------------------------------------------- comparison


def _areas(compare_with: list[str] | None, lang: str) -> list[str]:
    areas = [constants.CANADA]
    for raw in compare_with or []:
        name = raw.strip().upper().replace(" ", "_").replace("-", "_")
        if not name:
            continue
        for code in constants.GROUP_ALIASES.get(name, (name,)):
            if not _AREA.match(code):
                raise_localized(
                    InvalidInput,
                    f"{raw!r} is not a BIS area code or group. Use G7, EURO_AREA, or two-letter "
                    "codes such as US, GB, AU, NZ, SE (bis_describe_dataset lists them).",
                    f"{raw!r} n'est ni un code de zone de la BRI ni un groupe. Utilisez G7, "
                    "EURO_AREA ou des codes à deux lettres comme US, GB, AU, NZ, SE "
                    "(bis_describe_dataset les énumère).",
                    lang,
                )
            if code not in areas:
                areas.append(code)
    return areas


def _rank(countries: list[CountrySeries]) -> tuple[int | None, str | None, int | None]:
    """Canada's rank (1 = highest), in the period most compared economies report.

    Countries publish on different lags (Canada's house prices reached
    2026-Q2 while the euro area's stopped at 2026-Q1 on 2026-10-26), so the
    latest period of Canada alone would rank it against few of them.
    """
    ranked = [c for c in countries if c.area_code not in _AGGREGATES]
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
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> ComparisonResult:
    lang = _lang(lang)
    spec = constants.INDICATORS.get(indicator.strip().lower())
    if spec is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other BIS "
            "series use bis_get_series.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série de la BRI, utilisez bis_get_series.",
            lang,
        )
    name = indicator.strip().lower()
    _check_periods(start_period, end_period, last_n, lang)
    if last_n is None and start_period is None:
        # Keep the default answer small: the last five years of a quarterly series.
        last_n = 60 if spec.key.startswith("M.") else 20
    areas = _areas(compare_with, lang)
    fid, info = await _dataflow(spec.dataset, lang)
    structure, _ = await _structure(fid, info, lang)
    key = spec.key.format(area="+".join(areas))
    params = _data_params(start_period, end_period, last_n)
    series, cached, csv_url = await _fetch_series(
        fid, info, key, params, structure["dimensions"], lang
    )

    area_index = spec.key.split(".").index("{area}")
    by_area: dict[str, CountrySeries] = {}
    for s in series:
        area = s.dimensions[area_index]
        if not s.observations or area.code in by_area:
            continue
        by_area[area.code] = CountrySeries(
            area_code=area.code,
            area_name=area.label,
            key=s.key,
            observations=s.observations,
            latest_period=s.latest_period,
            latest_value=s.latest_value,
        )
    if constants.CANADA not in by_area:
        raise_localized(
            NotFound,
            f"The BIS has no {name} values for Canada in the periods asked for.",
            f"la BRI n'a aucune valeur {name} pour le Canada pour les périodes demandées.",
            lang,
        )
    # lastNObservations counts per series, so a series that ended long ago
    # (France's policy rate stops at 1998-12, when the euro area's starts)
    # still sends its last values; keep only Canada's window.
    first = by_area[constants.CANADA].observations[0].period
    for code in list(by_area):
        kept = [o for o in by_area[code].observations if o.period >= first]
        if not kept:
            del by_area[code]
        elif len(kept) < len(by_area[code].observations):
            by_area[code].observations = kept
    countries = [by_area[a] for a in areas if a in by_area]

    notes: list[str] = []
    missing = [a for a in areas if a not in by_area]
    if missing:
        notes.append(
            pick(
                lang,
                f"No values for: {', '.join(missing)} (not covered by {fid}, or no data in "
                "the periods asked for).",
                f"Aucune valeur pour : {', '.join(missing)} (non couverts par {fid}, ou sans "
                "données pour les périodes demandées).",
            )
        )
    if name == "policy_rate" and set(missing) & constants.EURO_AREA_MEMBERS:
        notes.append(
            pick(
                lang,
                "Euro area members have had no national policy rate since 1999; use EURO_AREA "
                "for the ECB's rate.",
                "Les pays de la zone euro n'ont plus de taux directeur national depuis 1999 ; "
                "utilisez EURO_AREA pour le taux de la BCE.",
            )
        )
    rank, rank_period, ranked = _rank(countries)
    return ComparisonResult(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        dataset=fid,
        countries=countries,
        canada_rank=rank,
        rank_period=rank_period,
        ranked_countries=ranked,
        csv_url=csv_url,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(fid, info["version"], key), params=params)),
            cached=cached,
            schema_name="bis.ComparisonResult",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                f"BIS dataset {fid} ({info['name']}), key {key}. Periods without a value "
                "are left out.",
                f"Jeu de données {fid} de la BRI ({info['name']}), clé {key}. Les périodes "
                "sans valeur sont omises.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )
