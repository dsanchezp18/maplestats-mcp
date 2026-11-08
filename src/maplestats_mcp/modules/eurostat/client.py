"""Client for Eurostat's dissemination APIs (no key, no registration).

Checked live on 2026-11-07 with the project's User-Agent:

- Table of contents: `catalogue/toc/txt?lang=en|fr` is a 2 MB tab-separated
  file, every field quoted: title (indented four spaces per tree level),
  code, type (folder, dataset, table), last update of data and last
  structure change (`16.10.2026`), data start and end (`2002-12`,
  `2026-09`, `2026`), and number of values. A dataset appears once per
  folder that holds it, so codes repeat.
- Structure: `sdmx/2.1/dataflow/ESTAT/{CODE}/latest?references=descendants
  &detail=referencepartial` answers SDMX-ML 2.1 (no JSON) with the dataflow
  names, the DSD's dimensions in order (ids in lower case, as the data API
  takes them: freq, unit, geo; then TIME_PERIOD), and its codelists cut to
  the codes that have data (PRC_HICP_MINR: 46 of the GEO codes), each code
  named in English, French and German. The `Ref` elements carry no
  namespace. The OBS_FLAG codelist decodes the status flags. Table codes
  (teina225) work the same as dataset codes. An unknown code answers 404
  with a SOAP fault ("... is not available for dissemination").
- Data: `statistics/1.0/data/{code}` answers JSON-stat 2.0. Any dimension
  filters as `dim=CODE`, repeated for several codes; `sinceTimePeriod`,
  `untilTimePeriod` and `lastTimePeriod` bound time (only since+until
  combine); `lang=EN|FR|DE` gives the labels. `value` and `status` are
  objects keyed by the flat cell index (row-major over `size`); missing
  cells are absent. `extension.status.label` labels the flags used.
  Unknown filter codes are dropped silently (US asked of namq_10_gdp: no
  US in the answer); a code combination with no data gives an empty
  `value`, HTTP 200. Errors come as `{"error": [{"status", "id", "label"}]}`:
  404/100 for an unknown dataset, 400/150 for an unknown dimension, 413
  EXTRACTION_TOO_BIG above 5,000,000 cells. The guide documents a
  `{"warning": ... "ASYNCHRONOUS_RESPONSE"}` answer for requests Eurostat
  queues; it was not seen here. A 2.4-million-cell answer took 88 s and
  30 MB, so this client bounds every request by series count first.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

import httpx
from defusedxml import ElementTree

from maplestats_mcp.modules.eurostat import constants
from maplestats_mcp.modules.eurostat.schemas import (
    Code,
    Comparison,
    DataResult,
    DatasetHit,
    DatasetSearch,
    DatasetStructure,
    Dimension,
    FlagLabel,
    GeoSeries,
    Observation,
    Row,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.models import CommercialUse
from maplestats_mcp.shared.rate_limiter import get_limiter

_FRESHNESS = {
    "en": (
        "Updated on Eurostat's release calendar: monthly indicators (HICP, unemployment) "
        "monthly, national accounts and house prices quarterly, others yearly."
    ),
    "fr": (
        "Mis à jour selon le calendrier de diffusion d'Eurostat : indicateurs mensuels (IPCH, "
        "chômage) chaque mois, comptes nationaux et prix des logements chaque trimestre, les "
        "autres chaque année."
    ),
}

_PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|S[12]|W\d{2}|\d{2}(-\d{2})?))?$")
_CODE = re.compile(r"^[A-Za-z0-9_$-]+$")
_SDMX = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}"
_COMMON = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with",
        "au", "aux", "d", "de", "des", "du", "en", "et", "l", "la", "le", "les", "par",
        "pour", "sur", "un", "une",
    }
)  # fmt: skip
_COMMERCIAL_OK = frozenset(constants.EU27 + constants.EFTA + constants.CANDIDATES)


def _licence(lang: str) -> str:
    return constants.LICENCE_FR if lang == "fr" else constants.LICENCE


def _fold(text: str) -> str:
    """Lower case without accents, for matching names and search words."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text))


def _iso_date(text: str) -> str | None:
    """'16.10.2026' -> '2026-10-16'."""
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text.strip())
    return f"{match[3]}-{match[2]}-{match[1]}" if match else None


def _browser_url(code: str, lang: str) -> str:
    return f"{constants.DATABROWSER_URL}{code.lower()}/default/table?lang={lang}"


# ------------------------------------------------------------------ requests


def _upstream_label(response: httpx.Response) -> str:
    """The `label` of Eurostat's JSON error, or the SOAP faultstring, or ''."""
    text = response.text[:4000]
    try:
        payload = json.loads(text)
    except ValueError:
        match = re.search(r"<faultstring>(.*?)</faultstring>", text, re.DOTALL)
        return match[1].strip() if match else ""
    errors = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("label") or "")
    if isinstance(errors, dict):
        return str(errors.get("label") or "")
    return ""


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"Eurostat's API did not answer ({url}): {detail}. Try again in a minute.",
        f"l'API d'Eurostat n'a pas répondu ({url}) : {detail}. Réessayez dans une minute.",
        lang,
    )


