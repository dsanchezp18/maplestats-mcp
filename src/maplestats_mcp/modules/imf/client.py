"""Client for the IMF's SDMX 2.1 API (api.imf.org/external/sdmx/2.1), no key.

Checked live on 2026-11-18 with the project's User-Agent:

- `dataflow/IMF.STA` (SDMX-JSON 1.0.0) lists 195 dataflows, 0.33 MB: CPI, ER
  (exchange rates), BOP, LS (labour statistics), QNEA and ANEA (national accounts),
  IMTS (trade by partner), MFS_*, GFS_*, PPI and more, and 120 dated "_VINTAGE"
  copies of some of them. IFS and DOT are not dataflows any more (IFS became the
  thematic datasets, DOT became IMTS). `dataflow/IMF.RES` lists 11: WEO (World
  Economic Outlook), PCPS (commodity prices), CTOT, ITS and others. Names and
  descriptions are English only; code names in the codelists come in eight languages
  (`names.fr`). The `lastUpdatedAt` annotation is empty.
- `dataflow/{agency}/{id}/latest?references=all` is the structure: the data
  structure (dimensions in key order), 7 concept schemes and 48 codelists, 2.4 MB for
  CPI. A dimension has no `localRepresentation`: its codelist is the one its concept
  names in `coreRepresentation.enumeration`. There is no availability constraint, so
  the codes with data cannot be told from the codelist; keys are checked against the
  codelists only. CPI's dimensions are COUNTRY.INDEX_TYPE.COICOP_1999.
  TYPE_OF_TRANSFORMATION.FREQUENCY (CL_COUNTRY has 343 codes, CAN among them).
- `data/{agency},{id}/{key}` answers SDMX-ML structure-specific XML whatever the
  data media type asked for (`application/vnd.sdmx.data+json` was ignored). The
  DataSet carries UPDATE_DATE ("2026-11-18T07:43:27.119173800Z"), PUBLICATION_DATE,
  SUGGESTED_CITATION and LICENSE ("(c) International Monetary Fund Copyright. All
  Rights Reserved. https://www.imf.org/external/terms.htm"); each Series has one
  attribute per key dimension plus SCALE and others; each Obs has TIME_PERIOD
  ("2026-M09"), OBS_VALUE and status attributes. A key shorter than the dimension
  count is a prefix (CAN means Canada and every value of the rest); another client's
  notes (EcuDataMCP, 2026-10-10) say a key with too many parts or an unknown value
  is HTTP 400 and an unknown flow 404.
- CPI for Canada, `CAN.CPI._T.IX.M`: 2026-M08 = 169.8 and 2026-M09 = 170 (the all-items
  index on Statistics Canada's own 2002=100 base), prepared 2026-11-18; October,
  released by Statistics Canada on 2026-11-17 (170.4), was not there yet: the IMF's
  consumer prices run about a month behind.

The IMF's terms (https://www.imf.org/en/About/copyright-and-terms, read 2026-11-18)
allow copying and distributing data with the IMF credited, ask for permission for
commercial reuse and prohibit bulk download by automated technology: see
constants.LICENCE. Results are classed commercial_use "not_allowed".

Requests are spaced and cached; `get_raw` retries a 429 or 5xx up to three times.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from maplestats_mcp.modules.imf import constants
from maplestats_mcp.modules.imf.schemas import (
    Code,
    DataResult,
    DataRow,
    DatasetSearch,
    DatasetStructure,
    DatasetSummary,
    Dimension,
    DimensionValue,
    SeriesInfo,
    SeriesList,
)
from maplestats_mcp.shared import sdmx
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import decode_json, get_raw
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = {
    "en": (
        "The IMF updates each dataset on its own schedule (UPDATE_DATE on each answer). "
        "Consumer prices run about a month behind national releases; other datasets lag "
        "by a quarter or more."
    ),
    "fr": (
        "Le FMI met chaque jeu de données à jour selon son propre calendrier (UPDATE_DATE de "
        "chaque réponse). Les prix à la consommation ont environ un mois de retard sur les "
        "publications nationales ; les autres jeux, un trimestre ou davantage."
    ),
}

_DATASET = re.compile(r"^(?:(IMF\.[A-Za-z]+)[,:])?([A-Za-z0-9_]+)$", re.IGNORECASE)
_COUNTRY = re.compile(r"^[A-Z0-9_]{2,12}$")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"the", "of", "and", "in", "for", "by", "on", "to", "a", "an", "data", "dataset",
     "datasets", "canada", "countries", "country", "imf", "de", "des", "du", "la", "le",
     "les", "et", "par", "en", "au", "aux", "pays", "fmi"}
)  # fmt: skip
_CODELIST = re.compile(r"Codelist=(.+)$")
_CONCEPT = re.compile(r"Concept=(.+)\.([^.]+)$")


# -------------------------------------------------------------------- HTTP


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The IMF's data API did not answer ({url}): {detail}. Try again in a minute.",
        f"l'API de données du FMI n'a pas répondu ({url}) : {detail}. Réessayez dans une minute.",
        lang,
    )


async def _get(
    url: str,
    params: dict[str, Any] | None,
    *,
    accept: str,
    timeout: float,
    max_bytes: int,
    not_found: tuple[str, str],
    lang: str,
) -> httpx.Response:
    """One paced GET. A body past `max_bytes` is refused before it is held (TooLarge)."""
    await get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    ).acquire()
    try:
        response = await get_raw(
            url, params=params, headers={"Accept": accept}, timeout=timeout, max_bytes=max_bytes
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(NotFound, not_found[0], not_found[1], lang)
        if status == 400:
            raise_localized(
                InvalidInput,
                f"The IMF rejected the request ({url}): a code or a key part it does not know. "
                "imf_describe_dataset lists the codes.",
                f"le FMI a refusé la requête ({url}) : un code ou une partie de clé inconnus. "
                "imf_describe_dataset donne les codes.",
                lang,
            )
        if status == 429 or status >= 500:
            _raise_unavailable(url, f"HTTP {status}", lang)
        raise_localized(
            UpstreamError,
            f"The IMF's data API answered HTTP {status} for {url}.",
            f"l'API de données du FMI a répondu HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(url, f"{type(exc).__name__}: {exc}", lang)
    if response.status_code >= 400:
        raise_localized(
            UpstreamError,
            f"The IMF's data API answered HTTP {response.status_code} for {url}.",
            f"l'API de données du FMI a répondu HTTP {response.status_code} pour {url}.",
            lang,
        )
    return response


# --------------------------------------------------------------- catalogue


def _plain(text: str) -> str:
    return " ".join(text.split())


def _fold(text: str) -> str:
    """Lower case without accents, so "inflacion" and "inflation" tokenize alike."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _short(text: str) -> str:
    if len(text) <= constants.MAX_DESCRIPTION_CHARS:
        return text
    return text[: constants.MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _browse_url(agency: str, fid: str) -> str:
    return f"{constants.BROWSER_URL}{agency}:{fid}"


def _catalogue_url(agency: str) -> str:
    return f"{constants.BASE_URL}dataflow/{agency}"


async def _catalogue() -> tuple[dict[str, dict[str, Any]], bool]:
    """Dataflow id -> agency, name, description, version, vintage flag, structure URN."""

    async def fetch() -> dict[str, dict[str, Any]]:
        flows: dict[str, dict[str, Any]] = {}
        for agency in constants.AGENCIES:
            url = _catalogue_url(agency)
            response = await _get(
                url,
                None,
                accept=constants.STRUCTURE_ACCEPT,
                timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
                max_bytes=constants.MAX_CATALOGUE_BYTES,
                not_found=(
                    f"The IMF dataflow list for {agency} was not found.",
                    f"la liste des jeux de données du FMI pour {agency} est introuvable.",
                ),
                lang="en",
            )
            payload = decode_json(response, url) or {}
            for flow in list_or_empty(payload.get("data") or {}, "dataflows"):
                if not isinstance(flow, dict) or not flow.get("id"):
                    continue
                fid = str(flow["id"])
                flows.setdefault(
                    fid,
                    {
                        "agency": str(flow.get("agencyID") or agency),
                        "name": str(flow.get("name") or fid),
                        "description": _plain(str(flow.get("description") or "")),
                        "version": str(flow.get("version") or ""),
                        "vintage": fid.upper().endswith("_VINTAGE"),
                        "structure": str(flow.get("structure") or ""),
                    },
                )
        if not flows:
            raise UpstreamError("The IMF dataflow lists came back empty.")
        return flows

    return await cached_fetch("imf:catalogue", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(_fold(text)) if len(w) > 1 and w not in _STOPWORDS]


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
        commercial_use="not_allowed",
        lang=lang,
    )


