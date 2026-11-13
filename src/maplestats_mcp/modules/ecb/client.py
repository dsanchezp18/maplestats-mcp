"""Client for the European Central Bank Data Portal API (SDMX 2.1 REST).

Checked live on 2026-11-07 with the project's User-Agent, no key:

- `dataflow/ECB` lists 105 dataflows as SDMX-ML 2.1 (SDMX-JSON structures
  answer 406), each with an English name and its data structure reference.
- `dataflow/ECB/{id}?references=all&detail=referencepartial` returns the
  data structure, concept schemes, full code lists (`referencepartial` is
  not honoured: FM's answer is 23 MB, its CL_PROVIDER_FM_ID alone 103,802
  codes) and a content constraint ("Allowed" cube region) listing the codes
  each dimension may take in that dataflow, which is what is shown.
- `data/{flow}/{key}?format=csvdata` gives one row per observation: KEY,
  one column per dimension, TIME_PERIOD (2026, 2026-Q3, 2026-10 or
  2026-11-05), OBS_VALUE, OBS_STATUS and the series attributes (TITLE,
  TITLE_COMPL, UNIT, UNIT_MULT). `detail=nodata` gives the same columns
  without observations, one row per series: the series list for a key.
  `startPeriod`, `endPeriod` and `lastNObservations` filter; an empty key
  part is a wildcard and `+` joins codes.
- A key with the wrong number of parts answers 400; no data for a key, an
  unknown code and an unknown dataflow answer 404. Structure calls answered
  504 once and then 200 within 1.5 s.
- The ICP dataflow (HICP, old classification) stops at 2025-12; HICP
  (COICOP 2018, data provider 4D0 = Eurostat) continues it.
- Terms: ESCB reuse policy, free reuse including commercial, "Source: ECB
  statistics"; third-party data excepted.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from maplestats_mcp.modules.ecb import constants
from maplestats_mcp.modules.ecb.schemas import (
    Code,
    Dataset,
    DatasetList,
    DatasetStructure,
    Dimension,
    Row,
    SeriesData,
    SeriesInfo,
    SeriesList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = {
    "en": (
        "Updated on the ECB's release calendar: exchange rates and €STR every business day, "
        "monetary and price statistics monthly."
    ),
    "fr": (
        "Mis à jour selon le calendrier de la BCE : taux de change et €STR chaque jour "
        "ouvrable, statistiques monétaires et de prix chaque mois."
    ),
}

_PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|S[12]|W\d{2}|\d{2}(-\d{2})?))?$")
_DATASET_ID = re.compile(r"^[A-Z0-9_]+$")
_KEY_PART = re.compile(r"^([A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*)?$")
_WORD = re.compile(r"[a-z0-9€]+")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _lang(lang: str) -> str:
    return normalize_lang(lang)


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _raise_unavailable(url: str, exc: Exception, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The ECB Data Portal API did not answer ({url}): {exc}. Try again in a minute.",
        f"l'API du portail de données de la BCE n'a pas répondu ({url}) : {exc}. Réessayez "
        "dans une minute.",
        lang,
    )


async def _get(
    url: str,
    params: dict[str, Any] | None,
    accept: str,
    timeout: float,
    not_found: tuple[str, str],
    bad_request: tuple[str, str],
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
        if status == 400:
            raise_localized(InvalidInput, bad_request[0], bad_request[1], lang)
        if status >= 500 or status == 429:
            _raise_unavailable(url, exc, lang)
        raise_localized(
            UpstreamError,
            f"The ECB Data Portal API answered HTTP {status} for {url}.",
            f"l'API du portail de données de la BCE a répondu HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(url, exc, lang)
    if response.status_code == 406:
        raise_localized(
            UpstreamError,
            f"The ECB Data Portal API refused the requested format (HTTP 406) for {url}.",
            f"l'API du portail de données de la BCE a refusé le format demandé (HTTP 406) pour "
            f"{url}.",
            lang,
        )
    return response


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _english_name(element: Any) -> str | None:
    """The English com:Name child of an SDMX-ML item, else its first name."""
    first = None
    for child in element:
        if _local(child.tag) == "Name":
            text = (child.text or "").strip()
            if child.get(_XML_LANG) == "en":
                return text
            first = first or text
    return first


# ---------------------------------------------------------------- catalogue


def _catalogue_url() -> str:
    return f"{constants.BASE_URL}dataflow/{constants.AGENCY}"


async def _catalogue(lang: str) -> tuple[dict[str, dict[str, str]], bool]:
    url = _catalogue_url()

    async def fetch() -> dict[str, dict[str, str]]:
        response = await _get(
            url,
            None,
            constants.STRUCTURE_ACCEPT,
            constants.STRUCTURE_TIMEOUT_SECONDS,
            (
                "The ECB dataflow list was not found.",
                "la liste des jeux de la BCE est introuvable.",
            ),
            ("The ECB refused the dataflow list request.", "la BCE a refusé la demande."),
            lang,
        )
        try:
            root = DefusedET.fromstring(response.content)
        except (DefusedXmlException, SyntaxError) as exc:
            raise UpstreamError(f"the ECB dataflow list is not readable XML: {exc}") from exc
        catalogue: dict[str, dict[str, str]] = {}
        for flow in root.iter():
            if _local(flow.tag) != "Dataflow" or not flow.get("id"):
                continue
            structure = ""
            for ref in flow.iter():
                if _local(ref.tag) == "Ref" and ref.get("class") in (None, "DataStructure"):
                    structure = str(ref.get("id") or "")
            fid = str(flow.get("id"))
            catalogue[fid] = {"name": _english_name(flow) or fid, "structure": structure}
        if not catalogue:
            raise UpstreamError("the ECB dataflow list came back empty")
        return catalogue

    return await cached_fetch("ecb:catalogue", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _note(dataset: str, lang: str) -> str | None:
    note = constants.DATASET_NOTES.get(dataset)
    return pick(lang, note[0], note[1]) if note else None


async def list_datasets(query: str | None = None, lang: str = "en") -> DatasetList:
    lang = _lang(lang)
    catalogue, cached = await _catalogue(lang)
    words = _WORD.findall((query or "").lower())
    datasets = []
    for fid, info in sorted(catalogue.items()):
        note = _note(fid, lang)
        hay = f"{fid} {info['name']} {constants.DATASET_NOTES.get(fid, ('', ''))[0]}"
        if note:
            hay += f" {note}"
        hay_words = _WORD.findall(hay.lower())
        if words and not all(any(h.startswith(w) for h in hay_words) for w in words):
            continue
        datasets.append(Dataset(id=fid, name=info["name"], description=note))
    # Described datasets first: they are the ones a comparison usually needs.
    datasets.sort(key=lambda d: (d.description is None, d.id))
    return DatasetList(
        datasets=datasets,
        total=len(catalogue),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=_catalogue_url(),
            cached=cached,
            schema_name="ecb.DatasetList",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Every dataflow of the ECB Data Portal. Names and code labels are English "
                "only upstream.",
                "Tous les jeux de données du portail de la BCE. Noms et libellés en anglais "
                "seulement à la source.",
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
            f"{dataset!r} is not an ECB dataset id (e.g. EXR, FM, HICP, BSI).",
            f"{dataset!r} n'est pas un identifiant de jeu de la BCE (p. ex. EXR, FM, HICP, BSI).",
            lang,
        )
    catalogue, _ = await _catalogue(lang)
    info = catalogue.get(fid)
    if info is None:
        raise_localized(
            NotFound,
            f"{fid} is not an ECB dataset. ecb_list_datasets lists them.",
            f"{fid} n'est pas un jeu de données de la BCE. ecb_list_datasets les énumère.",
            lang,
        )
    return fid, info


# ---------------------------------------------------------------- structure


@dataclass
class _Structure:
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    labels: dict[str, dict[str, str]] = field(default_factory=dict)  # FREQ, UNIT, UNIT_MULT


def _structure_url(fid: str) -> str:
    return f"{constants.BASE_URL}dataflow/{constants.AGENCY}/{fid}"


def parse_structure(body: bytes, fid: str, dsd_id: str) -> _Structure:
    """Dimensions in key order with the codes the dataflow allows, and labels."""
    root = DefusedET.fromstring(body)
    codelists: dict[str, list[tuple[str, str]]] = {}
    concepts: dict[str, str] = {}
    dsds: dict[str, list[tuple[int, str, str, str]]] = {}
    allowed: dict[str, set[str]] = {}
    for element in root.iter():
        tag = _local(element.tag)
        if tag == "Codelist":
            codelists[str(element.get("id"))] = [
                (str(code.get("id")), _english_name(code) or str(code.get("id")))
                for code in element
                if _local(code.tag) == "Code" and code.get("id")
            ]
        elif tag == "Concept" and element.get("id"):
            concepts.setdefault(str(element.get("id")), _english_name(element) or "")
        elif tag == "DataStructure" and element.get("id"):
            dims = []
            for dim in element.iter():
                if _local(dim.tag) != "Dimension" or not dim.get("id"):
                    continue
                codelist = ""
                concept = str(dim.get("id"))
                for ref in dim.iter():
                    if _local(ref.tag) != "Ref":
                        continue
                    if ref.get("class") == "Codelist":
                        codelist = str(ref.get("id"))
                dims.append((int(dim.get("position") or 0), concept, codelist, concept))
            dsds[str(element.get("id"))] = sorted(dims)
        elif tag == "ContentConstraint" and element.get("type", "Allowed") == "Allowed":
            attached = {
                str(ref.get("id"))
                for ref in element.iter()
                if _local(ref.tag) == "Ref" and ref.get("class") in ("Dataflow", None)
            }
            if attached and fid not in attached:
                continue
            for key_value in element.iter():
                if _local(key_value.tag) == "KeyValue" and key_value.get("id"):
                    values = {
                        (v.text or "").strip()
                        for v in key_value
                        if _local(v.tag) == "Value" and v.text
                    }
                    allowed.setdefault(str(key_value.get("id")), set()).update(values)
    dims = dsds.get(dsd_id) or (next(iter(dsds.values())) if len(dsds) == 1 else None)
    if not dims:
        raise UpstreamError(f"no data structure {dsd_id} in the answer")
    structure = _Structure()
    for _, dim_id, codelist, concept in dims:
        codes = codelists.get(codelist, [])
        if dim_id in allowed:
            codes = [c for c in codes if c[0] in allowed[dim_id]]
        structure.dimensions.append(
            {
                "id": dim_id,
                "name": concepts.get(concept) or dim_id,
                "codes": codes[: constants.MAX_CODES_PER_DIMENSION],
                "total": len(codes),
            }
        )
    for name in ("CL_FREQ", "CL_UNIT", "CL_UNIT_MULT"):
        structure.labels[name] = dict(codelists.get(name, []))
    # EST names its unit attribute UNIT_MEASURE (code PC) rather than UNIT.
    for code, label in codelists.get("CL_UNIT_MEASURE", []):
        structure.labels["CL_UNIT"].setdefault(code, label)
    return structure


async def _structure(fid: str, info: dict[str, str], lang: str) -> tuple[_Structure, bool]:
    url = _structure_url(fid)
    params = {"references": "all", "detail": "referencepartial"}

    async def fetch() -> _Structure:
        response = await _get(
            url,
            params,
            constants.STRUCTURE_ACCEPT,
            constants.STRUCTURE_TIMEOUT_SECONDS,
            (f"No structure for ECB dataset {fid}.", f"aucune structure pour le jeu {fid}."),
            (f"The ECB refused the structure of {fid}.", f"la BCE a refusé la structure de {fid}."),
            lang,
        )
        if len(response.content) > constants.MAX_STRUCTURE_BYTES:
            raise UpstreamError(f"the structure of {fid} is {len(response.content):,} bytes")
        try:
            return parse_structure(response.content, fid, info["structure"])
        except (DefusedXmlException, SyntaxError) as exc:
            raise UpstreamError(f"the structure of {fid} is not readable XML: {exc}") from exc

    return await cached_fetch(f"ecb:structure:{fid}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch)


def _example(fid: str) -> str | None:
    return next((i.key for i in constants.INDICATORS.values() if i.dataset == fid), None)


async def describe_dataset(
    dataset: str, code_query: str | None = None, lang: str = "en"
) -> DatasetStructure:
    lang = _lang(lang)
    fid, info = await _dataflow(dataset, lang)
    structure, cached = await _structure(fid, info, lang)
    words = _WORD.findall((code_query or "").lower())
    dimensions = []
    for position, dim in enumerate(structure.dimensions, start=1):
        codes = dim["codes"]
        if words:
            codes = [c for c in codes if all(w in f"{c[0]} {c[1]}".lower() for w in words)]
        dimensions.append(
            Dimension(
                id=dim["id"],
                name=dim["name"],
                position=position,
                codes=[Code(id=c[0], name=c[1]) for c in codes],
                total_codes=dim["total"],
                truncated=dim["total"] > len(dim["codes"]),
            )
        )
    return DatasetStructure(
        id=fid,
        name=info["name"],
        description=_note(fid, lang),
        dimensions=dimensions,
        key_template=".".join(d["id"] for d in structure.dimensions),
        example_key=_example(fid),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_structure_url(fid), params={"references": "all"})),
            cached=cached,
            schema_name="ecb.DatasetStructure",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Codes are those the ECB allows for this dataset (its content constraint); "
                f"each dimension lists at most {constants.MAX_CODES_PER_DIMENSION}, and "
                "code_query filters them. Labels are English only.",
                "Les codes sont ceux que la BCE autorise pour ce jeu (sa contrainte de "
                f"contenu) ; chaque dimension en donne au plus {constants.MAX_CODES_PER_DIMENSION}, "
                "et code_query les filtre. Libellés en anglais seulement.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# --------------------------------------------------------------------- data


def _check_key(key: str, structure: _Structure, fid: str, lang: str) -> str:
    dims = structure.dimensions
    template = ".".join(d["id"] for d in dims)
    parts = [p.strip() for p in key.strip().split(".")]
    parts = ["" if p == "*" else p for p in parts]
    if len(parts) != len(dims) or not all(_KEY_PART.match(p) for p in parts):
        raise_localized(
            InvalidInput,
            f"{key!r} is not a key for {fid}: it needs {len(dims)} parts in the order "
            f"{template}, each a code, codes joined by +, or empty (or *) for all. "
            "ecb_describe_dataset lists the codes.",
            f"{key!r} n'est pas une clé de {fid} : il faut {len(dims)} parties dans l'ordre "
            f"{template}, chacune un code, des codes joints par +, ou vide (ou *) pour tous. "
            "ecb_describe_dataset donne les codes.",
            lang,
        )
    return ".".join(p.upper() for p in parts)


def _check_periods(
    start_period: str | None, end_period: str | None, last_n: int | None, lang: str
) -> None:
    for name, value in (("start_period", start_period), ("end_period", end_period)):
        if value is not None and not _PERIOD.match(value.strip()):
            raise_localized(
                InvalidInput,
                f"{name} {value!r} is not a period (2026, 2026-Q1, 2026-09 or 2026-09-30).",
                f"{name} {value!r} n'est pas une période (2026, 2026-Q1, 2026-09 ou 2026-09-30).",
                lang,
            )
    if last_n is not None and not 1 <= last_n <= constants.MAX_LAST_N:
        raise_localized(
            InvalidInput,
            f"last_n must be between 1 and {constants.MAX_LAST_N}.",
            f"last_n doit être compris entre 1 et {constants.MAX_LAST_N}.",
            lang,
        )


def _period_start(period: str) -> str:
    """The first day of an SDMX period, as YYYY-MM-DD text: 2026-Q4 -> 2026-10-01."""
    year, _, rest = period.partition("-")
    if not rest:
        return f"{year}-01-01"
    if rest.startswith("Q"):
        return f"{year}-{3 * int(rest[1]) - 2:02d}-01"
    if rest.startswith("S"):
        return f"{year}-{6 * int(rest[1]) - 5:02d}-01"
    if rest.startswith("W"):
        return f"{year}-01-01"
    return period if len(period) == 10 else f"{period}-01"


def _data_url(fid: str, key: str) -> str:
    return f"{constants.BASE_URL}data/{fid}/{key}"


def _unit_label(structure: _Structure, unit: str | None, multiplier: str | None) -> str | None:
    if not unit:
        return None
    label = structure.labels["CL_UNIT"].get(unit, unit)
    if multiplier and multiplier not in ("0", ""):
        word = structure.labels["CL_UNIT_MULT"].get(multiplier)
        if word and word.lower() not in ("units", "unit"):
            label = f"{label}, {word.lower()}"
    return label


def _frequency(structure: _Structure, code: str | None) -> str | None:
    return structure.labels["CL_FREQ"].get(code or "", code) if code else None


def _read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


async def _fetch_csv(
    fid: str, key: str, params: dict[str, Any], lang: str, ttl: int
) -> tuple[list[dict[str, str]], bool]:
    url = _data_url(fid, key)

    async def fetch() -> list[dict[str, str]]:
        response = await _get(
            url,
            {**params, "format": "csvdata"},
            constants.DATA_ACCEPT,
            constants.DATA_TIMEOUT_SECONDS,
            (
                f"No data in ECB dataset {fid} for key {key}"
                + (" in the periods asked for" if "startPeriod" in params else "")
                + ". Check the codes with ecb_describe_dataset.",
                f"aucune donnée dans le jeu {fid} de la BCE pour la clé {key}"
                + (" pour les périodes demandées" if "startPeriod" in params else "")
                + ". Vérifiez les codes avec ecb_describe_dataset.",
            ),
            # The ECB's gateway answers a malformed query with an HTML "access
            # blocked" page and HTTP 400 (a future startPeriod did, 2026-11-07).
            (
                (
                    f"The ECB's gateway refused the query for {fid} key {key} (HTTP 400). Check "
                    "the key with ecb_describe_dataset and the periods."
                ),
                (
                    f"la passerelle de la BCE a refusé la requête pour la clé {key} de {fid} "
                    "(HTTP 400). Vérifiez la clé avec ecb_describe_dataset et les périodes."
                ),
            ),
            lang,
        )
        if len(response.content) > constants.MAX_SERIES_LIST_BYTES:
            raise_localized(
                InvalidInput,
                f"{fid} key {key} returns {len(response.content):,} bytes. Name more codes or "
                "narrow the periods.",
                f"la clé {key} de {fid} renvoie {fr_number(len(response.content))} octets. "
                "Précisez des codes ou réduisez les périodes.",
                lang,
            )
        return _read_csv(response.text)

    return await cached_fetch(f"ecb:data:{fid}:{key}:{sorted(params.items())}", ttl, fetch)


def _series_info(structure: _Structure, row: dict[str, str], fid: str) -> SeriesInfo:
    key = row.get("KEY", "")
    unit = _unit_label(structure, row.get("UNIT") or row.get("UNIT_MEASURE"), row.get("UNIT_MULT"))
    # Bilateral rates carry the quoted currency as UNIT ("Canadian dollar");
    # the reader needs the quote: CAD per EUR.
    if (
        fid == "EXR"
        and row.get("CURRENCY")
        and row.get("CURRENCY_DENOM")
        and row.get("EXR_TYPE", "").startswith(("SP", "RR"))
    ):
        unit = f"{row['CURRENCY']} per {row['CURRENCY_DENOM']}"
    return SeriesInfo(
        key=key.split(".", 1)[1] if key.startswith(f"{fid}.") else key,
        title=row.get("TITLE") or None,
        title_long=row.get("TITLE_COMPL") or None,
        frequency=_frequency(structure, row.get("FREQ")),
        unit=unit,
        unit_multiplier=row.get("UNIT_MULT") or None,
    )


async def search_series(
    dataset: str,
    key: str = "",
    query: str | None = None,
    limit: int = 50,
    lang: str = "en",
) -> SeriesList:
    lang = _lang(lang)
    if not 1 <= limit <= constants.MAX_LISTED_SERIES:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_LISTED_SERIES}.",
            f"limit doit être compris entre 1 et {constants.MAX_LISTED_SERIES}.",
            lang,
        )
    fid, info = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, info, lang)
    key = _check_key(key or "." * (len(structure.dimensions) - 1), structure, fid, lang)
    rows, cached = await _fetch_csv(
        fid, key, {"detail": "nodata"}, lang, constants.CACHE_TTL_STRUCTURE_SECONDS
    )
    words = _WORD.findall((query or "").lower())
    found = []
    for row in rows:
        hay = f"{row.get('KEY', '')} {row.get('TITLE', '')} {row.get('TITLE_COMPL', '')}".lower()
        hay_words = _WORD.findall(hay)
        if words and not all(any(h.startswith(w) for h in hay_words) for w in words):
            continue
        found.append(_series_info(structure, row, fid))
    notes = []
    if not found:
        notes.append(
            pick(
                lang,
                "No series matched. Titles are English (e.g. 'Canadian dollar', 'Total', "
                "'households').",
                "Aucune série trouvée. Les titres sont en anglais (p. ex. « Canadian dollar », "
                "« Total », « households »).",
            )
        )
    return SeriesList(
        dataset=fid,
        key=key,
        query=query,
        total_matches=len(found),
        series=found[:limit],
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(fid, key), params={"detail": "nodata"})),
            cached=cached,
            schema_name="ecb.SeriesList",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Series of the dataset that match the key (titles in English).",
                "Séries du jeu qui correspondent à la clé (titres en anglais).",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def get_series(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesData:
    lang = _lang(lang)
    _check_periods(start_period, end_period, last_n, lang)
    if start_period and _period_start(start_period.strip()) > datetime.now(UTC).date().isoformat():
        raise_localized(
            NotFound,
            f"start_period {start_period} is in the future: the ECB has no values for it yet.",
            f"start_period {start_period} est dans le futur : la BCE n'a pas encore de valeurs.",
            lang,
        )
    fid, info = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, info, lang)
    key = _check_key(key, structure, fid, lang)
    if start_period is None and last_n is None:
        # Without a window, a daily series sends decades; keep the default answer small.
        last_n = 260 if key.split(".")[0] in ("D", "B") else 60
        defaulted = True
    else:
        defaulted = False
    params: dict[str, Any] = {}
    if start_period:
        params["startPeriod"] = start_period.strip()
    if end_period:
        params["endPeriod"] = end_period.strip()
    if last_n is not None:
        params["lastNObservations"] = last_n
    rows, cached = await _fetch_csv(fid, key, params, lang, constants.CACHE_TTL_DATA_SECONDS)

    by_key: dict[str, tuple[SeriesInfo, list[Row]]] = {}
    for row in rows:
        series_id = row.get("KEY", "")
        entry = by_key.get(series_id)
        if entry is None:
            if len(by_key) >= constants.MAX_SERIES:
                continue
            series = _series_info(structure, row, fid)
            entry = by_key[series_id] = (series, [])
        try:
            value = float(row.get("OBS_VALUE") or "")
        except ValueError:
            continue
        period = row.get("TIME_PERIOD") or ""
        if not period or not math.isfinite(value):
            continue
        entry[1].append(
            Row(
                date=period,
                value=value,
                series_id=series_id,
                unit=entry[0].unit,
                frequency=entry[0].frequency,
            )
        )
    notes: list[str] = []
    total_series = len({r.get("KEY") for r in rows})
    if total_series > constants.MAX_SERIES:
        notes.append(
            pick(
                lang,
                f"First {constants.MAX_SERIES} of {total_series} series; csv_url has them all.",
                f"{constants.MAX_SERIES} premières séries sur {total_series} ; csv_url les "
                "contient toutes.",
            )
        )
    infos = []
    all_rows: list[Row] = []
    for series, series_rows in by_key.values():
        series_rows.sort(key=lambda r: r.date)
        if series_rows:
            series.first_period = series_rows[0].date
            series.last_period = series_rows[-1].date
            series.last_value = series_rows[-1].value
            series.observations = len(series_rows)
            infos.append(series)
            all_rows.extend(series_rows)
    if not all_rows:
        raise_localized(
            NotFound,
            f"ECB dataset {fid} has no values for key {key} in the periods asked for.",
            f"le jeu {fid} de la BCE n'a aucune valeur pour la clé {key} pour les périodes "
            "demandées.",
            lang,
        )
    if len(all_rows) > constants.MAX_ROWS:
        keep = max(1, constants.MAX_ROWS // len(infos))
        kept = []
        for series in infos:
            kept.extend([r for r in all_rows if r.series_id == f"{fid}.{series.key}"][-keep:])
        notes.append(
            pick(
                lang,
                f"{len(all_rows):,} rows; only the last {keep:,} of each series are returned. "
                "Narrow the periods, or read csv_url for everything.",
                f"{fr_number(len(all_rows))} lignes ; seules les {fr_number(keep)} dernières de "
                "chaque série sont renvoyées. Réduisez les périodes, ou lisez csv_url pour "
                "tout obtenir.",
            )
        )
        all_rows = kept
    if defaulted:
        notes.append(
            pick(
                lang,
                f"No start_period or last_n: the last {last_n} periods of each series. Pass "
                "start_period or last_n for more.",
                f"Ni start_period ni last_n : les {last_n} dernières périodes de chaque série. "
                "Passez start_period ou last_n pour en avoir plus.",
            )
        )
    return SeriesData(
        dataset=fid,
        key=key,
        series=infos,
        rows=all_rows,
        csv_url=str(httpx.URL(_data_url(fid, key), params={**params, "format": "csvdata"})),
        portal_url=f"{constants.PORTAL_URL}{fid}",
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(fid, key), params=params)),
            cached=cached,
            schema_name="ecb.SeriesData",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                f"ECB dataset {fid} ({info['name']}), key {key}. Periods without a value are "
                "left out.",
                f"Jeu {fid} de la BCE ({info['name']}), clé {key}. Les périodes sans valeur "
                "sont omises.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def get_indicator(
    indicator: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> SeriesData:
    lang = _lang(lang)
    name = indicator.strip().lower()
    spec = constants.INDICATORS.get(name)
    if spec is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other ECB "
            "series use ecb_search_series and ecb_get_series.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série de la BCE, utilisez ecb_search_series et ecb_get_series.",
            lang,
        )
    if ".KR." in spec.key and start_period is None and last_n is None:
        # Key rates are recorded on the dates they change: ten changes, not ten days.
        last_n = 10
    result = await get_series(spec.dataset, spec.key, start_period, end_period, last_n, lang=lang)
    result.indicator = name
    result.indicator_label = pick(lang, spec.label_en, spec.label_fr)
    result.compare_with_canada = pick(lang, spec.pair_en, spec.pair_fr)
    return result