async def _get(
    url: str,
    params: list[tuple[str, str]] | None,
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
        response = await get_raw(url, params=params, timeout=timeout)  # type: ignore[arg-type]
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        label = _upstream_label(exc.response)
        if status == 404:
            raise_localized(
                NotFound,
                not_found[0] + (f" Eurostat: {label}" if label else ""),
                not_found[1] + (f" Eurostat : {label}" if label else ""),
                lang,
            )
        if status == 413:
            raise_localized(
                InvalidInput,
                "Eurostat refused the request as too big. Name more codes in filters or geo, "
                f"or shorten the period. Eurostat: {label}",
                "Eurostat a refusé la requête, trop volumineuse. Précisez des codes dans "
                f"filters ou geo, ou raccourcissez la période. Eurostat : {label}",
                lang,
            )
        if status == 400:
            raise_localized(
                InvalidInput,
                f"Eurostat refused the query: {label or 'HTTP 400'}.",
                f"Eurostat a refusé la requête : {label or 'HTTP 400'}.",
                lang,
            )
        if status >= 500 or status == 429:
            _raise_unavailable(url, f"HTTP {status}", lang)
        raise_localized(
            UpstreamError,
            f"Eurostat's API answered HTTP {status} for {url}: {label}",
            f"l'API d'Eurostat a répondu HTTP {status} pour {url} : {label}",
            lang,
        )
    except httpx.HTTPError as exc:
        _raise_unavailable(url, str(exc) or type(exc).__name__, lang)
    if response.status_code >= 400:
        # get_raw hands 406 and 409 back unraised.
        raise_localized(
            UpstreamError,
            f"Eurostat's API answered HTTP {response.status_code} for {url}.",
            f"l'API d'Eurostat a répondu HTTP {response.status_code} pour {url}.",
            lang,
        )
    return response


# ---------------------------------------------------------- table of contents


def _parse_toc(text: str) -> list[dict[str, Any]]:
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    header = next(reader, None)
    if not header or len(header) < 3 or header[1].strip().lower() != "code":
        raise UpstreamError(f"unexpected table of contents header: {header!r}")
    entries: dict[str, dict[str, Any]] = {}
    path: list[str] = []
    for row in reader:
        if len(row) < 3:
            continue
        raw_title, code, kind = row[0], row[1].strip(), row[2].strip().lower()
        depth = (len(raw_title) - len(raw_title.lstrip(" "))) // 4
        title = raw_title.strip()
        if kind == "folder":
            del path[depth:]
            path.append(title)
            continue
        if kind not in ("dataset", "table") or not code or code in entries:
            continue
        cells = (row + [""] * 8)[:8]
        values = cells[7].strip()
        entries[code] = {
            "code": code,
            "title": title,
            "type": kind,
            # path[0] is "Database by themes" or "Tables by themes": not a theme.
            "theme": " > ".join(path[1:depth]),
            "last_update": _iso_date(cells[3]),
            "data_start": cells[5].strip() or None,
            "data_end": cells[6].strip() or None,
            "values": int(values) if values.isdigit() else None,
        }
    if not entries:
        raise UpstreamError("the table of contents lists no datasets")
    return list(entries.values())


async def _toc(lang: str) -> tuple[list[dict[str, Any]], bool]:
    async def fetch() -> list[dict[str, Any]]:
        response = await _get(
            constants.TOC_URL,
            [("lang", lang)],
            constants.TOC_TIMEOUT_SECONDS,
            (
                "Eurostat's table of contents was not found.",
                "la table des matières d'Eurostat est introuvable.",
            ),
            lang,
        )
        try:
            return _parse_toc(response.text)
        except UpstreamError as exc:
            raise_localized(
                UpstreamError,
                f"Eurostat's table of contents: {exc}.",
                f"table des matières d'Eurostat : {exc}.",
                lang,
            )

    return await cached_fetch(f"eurostat:toc:{lang}", constants.CACHE_TTL_TOC_SECONDS, fetch)


def _score(
    entry: dict[str, Any], other: dict[str, Any] | None, tokens: list[str], query_code: str
) -> tuple[int, int]:
    """(score, tokens matched): title words count 2, theme or code words 1.

    Titles and themes in both languages are searched, so an English query
    finds a dataset from the French list and the other way round.
    """
    if entry["code"].lower() == query_code:
        return 1000, len(tokens)
    title = _words(entry["title"]) + (_words(other["title"]) if other else [])
    rest = _words(entry["theme"]) + _words(entry["code"].replace("_", " "))
    if other:
        rest += _words(other["theme"])
    score = matched = 0
    for token in tokens:
        if any(w.startswith(token) for w in title):
            score, matched = score + 2, matched + 1
        elif any(w.startswith(token) for w in rest):
            score, matched = score + 1, matched + 1
    return score, matched


def _recency(entry: dict[str, Any]) -> str:
    return (entry["data_end"] or "")[:4]


async def search_datasets(
    query: str,
    dataset_type: str | None = None,
    limit: int = 10,
    lang: str = "en",
) -> DatasetSearch:
    lang = normalize_lang(lang)
    text = query.strip()
    tokens = [w for w in _words(text) if w not in _STOPWORDS]
    if not tokens:
        raise_localized(
            InvalidInput,
            "Give words from a dataset's title (e.g. 'unemployment rate monthly') or a code "
            "(e.g. une_rt_m).",
            "donnez des mots du titre d'un jeu (p. ex. « taux de chômage mensuel ») ou un "
            "code (p. ex. une_rt_m).",
            lang,
        )
    if not 1 <= limit <= constants.MAX_SEARCH_RESULTS:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.MAX_SEARCH_RESULTS}.",
            f"limit doit être compris entre 1 et {constants.MAX_SEARCH_RESULTS}.",
            lang,
        )
    kind = (dataset_type or "").strip().lower() or None
    if kind not in (None, "dataset", "table"):
        raise_localized(
            InvalidInput,
            "dataset_type must be 'dataset' or 'table'.",
            "dataset_type doit valoir « dataset » ou « table ».",
            lang,
        )
    entries, cached = await _toc(lang)
    try:
        others, _ = await _toc("fr" if lang == "en" else "en")
    except (UpstreamError, UpstreamUnavailable, NotFound):
        others = []
    other_by_code = {e["code"]: e for e in others}
    query_code = text.lower()
    scored = []
    for entry in entries:
        if kind and entry["type"] != kind:
            continue
        score, matched = _score(entry, other_by_code.get(entry["code"]), tokens, query_code)
        if score:
            scored.append((matched, score, entry))
    # Entries matching more of the words first; partial matches still come
    # after (une_rt_m's title has no "rate"), not dropped.
    pool = scored
    # Ties go to the dataset with the latest data (a discontinued one sinks),
    # then to the largest: the main database before its extracts.
    pool.sort(key=lambda s: (s[0], s[1], _recency(s[2]), s[2]["values"] or 0), reverse=True)
    hits = [DatasetHit(**entry) for _, _, entry in pool[:limit]]
    return DatasetSearch(
        query=text,
        total_matches=len(pool),
        datasets=hits,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(constants.TOC_URL, params={"lang": lang})),
            cached=cached,
            schema_name="eurostat.DatasetSearch",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Eurostat's table of contents: every dataset and table, matched on title, "
                "code and theme. A data_end years back means the dataset is discontinued; "
                "the newer one usually has a close title.",
                "Table des matières d'Eurostat : tous les jeux et tableaux, cherchés dans le "
                "titre, le code et le thème. Un data_end ancien signale un jeu abandonné ; "
                "son remplaçant a souvent un titre proche.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# ----------------------------------------------------------------- structure