def _not_statcan(lang: str) -> str:
    return pick(
        lang,
        "These are the IMF's figures, as countries report them to it, not Statistics "
        "Canada's: for Canada's own latest value, cite the StatCan or Bank of Canada release.",
        "Ce sont les chiffres du FMI, tels que les pays les lui déclarent, et non ceux de "
        "Statistique Canada : pour la dernière valeur propre au Canada, citez la publication "
        "de StatCan ou de la Banque du Canada.",
    )


def _dataset_notes(fid: str, lang: str) -> list[str]:
    """What a reader must know about one dataset before quoting it."""
    if fid.upper().startswith("WEO"):
        return [
            pick(
                lang,
                "World Economic Outlook values after the last actual year are IMF projections "
                "(the 2026 value of a series published in October 2026 is an estimate or a "
                "forecast, not a statistic); the latest period listed is often a projection.",
                "Les valeurs des Perspectives de l'économie mondiale postérieures à la dernière "
                "année observée sont des projections du FMI (la valeur 2026 d'une série publiée "
                "en octobre 2026 est une estimation ou une prévision, non une statistique) ; la "
                "dernière période listée est souvent une projection.",
            )
        ]
    return []


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
            "Give a few English words to search for, e.g. 'consumer price', 'exchange rate', "
            "'balance of payments', 'labor statistics' (the IMF names its datasets in English).",
            "donnez quelques mots anglais à chercher, p. ex. « consumer price », « exchange "
            "rate », « balance of payments », « labor statistics » (le FMI nomme ses jeux de "
            "données en anglais).",
            lang,
        )
    catalogue, cached = await _catalogue()
    asked_for_vintage = "vintage" in _fold(query)
    scored = []
    hidden = 0
    for fid, info in catalogue.items():
        if info["vintage"] and not asked_for_vintage:
            hidden += 1
            continue
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
        scored.append((-score, len(info["name"]), fid))
    scored.sort()
    notes = [_not_statcan(lang)]
    if hidden:
        notes.append(
            pick(
                lang,
                f"{hidden} dated vintages of datasets (ids ending _VINTAGE) are left out; add "
                "the word vintage to the query to list them.",
                f"{hidden} millésimes datés de jeux de données (identifiants se terminant par "
                "_VINTAGE) sont omis ; ajoutez le mot vintage à la requête pour les lister.",
            )
        )
    return DatasetSearch(
        query=query,
        total_matches=len(scored),
        datasets=[
            DatasetSummary(
                id=fid,
                agency=catalogue[fid]["agency"],
                name=catalogue[fid]["name"],
                description=_short(catalogue[fid]["description"]),
                browse_url=_browse_url(catalogue[fid]["agency"], fid),
            )
            for _, _, fid in scored[:limit]
        ],
        notes=notes,
        provenance=_provenance(
            ", ".join(_catalogue_url(a) for a in constants.AGENCIES),
            cached,
            "imf.DatasetSearch",
            lang,
            pick(
                lang,
                "Every dataflow of the IMF.STA and IMF.RES agencies (statistics, World Economic "
                "Outlook, commodity prices), dated vintages aside.",
                "Tous les jeux de données des agences IMF.STA et IMF.RES (statistiques, "
                "Perspectives de l'économie mondiale, prix des produits de base), millésimes "
                "datés exceptés.",
            ),
        ),
    )


async def _dataflow(dataset: str, lang: str) -> tuple[str, str, dict[str, Any]]:
    match = _DATASET.match(dataset.strip())
    if not match:
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not an IMF dataset id (e.g. CPI, ER, BOP, WEO). "
            "imf_search_datasets finds them.",
            f"{dataset!r} n'est pas un identifiant de jeu de données du FMI (p. ex. CPI, ER, "
            "BOP, WEO). imf_search_datasets les trouve.",
            lang,
        )
    agency_asked, raw_id = match.groups()
    fid = raw_id.upper()
    catalogue, _ = await _catalogue()
    info = catalogue.get(fid)
    if info is None or (agency_asked and info["agency"].upper() != agency_asked.upper()):
        raise_localized(
            NotFound,
            f"{dataset!r} is not an IMF dataset. Search with imf_search_datasets.",
            f"{dataset!r} n'est pas un jeu de données du FMI. Cherchez avec imf_search_datasets.",
            lang,
        )
    return info["agency"], fid, info


# ---------------------------------------------------------------- structure


def _structure_url(agency: str, fid: str) -> str:
    return f"{constants.BASE_URL}dataflow/{agency}/{fid}/latest"


def _key_of(item: dict[str, Any]) -> str:
    return f"{item.get('agencyID')}:{item.get('id')}({item.get('version')})"