def _names(element: Any) -> dict[str, str]:
    return {
        str(n.get(_XML_LANG) or "en"): (n.text or "").strip()
        for n in element.findall(f"{_COMMON}Name")
    }


def _parse_structure(xml: bytes) -> dict[str, Any]:
    root = ElementTree.fromstring(xml)
    codelists: dict[str, list[tuple[str, dict[str, str]]]] = {}
    codelist_names: dict[str, dict[str, str]] = {}
    for codelist in root.iter(f"{_SDMX}Codelist"):
        cid = str(codelist.get("id") or "")
        codelist_names[cid] = _names(codelist)
        codelists[cid] = [
            (str(code.get("id")), _names(code))
            for code in codelist.findall(f"{_SDMX}Code")
            if code.get("id")
        ]
    flow = next(root.iter(f"{_SDMX}Dataflow"), None)
    dimensions = []
    for dim in root.iter(f"{_SDMX}Dimension"):
        enumeration = dim.find(f"{_SDMX}LocalRepresentation/{_SDMX}Enumeration")
        ref = next(iter(enumeration), None) if enumeration is not None else None
        cid = str(ref.get("id")) if ref is not None else ""
        dimensions.append(
            {
                "id": str(dim.get("id") or ""),
                "position": int(dim.get("position") or 0),
                "names": codelist_names.get(cid, {}),
                "codes": codelists.get(cid, []),
            }
        )
    dimensions.sort(key=lambda d: d["position"])
    if not dimensions:
        raise UpstreamError("the structure lists no dimensions")
    return {
        "names": _names(flow) if flow is not None else {},
        "dimensions": dimensions,
        "flags": codelists.get("OBS_FLAG", []),
    }


def _check_code(dataset: str, lang: str) -> str:
    code = dataset.strip()
    if not code or not _CODE.match(code):
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not a Eurostat dataset code (e.g. namq_10_gdp, une_rt_m, "
            "prc_hicp_minr). eurostat_search_datasets finds codes.",
            f"{dataset!r} n'est pas un code de jeu d'Eurostat (p. ex. namq_10_gdp, une_rt_m, "
            "prc_hicp_minr). eurostat_search_datasets trouve les codes.",
            lang,
        )
    return code.lower()