def _parse_structure(payload: Any, fid: str) -> dict[str, Any]:
    """The compact structure: dimensions in key order, each with its codes as
    (id, English name, French name), read through concept -> codelist."""
    data = (payload or {}).get("data") or {}
    flow = next(
        (f for f in list_or_empty(data, "dataflows") if isinstance(f, dict) and f.get("id")), {}
    )
    wanted = str(flow.get("structure") or "").split("=")[-1]
    structures = [s for s in list_or_empty(data, "dataStructures") if isinstance(s, dict)]
    dsd = next((s for s in structures if _key_of(s) == wanted), None)
    if dsd is None and len(structures) == 1:
        dsd = structures[0]
    if dsd is None:
        raise UpstreamError(f"{fid}: the structure answer has no data structure {wanted}.")
    schemes = {
        _key_of(s): {
            str(c["id"]): c
            for c in list_or_empty(s, "concepts")
            if isinstance(c, dict) and c.get("id")
        }
        for s in list_or_empty(data, "conceptSchemes")
        if isinstance(s, dict)
    }
    codelists = {_key_of(c): c for c in list_or_empty(data, "codelists") if isinstance(c, dict)}
    components = dsd.get("dataStructureComponents") or {}
    raw_dims = list_or_empty(components.get("dimensionList") or {}, "dimensions")
    dimensions = []
    for dim in sorted(
        (d for d in raw_dims if isinstance(d, dict)), key=lambda d: int(d.get("position") or 0)
    ):
        concept = {}
        found = _CONCEPT.search(str(dim.get("conceptIdentity") or ""))
        if found:
            concept = schemes.get(found.group(1), {}).get(found.group(2), {})
        enumeration = ((concept.get("coreRepresentation") or {}).get("enumeration")) or (
            (dim.get("localRepresentation") or {}).get("enumeration") or ""
        )
        listed = _CODELIST.search(str(enumeration))
        codelist = codelists.get(listed.group(1), {}) if listed else {}
        codes = []
        for code in list_or_empty(codelist, "codes"):
            if not isinstance(code, dict) or not code.get("id"):
                continue
            raw_names = code.get("names")
            names: dict[str, Any] = raw_names if isinstance(raw_names, dict) else {}
            english = str(code.get("name") or names.get("en") or code["id"])
            codes.append((str(code["id"]), english, str(names.get("fr") or english)))
        dimensions.append(
            {
                "id": str(dim.get("id") or ""),
                "name": str(concept.get("name") or dim.get("id") or ""),
                "codes": codes,
            }
        )
    if not dimensions:
        raise UpstreamError(f"{fid}: the data structure lists no dimensions.")
    return {
        "name": str(flow.get("name") or fid),
        "description": _plain(str(flow.get("description") or "")),
        "version": str(flow.get("version") or ""),
        "dimensions": dimensions,
    }


async def _structure(agency: str, fid: str, lang: str) -> tuple[dict[str, Any], bool]:
    url = _structure_url(agency, fid)

    async def fetch() -> dict[str, Any]:
        response = await _get(
            url,
            {"references": "all"},
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.STRUCTURE_TIMEOUT_SECONDS,
            max_bytes=constants.MAX_STRUCTURE_BYTES,
            not_found=(
                f"No structure for IMF dataset {fid}.",
                f"aucune structure pour le jeu de données {fid} du FMI.",
            ),
            lang=lang,
        )
        try:
            return _parse_structure(decode_json(response, url), fid)
        except UpstreamError as exc:
            raise_localized(UpstreamError, str(exc), f"structure de {fid} illisible : {exc}", lang)

    return await cached_fetch(
        f"imf:structure:{agency}:{fid}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )


def _dims(structure: dict[str, Any], lang: str) -> list[sdmx.Dim]:
    """The structure's dimensions as shared SDMX dimensions, labelled in `lang`."""
    index = 2 if lang == "fr" else 1
    return [
        sdmx.Dim(
            id=d["id"],
            name=d["name"],
            codes=[(c[0], c[index]) for c in d["codes"]],
            constrained=bool(d["codes"]),
        )
        for d in structure["dimensions"]
    ]


def _country_position(dims: list[sdmx.Dim]) -> int:
    """Where the country sits in the key: the COUNTRY dimension, else the first."""
    return next((i for i, d in enumerate(dims) if d.id in ("COUNTRY", "REF_AREA")), 0)


def _citation(name: str, agency: str, fid: str, updated: datetime | None, lang: str) -> str:
    year = (updated or datetime.now(UTC)).year
    today = datetime.now(UTC).date().isoformat()
    url = _browse_url(agency, fid)
    return pick(
        lang,
        f"International Monetary Fund ({year}), {name}, {url} (accessed on {today}).",
        f"Fonds monétaire international ({year}), {name}, {url} (consulté le {today}).",
    )


async def describe_dataset(dataset: str, lang: str = "en") -> DatasetStructure:
    lang = normalize_lang(lang)
    agency, fid, info = await _dataflow(dataset, lang)
    structure, cached = await _structure(agency, fid, lang)
    dims = _dims(structure, lang)
    dimensions = [
        Dimension(
            id=dim.id,
            name=dim.name,
            position=position,
            codes=[Code(id=c, name=n) for c, n in dim.codes[: constants.MAX_CODES_PER_DIMENSION]],
            total_codes=len(dim.codes),
            truncated=len(dim.codes) > constants.MAX_CODES_PER_DIMENSION,
        )
        for position, dim in enumerate(dims, start=1)
    ]
    example = [""] * len(dims)
    country_at = _country_position(dims)
    if constants.CANADA in dims[country_at].code_ids():
        example[country_at] = constants.CANADA
    return DatasetStructure(
        id=fid,
        agency=agency,
        name=structure["name"],
        description=_short(structure["description"] or info["description"]),
        version=structure["version"],
        dimensions=dimensions,
        key_template=".".join(d.id for d in dims),
        example_key=".".join(example),
        citation=_citation(structure["name"], agency, fid, None, lang),
        browse_url=_browse_url(agency, fid),
        provenance=_provenance(
            str(httpx.URL(_structure_url(agency, fid), params={"references": "all"})),
            cached,
            "imf.DatasetStructure",
            lang,
            pick(
                lang,
                "Codes are those of the dataset's codelists; the IMF does not publish which "
                "of them have data, so a key can match no series.",
                "Les codes sont ceux des listes de codes du jeu de données ; le FMI ne publie "
                "pas lesquels ont des données, si bien qu'une clé peut ne correspondre à aucune "
                "série.",
            ),
        ),
    )


# --------------------------------------------------------------------- data


class _Parsed:
    """A data answer: its series and what the DataSet says about itself."""

    def __init__(
        self, series: list[sdmx.Series], updated: datetime | None, citation: str | None
    ) -> None:
        self.series = series
        self.updated = updated
        self.citation = citation


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _when(raw: str | None) -> datetime | None:
    """'2026-11-18T07:43:27.119173800Z' as a UTC datetime (nine fractional digits)."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.strip()).astimezone(UTC)
    except ValueError:
        return None


def _parse_data(content: bytes, dims: list[sdmx.Dim]) -> _Parsed:
    """Series and observations of a structure-specific SDMX-ML answer.

    Each Series element has one attribute per key dimension (the code) and series
    attributes (SCALE, ...); each Obs has TIME_PERIOD, OBS_VALUE and status attributes.
    Observations without a number are left out; periods sort as text within a series
    (2026-M08 before 2026-M09), since one series has one frequency.
    """
    try:
        root = DefusedET.fromstring(content)
    except (DefusedXmlException, SyntaxError) as exc:
        raise UpstreamError(f"the IMF answer is not readable XML: {exc}") from exc
    dataset = next((e for e in root.iter() if _local(e.tag) == "DataSet"), None)
    if dataset is None:
        return _Parsed([], None, None)
    labels = [dict(d.codes) for d in dims]
    series: list[sdmx.Series] = []
    for element in dataset:
        if _local(element.tag) != "Series":
            continue
        codes = [element.get(d.id, "") for d in dims]
        observations: list[tuple[str, float, str | None]] = []
        for obs in element:
            if _local(obs.tag) != "Obs":
                continue
            period, raw = obs.get("TIME_PERIOD"), obs.get("OBS_VALUE")
            if not period or raw in (None, ""):
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            # float() accepts "NaN" and "inf": such a value is a missing observation. Kept,
            # it would become the series' latest value (and a null in a float field).
            if not math.isfinite(value):
                continue
            observations.append((period, value, obs.get("OBS_STATUS") or None))
        if not observations:
            continue
        observations.sort(key=lambda o: o[0])
        attributes = {
            name: (value, value)
            for name in ("SCALE", "UNIT", "UNIT_MEASURE")
            if (value := element.get(name))
        }
        series.append(
            sdmx.Series(
                dims=[
                    (d.id, code, labels[i].get(code, code))
                    for i, (d, code) in enumerate(zip(dims, codes, strict=True))
                ],
                attributes=attributes,
                observations=observations,
            )
        )
    return _Parsed(series, _when(dataset.get("UPDATE_DATE")), dataset.get("SUGGESTED_CITATION"))


def _data_url(agency: str, fid: str, key: str) -> str:
    return f"{constants.BASE_URL}data/{agency},{fid}/{key}"


async def _fetch(
    agency: str,
    fid: str,
    key: str,
    params: dict[str, Any],
    dims: list[sdmx.Dim],
    lang: str,
) -> tuple[_Parsed, bool]:
    url = _data_url(agency, fid, key)

    async def fetch() -> _Parsed:
        response = await _get(
            url,
            params,
            accept=constants.DATA_ACCEPT,
            timeout=constants.DATA_TIMEOUT_SECONDS,
            max_bytes=constants.MAX_DATA_BYTES,
            not_found=(
                f"No data in IMF dataset {fid} for key {key!r}"
                + (" in the periods asked for" if params else "")
                + ". Check the codes with imf_describe_dataset.",
                f"aucune donnée dans le jeu {fid} du FMI pour la clé {key!r}"
                + (" pour les périodes demandées" if params else "")
                + ". Vérifiez les codes avec imf_describe_dataset.",
            ),
            lang=lang,
        )
        try:
            return _parse_data(response.content, dims)
        except UpstreamError as exc:
            raise_localized(
                UpstreamError, f"{fid}: {exc}", f"{fid} : réponse illisible : {exc}", lang
            )

    # The parsed answer holds labels in one language, so the language is in the cache key.
    return await cached_fetch(
        f"imf:data:{agency}:{fid}:{key}:{sorted(params.items())}:{lang}",
        constants.CACHE_TTL_DATA_SECONDS,
        fetch,
    )


def _series_info(series: sdmx.Series) -> SeriesInfo:
    freq = series.dim("FREQUENCY") or series.dim("FREQ")
    obs = series.observations
    attrs = series.attributes
    return SeriesInfo(
        key=series.key,
        label="; ".join(label for _, code, label in series.dims if code),
        dimensions=[DimensionValue(id=d, code=c, label=label) for d, c, label in series.dims],
        frequency=freq[1] if freq else None,
        unit=(attrs.get("UNIT") or attrs.get("UNIT_MEASURE") or ("", None))[1],
        scale=attrs["SCALE"][1] if "SCALE" in attrs else None,
        observation_count=len(obs),
        latest_period=obs[-1][0] if obs else None,
        latest_value=obs[-1][1] if obs else None,
    )


def _pad_key(key: str, dims: list[sdmx.Dim], fid: str, lang: str) -> str:
    """The IMF reads a short key as a prefix, so pad it with wildcards; refuse a long one."""
    parts = key.strip().split(".")
    if len(parts) > len(dims):
        template = ".".join(d.id for d in dims)
        raise_localized(
            InvalidInput,
            f"{key!r} has {len(parts)} parts but {fid} has {len(dims)} dimensions: {template}.",
            f"{key!r} a {len(parts)} parties mais {fid} a {len(dims)} dimensions : {template}.",
            lang,
        )
    return ".".join(parts + [""] * (len(dims) - len(parts)))


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
    agency, fid, _ = await _dataflow(dataset, lang)
    structure, _ = await _structure(agency, fid, lang)
    dims = _dims(structure, lang)
    key = sdmx.check_key(
        _pad_key(key, dims, fid, lang), dims, fid, "imf_describe_dataset", constants.CANADA, lang
    )
    # The bound multiplies the codes of every wildcard dimension, far above the series
    # that exist, so it only stops an unbounded history of many series.
    bound = sdmx.max_series(key, dims)
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
    parsed, cached = await _fetch(agency, fid, key, params, dims, lang)
    fetched = parsed.series
    if not fetched:
        raise_localized(
            NotFound,
            f"IMF dataset {fid} has no values for key {key!r} in the periods asked for.",
            f"le jeu {fid} du FMI n'a aucune valeur pour la clé {key!r} pour les périodes "
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
                f"First {constants.MAX_SERIES} of {total_series} series; name more codes in "
                "the key for the others.",
                f"{constants.MAX_SERIES} premières séries sur {total_series} ; nommez plus de "
                "codes dans la clé pour les autres.",
            )
        )
    total_rows = sum(len(s.observations) for s in fetched)
    if total_rows > constants.MAX_ROWS:
        keep = max(1, constants.MAX_ROWS // len(fetched))
        # The series came from the cache, which hands every caller the same objects: cut
        # copies, never the series themselves, or a repeat call would find them already
        # short, see the rows under the cap and drop the note on the cut history.
        fetched = [replace(s, observations=s.observations[-keep:]) for s in fetched]
        limits.append(
            pick(
                lang,
                f"{total_rows:,} observations; only the last {keep:,} of each series are "
                "returned. Narrow the periods.",
                f"{fr_number(total_rows)} observations ; seules les {fr_number(keep)} "
                "dernières de chaque série sont renvoyées. Réduisez les périodes.",
            )
        )
    series = [_series_info(s) for s in fetched]
    rows = [
        DataRow(series_key=info.key, period=period, value=value, status=status)
        for info, s in zip(series, fetched, strict=True)
        for period, value, status in s.observations
    ]
    notes = [*limits, _not_statcan(lang), *_dataset_notes(fid, lang)]
    name = structure["name"]
    return DataResult(
        dataset=fid,
        dataset_name=name,
        key=key,
        series=series,
        rows=rows,
        citation=_citation(name, agency, fid, parsed.updated, lang),
        notes=notes,
        provenance=_provenance(
            str(httpx.URL(_data_url(agency, fid, key), params=params)),
            cached,
            "imf.DataResult",
            lang,
            pick(
                lang,
                f"IMF dataset {fid} ({name}), key {key}. Periods without a value are left out.",
                f"Jeu de données {fid} du FMI ({name}), clé {key}. Les périodes sans valeur "
                "sont omises.",
            ),
            as_of=parsed.updated,
            limits=" ".join(limits) or None,
        ),
    )


async def search_series(
    dataset: str,
    query: str | None = None,
    country: str = constants.CANADA,
    limit: int = 25,
    lang: str = "en",
) -> SeriesList:
    lang = normalize_lang(lang)
    if not 1 <= limit <= constants.MAX_SEARCH_RESULTS:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_SEARCH_RESULTS}.",
            f"limit doit être compris entre 1 et {constants.MAX_SEARCH_RESULTS}.",
            lang,
        )
    code = country.strip().upper()
    if not _COUNTRY.match(code):
        raise_localized(
            InvalidInput,
            f"{country!r} is not an IMF country code (CAN, USA, GBR, ...).",
            f"{country!r} n'est pas un code de pays du FMI (CAN, USA, GBR, ...).",
            lang,
        )
    agency, fid, _ = await _dataflow(dataset, lang)
    structure, _ = await _structure(agency, fid, lang)
    dims = _dims(structure, lang)
    at = _country_position(dims)
    parts = [""] * len(dims)
    parts[at] = code
    key = sdmx.check_key(".".join(parts), dims, fid, "imf_describe_dataset", constants.CANADA, lang)
    params = sdmx.data_params(None, None, 1)
    parsed, cached = await _fetch(agency, fid, key, params, dims, lang)
    fetched = parsed.series
    if not fetched:
        raise_localized(
            NotFound,
            f"IMF dataset {fid} has no series for {code}.",
            f"le jeu {fid} du FMI n'a aucune série pour {code}.",
            lang,
        )
    notes = [_not_statcan(lang), *_dataset_notes(fid, lang)]
    if len(fetched) > constants.MAX_SERIES:
        notes.append(
            pick(
                lang,
                f"Only the first {constants.MAX_SERIES} of {len(fetched)} series were read.",
                f"Seules les {constants.MAX_SERIES} premières séries sur {len(fetched)} ont été "
                "lues.",
            )
        )
        fetched = fetched[: constants.MAX_SERIES]
    words = _tokens(query) if query else []
    infos = [_series_info(s) for s in fetched]
    if words:
        infos = [i for i in infos if set(words) <= set(_WORD.findall(_fold(i.label)))]
    total = len(infos)
    name = structure["name"]
    return SeriesList(
        dataset=fid,
        dataset_name=name,
        country=code,
        query=query,
        total_matches=total,
        series=infos[:limit],
        citation=_citation(name, agency, fid, parsed.updated, lang),
        notes=notes,
        provenance=_provenance(
            str(httpx.URL(_data_url(agency, fid, key), params=params)),
            cached,
            "imf.SeriesList",
            lang,
            pick(
                lang,
                f"Every series of IMF dataset {fid} ({name}) for {code}, each with its latest "
                "observation; every word of the query must appear in a series' labels.",
                f"Toutes les séries du jeu {fid} du FMI ({name}) pour {code}, chacune avec sa "
                "dernière observation ; chaque mot de la requête doit figurer dans les libellés "
                "d'une série.",
            ),
            as_of=parsed.updated,
        ),
    )