def _structure_url(code: str) -> str:
    return f"{constants.STRUCTURE_URL}{code.upper()}/latest"


_STRUCTURE_PARAMS = [("references", "descendants"), ("detail", "referencepartial")]


async def _structure(code: str, lang: str) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        response = await _get(
            _structure_url(code),
            _STRUCTURE_PARAMS,
            constants.STRUCTURE_TIMEOUT_SECONDS,
            (
                f"{code} is not a Eurostat dataset. eurostat_search_datasets finds codes.",
                (
                    f"{code} n'est pas un jeu de données d'Eurostat. eurostat_search_datasets "
                    "trouve les codes."
                ),
            ),
            lang,
        )
        try:
            return _parse_structure(response.content)
        except (UpstreamError, ElementTree.ParseError, ValueError) as exc:
            raise_localized(
                UpstreamError,
                f"{code}: unreadable structure from Eurostat ({exc}).",
                f"{code} : structure illisible renvoyée par Eurostat ({exc}).",
                lang,
            )

    return await cached_fetch(
        f"eurostat:structure:{code}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )


def _label(names: dict[str, str], lang: str) -> str:
    return names.get(lang) or names.get("en") or next(iter(names.values()), "")


def _flag_label(flag: str, lang: str, known: dict[str, str] | None = None) -> str:
    """Eurostat's own label when it gave one, else the letters decoded one by one."""
    if known and flag in known:
        return known[flag]
    parts = []
    for letter in flag:
        en, fr = constants.FLAGS.get(letter, (letter, letter))
        parts.append(pick(lang, en, fr))
    return ", ".join(parts)


async def _toc_entry(code: str, lang: str) -> dict[str, Any] | None:
    """The dataset's line in the table of contents, if it can be read."""
    try:
        entries, _ = await _toc(lang)
    except (UpstreamError, UpstreamUnavailable, NotFound):
        return None
    return next((e for e in entries if e["code"].lower() == code), None)


async def describe_dataset(dataset: str, lang: str = "en") -> DatasetStructure:
    lang = normalize_lang(lang)
    code = _check_code(dataset, lang)
    structure, cached = await _structure(code, lang)
    entry = await _toc_entry(code, lang)
    dimensions = []
    example: dict[str, list[str]] = {}
    for dim in structure["dimensions"]:
        codes = dim["codes"]
        dimensions.append(
            Dimension(
                id=dim["id"],
                label=_label(dim["names"], lang) or dim["id"],
                position=dim["position"],
                codes=[
                    Code(id=c, label=_label(n, lang) or c)
                    for c, n in codes[: constants.MAX_CODES_PER_DIMENSION]
                ],
                total_codes=len(codes),
                truncated=len(codes) > constants.MAX_CODES_PER_DIMENSION,
            )
        )
        if codes:
            ids = [c for c, _ in codes]
            if dim["id"] == "geo":
                pick_code = next((g for g in constants.EU_AGGREGATES if g in ids), ids[0])
            else:
                pick_code = ids[0]
            example[dim["id"]] = [pick_code]
    flags = [
        FlagLabel(flag=f, label=_label(n, lang) or _flag_label(f, lang))
        for f, n in structure["flags"]
    ] or [FlagLabel(flag=f, label=pick(lang, *v)) for f, v in constants.FLAGS.items()]
    title = _label(structure["names"], lang) or (entry or {}).get("title") or code
    return DatasetStructure(
        code=code,
        title=title,
        last_update=(entry or {}).get("last_update"),
        data_start=(entry or {}).get("data_start"),
        data_end=(entry or {}).get("data_end"),
        dimensions=dimensions,
        example_filters=example,
        flags=flags,
        databrowser_url=_browser_url(code, lang),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_structure_url(code), params=_STRUCTURE_PARAMS)),
            cached=cached,
            schema_name="eurostat.DatasetStructure",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Codes are those Eurostat lists as having data in this dataset. Time is not "
                "listed: bound it with start_period, end_period or last_n.",
                "Les codes sont ceux qu'Eurostat déclare comme ayant des données dans ce jeu. "
                "Le temps n'est pas listé : bornez-le avec start_period, end_period ou last_n.",
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


# ----------------------------------------------------------------------- data


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
    if last_n is not None:
        if not 1 <= last_n <= constants.MAX_LAST_N:
            raise_localized(
                InvalidInput,
                f"last_n must be between 1 and {constants.MAX_LAST_N}.",
                f"last_n doit être compris entre 1 et {constants.MAX_LAST_N}.",
                lang,
            )
        if start_period or end_period:
            # Eurostat refuses lastTimePeriod with another time parameter.
            raise_localized(
                InvalidInput,
                "Give last_n or start_period/end_period, not both.",
                "donnez last_n ou start_period/end_period, pas les deux.",
                lang,
            )


def _resolve_geo(
    requested: Sequence[str], available: list[tuple[str, dict[str, str]]], lang: str
) -> list[str]:
    """Codes, Eurostat or ISO, aggregates (EU27, EURO_AREA), groups and country names."""
    ids = [c for c, _ in available]
    id_set = set(ids)
    by_name: dict[str, str] = {}
    for code, names in available:
        for name in names.values():
            by_name.setdefault(_fold(name).strip(), code)
    out: list[str] = []
    for raw in requested:
        text = raw.strip()
        if not text:
            continue
        key = re.sub(r"[\s-]+", "_", _fold(text).upper())
        # EU and EA name the fixed-composition aggregates (EU27_2020, EA21), as
        # Eurostat's headlines do; the changing-composition codes are a fallback.
        if key in constants.GEO_AGGREGATE_ALIASES:
            choices = constants.GEO_AGGREGATE_ALIASES[key]
            found = next((c for c in choices if c in id_set), None)
            codes = [found] if found else [choices[0]]
        elif key in constants.GEO_GROUPS:
            codes = list(constants.GEO_GROUPS[key])
        elif text.upper() in id_set:
            codes = [text.upper()]
        elif constants.ISO_TO_EUROSTAT.get(text.upper()) in id_set:
            codes = [constants.ISO_TO_EUROSTAT[text.upper()]]
        elif _fold(text) in by_name:
            codes = [by_name[_fold(text)]]
        elif re.fullmatch(r"[A-Za-z]{2}|[A-Za-z0-9]{2,6}_[A-Za-z0-9_]+|[A-Za-z]{2}\d+", text):
            # A code the dataset lacks (US in namq_10_gdp): Eurostat drops it
            # silently, and the result lists it in missing_geo.
            upper = text.upper()
            codes = [constants.ISO_TO_EUROSTAT.get(upper, upper)]
        else:
            sample = ", ".join(ids[:40])
            raise_localized(
                InvalidInput,
                f"{raw!r} is not a geo code, group or country name in this dataset. Use "
                f"EU27, EURO_AREA, EU_MEMBERS, EURO_AREA_MEMBERS, BIG_FOUR, a country name, "
                f"or a code: {sample}.",
                f"{raw!r} n'est ni un code geo, ni un groupe, ni un nom de pays de ce jeu. "
                f"Utilisez EU27, EURO_AREA, EU_MEMBERS, EURO_AREA_MEMBERS, BIG_FOUR, un nom "
                f"de pays, ou un code : {sample}.",
                lang,
            )
        for code in codes:
            if code not in out:
                out.append(code)
    return out


def _resolve_filters(
    code: str,
    filters: Mapping[str, Sequence[str] | str] | None,
    geo: Sequence[str] | None,
    dimensions: list[dict[str, Any]],
    lang: str,
) -> dict[str, list[str]]:
    by_id = {d["id"].lower(): d for d in dimensions}
    chosen: dict[str, list[str]] = {}
    for raw_dim, raw_codes in (filters or {}).items():
        dim_id = raw_dim.strip().lower()
        if dim_id in ("time", "time_period"):
            raise_localized(
                InvalidInput,
                "Bound time with start_period, end_period or last_n, not in filters.",
                "bornez le temps avec start_period, end_period ou last_n, pas dans filters.",
                lang,
            )
        dim = by_id.get(dim_id)
        if dim is None:
            raise_localized(
                InvalidInput,
                f"{code} has no dimension {raw_dim!r}. Dimensions: {', '.join(by_id)}.",
                f"{code} n'a pas de dimension {raw_dim!r}. Dimensions : {', '.join(by_id)}.",
                lang,
            )
        wanted = [raw_codes] if isinstance(raw_codes, str) else list(raw_codes)
        if dim_id == "geo":
            chosen["geo"] = _resolve_geo(wanted, dim["codes"], lang)
            continue
        known = {c.upper(): c for c, _ in dim["codes"]}
        codes = []
        for value in wanted:
            value = value.strip()
            if not value:
                continue
            match = known.get(value.upper())
            if match is None and known:
                sample = ", ".join(list(known.values())[:30])
                raise_localized(
                    InvalidInput,
                    f"{value!r} is not a code of {dim_id} in {code} with data. Codes: "
                    f"{sample}{' ...' if len(known) > 30 else ''} (eurostat_describe_dataset "
                    "lists them all).",
                    f"{value!r} n'est pas un code de {dim_id} avec données dans {code}. Codes : "
                    f"{sample}{' ...' if len(known) > 30 else ''} (eurostat_describe_dataset "
                    "les énumère tous).",
                    lang,
                )
            codes.append(match or value)
        if codes:
            chosen[dim_id] = codes
    if geo:
        if "geo" not in by_id:
            raise_localized(
                InvalidInput,
                f"{code} has no geo dimension.",
                f"{code} n'a pas de dimension geo.",
                lang,
            )
        merged = chosen.get("geo", []) + [
            g
            for g in _resolve_geo(geo, by_id["geo"]["codes"], lang)
            if g not in chosen.get("geo", [])
        ]
        chosen["geo"] = merged
    return chosen


def _series_bound(chosen: dict[str, list[str]], dimensions: list[dict[str, Any]]) -> int:
    total = 1
    for dim in dimensions:
        total *= len(chosen[dim["id"]]) if dim["id"] in chosen else max(1, len(dim["codes"]))
    return total


def _data_params(
    chosen: dict[str, list[str]],
    start_period: str | None,
    end_period: str | None,
    last_n: int | None,
    lang: str,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("lang", constants.LANGS[lang])]
    for dim_id, codes in chosen.items():
        params.extend((dim_id, c) for c in codes)
    if start_period:
        params.append(("sinceTimePeriod", start_period.strip()))
    if end_period:
        params.append(("untilTimePeriod", end_period.strip()))
    if last_n is not None:
        params.append(("lastTimePeriod", str(last_n)))
    return params


def _categories(dimension: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    category = dimension.get("category") or {}
    index = category.get("index")
    if isinstance(index, dict):
        codes = [c for c, _ in sorted(index.items(), key=lambda kv: int(kv[1]))]
    elif isinstance(index, list):
        codes = [str(c) for c in index]
    else:
        codes = list((category.get("label") or {}).keys())
    labels = {str(k): str(v) for k, v in (category.get("label") or {}).items()}
    return codes, labels


def _cells(container: Any) -> dict[int, Any]:
    if isinstance(container, dict):
        return {int(k): v for k, v in container.items()}
    if isinstance(container, list):
        return {i: v for i, v in enumerate(container) if v is not None}
    return {}


def _parse_jsonstat(payload: dict[str, Any]) -> dict[str, Any]:
    """Every cell with a value or a flag, as (codes by dimension, value, flag)."""
    if "warning" in payload and "value" not in payload:
        raise UpstreamUnavailable(str(payload["warning"]))
    ids = [str(i) for i in payload.get("id") or []]
    sizes = [int(s) for s in payload.get("size") or []]
    dims = payload.get("dimension") or {}
    if not ids or len(ids) != len(sizes) or any(i not in dims for i in ids):
        raise UpstreamError("the JSON-stat answer has no consistent id, size and dimension")
    categories = {i: _categories(dims[i]) for i in ids}
    values = _cells(payload.get("value"))
    status = {k: str(v) for k, v in _cells(payload.get("status")).items()}
    strides = [1] * len(sizes)
    for n in range(len(sizes) - 2, -1, -1):
        strides[n] = strides[n + 1] * sizes[n + 1]
    cells = []
    for flat in sorted(set(values) | set(status)):
        codes = {}
        for dim_id, size, stride in zip(ids, sizes, strides, strict=True):
            position = (flat // stride) % size
            dim_codes = categories[dim_id][0]
            codes[dim_id] = dim_codes[position] if position < len(dim_codes) else str(position)
        raw = values.get(flat)
        value = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        if value is not None and not math.isfinite(value):
            value = None
        cells.append((codes, value, status.get(flat)))
    extension = payload.get("extension") or {}
    flag_labels = {
        str(k): str(v) for k, v in ((extension.get("status") or {}).get("label") or {}).items()
    }
    return {
        "ids": ids,
        "categories": categories,
        "cells": cells,
        "flag_labels": flag_labels,
        "label": str(payload.get("label") or ""),
        "updated": payload.get("updated"),
    }


def _data_url(code: str) -> str:
    return f"{constants.DATA_URL}{code}"


async def _fetch_data(
    code: str, params: list[tuple[str, str]], lang: str
) -> tuple[dict[str, Any], bool]:
    url = _data_url(code)

    async def fetch() -> dict[str, Any]:
        response = await _get(
            url,
            params,
            constants.DATA_TIMEOUT_SECONDS,
            (
                f"{code} is not a Eurostat dataset, or has no data for this query.",
                (
                    f"{code} n'est pas un jeu de données d'Eurostat, ou n'a pas de données "
                    "pour cette requête."
                ),
            ),
            lang,
        )
        try:
            payload = response.json()
        except ValueError:
            raise_localized(
                UpstreamError,
                f"{code}: Eurostat's answer is not JSON.",
                f"{code} : la réponse d'Eurostat n'est pas du JSON.",
                lang,
            )
        try:
            return _parse_jsonstat(payload if isinstance(payload, dict) else {})
        except UpstreamUnavailable:
            raise_localized(
                UpstreamUnavailable,
                f"Eurostat queued the {code} request for asynchronous processing (it is "
                "busy, or the request is large). Narrow the filters or try again in a few "
                "minutes.",
                f"Eurostat a mis la requête {code} en file d'attente asynchrone (service "
                "chargé ou requête volumineuse). Précisez les filtres ou réessayez dans "
                "quelques minutes.",
                lang,
            )
        except UpstreamError as exc:
            raise_localized(
                UpstreamError,
                f"{code}: {exc}.",
                f"{code} : réponse JSON-stat incohérente.",
                lang,
            )

    return await cached_fetch(
        f"eurostat:data:{code}:{params}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )


def _commercial(geos: set[str]) -> tuple[CommercialUse | None, list[str]]:
    """Countries outside the EU, EFTA and candidates may not be reused commercially."""
    outside = sorted(
        g for g in geos if len(g) == 2 and g not in _COMMERCIAL_OK and g not in {"EU", "EA"}
    )
    return ("not_allowed" if outside else None), outside


def _commercial_note(outside: list[str], lang: str) -> str:
    return pick(
        lang,
        f"Data for {', '.join(outside)} (outside the EU, EFTA and candidate countries) may "
        "not be reused commercially under Eurostat's terms.",
        f"Les données de {', '.join(outside)} (hors UE, AELE et pays candidats) ne peuvent "
        "pas être réutilisées à des fins commerciales selon les conditions d'Eurostat.",
    )


async def _query(
    code: str,
    filters: Mapping[str, Sequence[str] | str] | None,
    geo: Sequence[str] | None,
    start_period: str | None,
    end_period: str | None,
    last_n: int | None,
    lang: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[str]], list[tuple[str, str]], bool]:
    _check_periods(start_period, end_period, last_n, lang)
    structure, _ = await _structure(code, lang)
    dimensions = structure["dimensions"]
    chosen = _resolve_filters(code, filters, geo, dimensions, lang)
    bound = _series_bound(chosen, dimensions)
    periods = last_n or 1
    if bound > constants.MAX_SERIES or bound * periods > constants.MAX_CELLS:
        open_dims = ", ".join(
            f"{d['id']} ({len(d['codes'])} codes)"
            for d in dimensions
            if d["id"] not in chosen and len(d["codes"]) > 1
        )
        raise_localized(
            InvalidInput,
            f"{code}: this query can match up to {bound:,} series (limit "
            f"{constants.MAX_SERIES}). Name codes in filters or geo for: {open_dims}. "
            "eurostat_describe_dataset lists the codes.",
            f"{code} : cette requête peut correspondre à {fr_number(bound)} séries (limite "
            f"{constants.MAX_SERIES}). Précisez des codes dans filters ou geo pour : "
            f"{open_dims}. eurostat_describe_dataset donne les codes.",
            lang,
        )
    params = _data_params(chosen, start_period, end_period, last_n, lang)
    parsed, cached = await _fetch_data(code, params, lang)
    return structure, parsed, chosen, params, cached


async def get_data(
    dataset: str,
    filters: Mapping[str, Sequence[str] | str] | None = None,
    geo: Sequence[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> DataResult:
    lang = normalize_lang(lang)
    code = _check_code(dataset, lang)
    notes: list[str] = []
    if last_n is None and not start_period and not end_period:
        last_n = constants.DEFAULT_LAST_N
        notes.append(
            pick(
                lang,
                f"No period given: the last {last_n} periods. Use start_period, end_period "
                "or last_n for others.",
                f"Aucune période donnée : les {last_n} dernières périodes. Utilisez "
                "start_period, end_period ou last_n pour d'autres.",
            )
        )
    structure, parsed, chosen, params, cached = await _query(
        code, filters, geo, start_period, end_period, last_n, lang
    )
    ids = parsed["ids"]
    categories = parsed["categories"]
    cells = parsed["cells"]
    if not cells:
        raise_localized(
            NotFound,
            f"{code} has no values for these filters and periods. eurostat_describe_dataset "
            "lists the codes with data; some combinations are still empty.",
            f"{code} n'a aucune valeur pour ces filtres et périodes. "
            "eurostat_describe_dataset donne les codes avec données ; certaines combinaisons "
            "restent vides.",
            lang,
        )
    used: dict[str, set[str]] = {i: set() for i in ids}
    for codes, _, _ in cells:
        for dim_id, c in codes.items():
            used[dim_id].add(c)
    row_dims = {"geo", "time", "unit"}
    fixed = {
        i: Code(id=next(iter(used[i])), label=categories[i][1].get(next(iter(used[i])), ""))
        for i in ids
        if i not in row_dims and len(used[i]) == 1
    }
    varying_ids = [i for i in ids if i not in row_dims and len(used[i]) > 1]
    varying = {i: {c: categories[i][1].get(c, c) for c in sorted(used[i])} for i in varying_ids}
    flag_labels: dict[str, str] = {}
    rows = []
    for codes, value, flag in cells:
        label = _flag_label(flag, lang, parsed["flag_labels"]) if flag else None
        if flag and label:
            flag_labels[flag] = label
        geo_code = codes.get("geo")
        unit_code = codes.get("unit")
        rows.append(
            Row(
                geo=geo_code,
                geo_label=categories["geo"][1].get(geo_code) if geo_code else None,
                time=codes.get("time", ""),
                unit=unit_code,
                unit_label=categories["unit"][1].get(unit_code) if unit_code else None,
                value=value,
                flag=flag,
                flag_label=label,
                dimensions={i: codes[i] for i in varying_ids},
            )
        )
    total = len(rows)
    if total > constants.MAX_ROWS:
        rows = rows[: constants.MAX_ROWS]
        notes.append(
            pick(
                lang,
                f"First {constants.MAX_ROWS:,} of {total:,} rows. Narrow the filters or "
                "periods for the rest.",
                f"{fr_number(constants.MAX_ROWS)} premières lignes sur {fr_number(total)}. "
                "Précisez les filtres ou les périodes pour le reste.",
            )
        )
    asked_geo = chosen.get("geo", [])
    with_values = {c["geo"] for c, v, _ in cells if v is not None and "geo" in c}
    missing = [g for g in asked_geo if g not in with_values]
    use, outside = _commercial(used.get("geo", set()))
    if outside:
        notes.append(_commercial_note(outside, lang))
    title = parsed["label"] or _label(structure["names"], lang) or code
    return DataResult(
        dataset=code,
        title=title,
        updated=parsed["updated"],
        fixed=fixed,
        varying=varying,
        rows=rows,
        total_rows=total,
        flags=[FlagLabel(flag=f, label=lbl) for f, lbl in sorted(flag_labels.items())],
        missing_geo=missing,
        databrowser_url=_browser_url(code, lang),
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(code), params=params)),
            cached=cached,
            schema_name="eurostat.DataResult",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Cells with neither a value nor a flag are left out. Labels as Eurostat "
                "publishes them.",
                "Les cellules sans valeur ni indicateur sont omises. Libellés tels que publiés "
                "par Eurostat.",
            ),
            licence=_licence(lang),
            commercial_use=use,
            lang=lang,
        ),
    )


# ---------------------------------------------------------------- comparison


async def compare(
    indicator: str,
    geo: Sequence[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> Comparison:
    lang = normalize_lang(lang)
    name = indicator.strip().lower()
    spec = constants.INDICATORS.get(name)
    if spec is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other series "
            "use eurostat_get_data.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série, utilisez eurostat_get_data.",
            lang,
        )
    if last_n is None and not start_period and not end_period:
        last_n = constants.DEFAULT_LAST_N
    filters: dict[str, list[str] | str] = {k: [v] for k, v in spec.filters.items()}
    asked = list(geo) if geo else list(constants.DEFAULT_COMPARE_GEO)
    _, parsed, chosen, params, cached = await _query(
        spec.dataset, filters, asked, start_period, end_period, last_n, lang
    )
    geo_labels = parsed["categories"].get("geo", ([], {}))[1]
    by_geo: dict[str, list[Observation]] = {}
    flag_labels = parsed["flag_labels"]
    for codes, value, flag in parsed["cells"]:
        g = codes.get("geo")
        if g is None:
            continue
        by_geo.setdefault(g, []).append(
            Observation(
                time=codes.get("time", ""),
                value=value,
                flag=flag,
                flag_label=_flag_label(flag, lang, flag_labels) if flag else None,
            )
        )
    series = []
    for g in chosen.get("geo", []):
        observations = sorted(by_geo.get(g, []), key=lambda o: o.time)
        valued = [o for o in observations if o.value is not None]
        if not valued:
            continue
        latest = valued[-1]
        series.append(
            GeoSeries(
                geo=g,
                geo_label=geo_labels.get(g, g),
                observations=observations,
                latest_time=latest.time,
                latest_value=latest.value,
                latest_flag=latest.flag,
            )
        )
    missing = [g for g in chosen.get("geo", []) if g not in {s.geo for s in series}]
    if not series:
        raise_localized(
            NotFound,
            f"Eurostat has no {name} values for these places and periods.",
            f"Eurostat n'a aucune valeur {name} pour ces lieux et périodes.",
            lang,
        )
    notes: list[str] = []
    if missing:
        notes.append(
            pick(
                lang,
                f"No values for: {', '.join(missing)} (not in {spec.dataset}, or no data in "
                "the periods asked for).",
                f"Aucune valeur pour : {', '.join(missing)} (absents de {spec.dataset}, ou "
                "sans données pour les périodes demandées).",
            )
        )
    use, outside = _commercial({s.geo for s in series})
    if outside:
        notes.append(_commercial_note(outside, lang))
    return Comparison(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        dataset=spec.dataset,
        filters=dict(spec.filters),
        series=series,
        canada_counterpart=pick(lang, spec.canada_en, spec.canada_fr),
        missing_geo=missing,
        databrowser_url=_browser_url(spec.dataset, lang),
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_data_url(spec.dataset), params=params)),
            cached=cached,
            schema_name="eurostat.Comparison",
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                f"Eurostat dataset {spec.dataset} ({parsed['label']}). Canada is not in "
                "Eurostat: canada_counterpart names the MapleStats source to pair with.",
                f"Jeu de données {spec.dataset} d'Eurostat ({parsed['label']}). Le Canada est "
                "absent d'Eurostat : canada_counterpart indique la source MapleStats à "
                "mettre en regard.",
            ),
            licence=_licence(lang),
            commercial_use=use,
            lang=lang,
        ),
    )
