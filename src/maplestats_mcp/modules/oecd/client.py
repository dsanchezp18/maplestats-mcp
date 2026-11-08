"""Client for the OECD Data Explorer SDMX REST API (sdmx.oecd.org/public/rest).

Checked live on 2026-11-07 with the project's User-Agent, no key:

- `dataflow/all` (SDMX-JSON) lists 1,552 dataflows from 40 agencies, nearly
  all OECD directorates (OECD.ECO.MAD, OECD.SDD.TPS...), plus ESTAT and
  IAEG-SDGs. Ids are unique across agencies. Names and descriptions are
  English only (one flow has a French name); descriptions are HTML. 27
  flows are `isExternalReference` stubs pointing at the archive space,
  without a structure here. The whole list is about 6 MB, so it is cached
  for a day and kept slimmed.
- `dataflow/{agency}/{id}/latest?references=all&detail=referencepartial`
  returns the DSD, codelists (not cut: EO's CL_AREA has 447 codes), concept
  schemes and an "Actual" content constraint whose cube region lists the
  codes that have data (EO: 65 areas), with `validFrom` (last update), an
  `obs_count` annotation and the time range. Keys are checked against that
  constraint here, since every query costs one of the hourly downloads.
  With `Accept-Language: fr` codes and concepts come in French where the
  OECD has them.
- `data/{agency},{id},/{key}` with the SDMX-CSV 2.0 media type and
  `labels=both` gives one row per observation, unsorted, headers like
  `REF_AREA: Zone de référence` and cells like `CAN: Canada`; some labels
  are empty (`0: `). An empty key part is a wildcard and `+` joins codes.
  `startPeriod`, `endPeriod` and `lastNObservations` filter periods.
- No data for a key and an unknown code both answer 404 `NoRecordsFound`
  (text/plain); an unknown dataflow's structure answers 404 "No Results
  Found". A key with too few parts answers 403 "Not enough key values in
  query" (BIS widens it instead). lastNObservations answers 413 on a dozen
  very large datasets (OECD page "restrictions on specific API parameters").

Limits: the API best-practices page (2026-03-18) allows 60 data downloads an
hour, after which requests are blocked for a while; this client spends at
most constants.DATA_BUDGET_PER_HOUR of them, caches every answer and fails a
call that would exceed the budget with the wait, without sending it. It uses
its own client without retries: a retried 429 or 5xx would spend more of the
budget, and the OECD may block an address it sees straining the service.
"""

from __future__ import annotations

import csv
import html
import io
import math
import re
import time
from collections import deque
from datetime import UTC, date, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.oecd import constants
from maplestats_mcp.modules.oecd.schemas import (
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
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.models import CommercialUse
from maplestats_mcp.shared.rate_limiter import get_limiter

_client = new_client(timeout=constants.DATA_TIMEOUT_SECONDS)

_FRESHNESS = {
    "en": (
        "Updated on each dataset's own schedule: most once or twice a year, the composite "
        "leading indicators monthly, unit labour costs quarterly, the Economic Outlook in June "
        "and December."
    ),
    "fr": (
        "Mis à jour selon le calendrier de chaque jeu de données : la plupart une ou deux fois "
        "par an, les indicateurs composites avancés chaque mois, les coûts unitaires de "
        "main-d'œuvre chaque trimestre, les Perspectives économiques en juin et en décembre."
    ),
}

# SDMX reporting periods: 2026, 2026-Q1, 2026-S1, 2026-09, 2026-M09, 2026-09-30.
_PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|S[12]|A1|W\d{2}|M?\d{2}(-\d{2})?))?$")
_DATASET = re.compile(r"^(?:([A-Za-z0-9_.\-]+)[,:])?([A-Za-z0-9_@\-]+)$")
_CODE = r"[A-Za-z0-9_\-]+"
_KEY_PART = re.compile(rf"^(\*|{_CODE}(\+{_CODE})*)?$")
_AREA = re.compile(r"^[A-Z0-9_]{2,12}$")
_TAG = re.compile(r"<[^>]+>")
_HIDDEN = re.compile(r"<div[^>]*visibility:\s*hidden[^>]*>.*?</div>", re.IGNORECASE | re.DOTALL)
_WORD = re.compile(r"[a-z0-9]+")
# Phrases in a dataflow's description that point at data the OECD does not own.
_THIRD_PARTY = re.compile(
    r"third[- ]party data|©|\bcopyright\b|all rights reserved|may not be (?:reproduced|"
    r"redistributed)",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    {"the", "of", "and", "in", "for", "by", "on", "to", "a", "an", "data", "dataset",
     "datasets", "canada", "countries", "country"}
)  # fmt: skip


_PRESET_FLOWS = frozenset(spec.dataflow for spec in constants.INDICATORS.values())


def _lang(lang: str) -> str:
    return normalize_lang(lang)


# ------------------------------------------------------------------ budget


class _DownloadBudget:
    """The server's share of the OECD's 60 data downloads an hour.

    Per process and in memory, like the rate limiter. Only data requests that
    reach the OECD count (cache hits do not); a 429 blocks every request
    until its Retry-After, or COOLDOWN_SECONDS without one.
    """

    def __init__(self) -> None:
        self._times: deque[float] = deque()
        self._blocked_until = 0.0

    def reset(self) -> None:
        self._times.clear()
        self._blocked_until = 0.0

    def _wait(self, now: float, data: bool) -> float:
        if now < self._blocked_until:
            return self._blocked_until - now
        if not data:
            return 0.0
        while self._times and now - self._times[0] >= 3600:
            self._times.popleft()
        if len(self._times) >= constants.DATA_BUDGET_PER_HOUR:
            return 3600 - (now - self._times[0])
        return 0.0

    def spend(self, lang: str, *, data: bool) -> None:
        now = time.monotonic()
        wait = self._wait(now, data)
        if wait > 0:
            minutes = max(1, math.ceil(wait / 60))
            raise_localized(
                UpstreamUnavailable,
                f"The OECD API allows {constants.DATA_DOWNLOADS_PER_HOUR} data downloads an hour "
                "and this server has used its share; try again in about "
                f"{minutes} minute{'s' if minutes > 1 else ''}. Answers already fetched stay "
                "available from the cache.",
                f"l'API de l'OCDE permet {constants.DATA_DOWNLOADS_PER_HOUR} téléchargements de "
                "données par heure et ce serveur a utilisé sa part ; réessayez dans environ "
                f"{minutes} minute{'s' if minutes > 1 else ''}. Les réponses déjà obtenues "
                "restent disponibles dans le cache.",
                lang,
            )
        if data:
            self._times.append(now)

    def block(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)


BUDGET = _DownloadBudget()


# -------------------------------------------------------------------- HTTP


def _raise_unavailable(url: str, detail: str, lang: str) -> NoReturn:
    raise_localized(
        UpstreamUnavailable,
        f"The OECD Data Explorer API did not answer ({url}): {detail}. Try again in a minute.",
        f"l'API de l'Explorateur de données de l'OCDE n'a pas répondu ({url}) : {detail}. "
        "Réessayez dans une minute.",
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
    data: bool,
) -> httpx.Response:
    BUDGET.spend(lang, data=data)
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
    if status == 429:
        wait = retry_after_seconds(response.headers.get("Retry-After", ""))
        BUDGET.block(wait if wait is not None else constants.COOLDOWN_SECONDS)
        raise_localized(
            UpstreamUnavailable,
            "The OECD API answered HTTP 429: its limit of "
            f"{constants.DATA_DOWNLOADS_PER_HOUR} data downloads an hour is reached. This server "
            "sends no more requests to it for a while; try again later.",
            "l'API de l'OCDE a répondu HTTP 429 : sa limite de "
            f"{constants.DATA_DOWNLOADS_PER_HOUR} téléchargements de données par heure est "
            "atteinte. Ce serveur ne lui envoie plus de requêtes pendant un moment ; réessayez "
            "plus tard.",
            lang,
        )
    if status == 413:
        raise_localized(
            InvalidInput,
            "The OECD refuses last_n (lastNObservations) on this very large dataset (HTTP 413); "
            "use start_period instead.",
            "l'OCDE refuse last_n (lastNObservations) pour ce très grand jeu de données "
            "(HTTP 413) ; utilisez plutôt start_period.",
            lang,
        )
    if status >= 500:
        _raise_unavailable(url, f"HTTP {status}", lang)
    raise_localized(
        UpstreamError,
        f"The OECD Data Explorer API answered HTTP {status} for {url}: {body}",
        f"l'API de l'Explorateur de données de l'OCDE a répondu HTTP {status} pour {url} : {body}",
        lang,
    )


# --------------------------------------------------------------- catalogue


def _catalogue_url() -> str:
    return f"{constants.BASE_URL}dataflow/all"


def _plain(text: str) -> str:
    text = _HIDDEN.sub(" ", text)
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


def _owner_note(agency: str, description: str) -> str:
    """Why a dataflow may not be OECD-owned data, or "" when nothing says so."""
    if not agency.startswith("OECD"):
        return f"published by {agency}"
    match = _THIRD_PARTY.search(_plain(description))
    return f"its description says '{match.group(0)}'" if match else ""


async def _catalogue(lang: str) -> tuple[dict[str, dict[str, Any]], bool]:
    url = _catalogue_url()

    async def fetch() -> dict[str, dict[str, Any]]:
        response = await _get(
            url,
            None,
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
            not_found=(
                "The OECD dataflow list was not found.",
                "la liste des jeux de données de l'OCDE est introuvable.",
            ),
            lang="en",
            data=False,
        )
        payload = decode_json(response, url) or {}
        catalogue: dict[str, dict[str, Any]] = {}
        for flow in list_or_empty(payload.get("data") or {}, "dataflows"):
            if not isinstance(flow, dict) or not flow.get("id") or not flow.get("agencyID"):
                continue
            description = str(flow.get("description") or "")
            links = [
                str(link.get("href"))
                for link in list_or_empty(flow, "links")
                if isinstance(link, dict) and link.get("href")
            ]
            catalogue[str(flow["id"])] = {
                "agency": str(flow["agencyID"]),
                "version": str(flow.get("version") or ""),
                "name": str(flow.get("name") or flow["id"]),
                # The hidden keyword block helps search but not a reader.
                "search": " ".join(html.unescape(_TAG.sub(" ", description)).split()).lower(),
                "description": _plain(description)[: constants.MAX_DESCRIPTION_CHARS * 3],
                "archived": bool(flow.get("isExternalReference")),
                "archive_url": links[0] if links else "",
                "owner_note": _owner_note(str(flow["agencyID"]), description),
            }
        if not catalogue:
            raise_localized(
                UpstreamError,
                "The OECD dataflow list came back empty.",
                "la liste des jeux de données de l'OCDE est revenue vide.",
                lang,
            )
        return catalogue

    return await cached_fetch("oecd:catalogue", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch)


def _explorer_url(agency: str, fid: str) -> str:
    return str(
        httpx.URL(
            constants.EXPLORER_URL,
            params={"df[ds]": "dsDisseminateFinalDMZ", "df[id]": fid, "df[ag]": agency},
        )
    )


def _short(text: str) -> str:
    if len(text) <= constants.MAX_DESCRIPTION_CHARS:
        return text
    return text[: constants.MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _summary(fid: str, info: dict[str, Any]) -> DatasetSummary:
    return DatasetSummary(
        id=fid,
        agency=info["agency"],
        version=info["version"],
        name=info["name"],
        description=_short(info["description"]),
        archived=info["archived"],
        explorer_url=_explorer_url(info["agency"], fid),
    )


def _licence(info: dict[str, Any], lang: str) -> tuple[str, CommercialUse]:
    base = constants.LICENCE_FR if lang == "fr" else constants.LICENCE
    note = info.get("owner_note") or ""
    if not note:
        return base, "allowed"
    warning = constants.THIRD_PARTY_WARNING_FR if lang == "fr" else constants.THIRD_PARTY_WARNING
    return f"{warning.format(reason=note)} {base}", "varies"


def _catalogue_provenance(schema: str, lang: str, cached: bool) -> Any:
    return make_provenance(
        source=constants.SOURCE,
        url=_catalogue_url(),
        cached=cached,
        schema_name=schema,
        freshness=_FRESHNESS[lang],
        coverage=pick(
            lang,
            "Every dataflow of the OECD Data Explorer's public space. Names and descriptions "
            "are in English only upstream.",
            "Tous les jeux de données de l'espace public de l'Explorateur de données de "
            "l'OCDE. Les noms et descriptions n'existent qu'en anglais à la source.",
        ),
        limits=pick(lang, constants.LIMITS, constants.LIMITS_FR),
        licence=pick(lang, constants.LICENCE, constants.LICENCE_FR),
        commercial_use="allowed",
        lang=lang,
    )


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS]


async def search_datasets(query: str, limit: int = 10, lang: str = "en") -> DatasetSearch:
    lang = _lang(lang)
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
            "Give a few English words to search for, e.g. 'house prices', 'productivity', "
            "'tax revenue', 'economic outlook'.",
            "donnez quelques mots en anglais à chercher, p. ex. « house prices », "
            "« productivity », « tax revenue », « economic outlook » (les noms des jeux de "
            "données de l'OCDE n'existent qu'en anglais).",
            lang,
        )
    catalogue, cached = await _catalogue(lang)
    scored = []
    for fid, info in catalogue.items():
        name_words = set(_WORD.findall(info["name"].lower()))
        search_words = set(_WORD.findall(info["search"]))
        id_text = fid.lower()
        matched = 0
        score = 0.0
        for word in words:
            hit = False
            if word in name_words:
                score += 3
                hit = True
            elif any(n.startswith(word) for n in name_words if len(word) >= 4):
                score += 2
                hit = True
            if word in search_words:
                score += 1
                hit = True
            if len(word) >= 3 and word in id_text:
                score += 2
                hit = True
            matched += hit
        if not matched:
            continue
        # Datasets matching every word first; archived ones and older Economic
        # Outlook editions after the live ones.
        score += 10 * (matched == len(words))
        score -= 5 * info["archived"]
        # The datasets behind the preset comparisons are the ones most asked for.
        score += 2 * (fid in _PRESET_FLOWS)
        scored.append((-score, len(info["name"]), fid))
    scored.sort()
    datasets = [_summary(fid, catalogue[fid]) for _, _, fid in scored[:limit]]
    return DatasetSearch(
        query=query,
        total_matches=len(scored),
        datasets=datasets,
        provenance=_catalogue_provenance("oecd.DatasetSearch", lang, cached),
    )


async def _dataflow(dataset: str, lang: str) -> tuple[str, dict[str, Any]]:
    match = _DATASET.match(dataset.strip())
    if not match:
        raise_localized(
            InvalidInput,
            f"{dataset!r} is not an OECD dataset id (e.g. DSD_EO@DF_EO, or "
            "OECD.ECO.MAD,DSD_EO@DF_EO). oecd_search_datasets finds them.",
            f"{dataset!r} n'est pas un identifiant de jeu de données de l'OCDE (p. ex. "
            "DSD_EO@DF_EO, ou OECD.ECO.MAD,DSD_EO@DF_EO). oecd_search_datasets les trouve.",
            lang,
        )
    agency, fid = match.group(1), match.group(2)
    catalogue, _ = await _catalogue(lang)
    info = catalogue.get(fid) or next(
        (v for k, v in catalogue.items() if k.upper() == fid.upper()), None
    )
    if info is not None:
        fid = next(k for k, v in catalogue.items() if v is info)
    if info is None or (agency and agency.upper() != info["agency"].upper()):
        raise_localized(
            NotFound,
            f"{dataset} is not an OECD Data Explorer dataset. Search with oecd_search_datasets.",
            f"{dataset} n'est pas un jeu de données de l'Explorateur de l'OCDE. Cherchez avec "
            "oecd_search_datasets.",
            lang,
        )
    if info["archived"]:
        raise_localized(
            NotFound,
            f"{fid} is an archived OECD dataset, not served by this module: "
            f"{info['archive_url'] or 'see the OECD Data Explorer'}.",
            f"{fid} est un jeu de données archivé de l'OCDE, non servi par ce module : "
            f"{info['archive_url'] or 'voir l’Explorateur de données de l’OCDE'}.",
            lang,
        )
    return fid, info


# ---------------------------------------------------------------- structure


def _urn_key(urn: str) -> str:
    """'urn:...Codelist=OECD:CL_AREA(1.0)' -> 'OECD:CL_AREA(1.0)'."""
    return urn.split("=", 1)[-1]


def _structure_url(agency: str, fid: str) -> str:
    return f"{constants.BASE_URL}dataflow/{agency}/{fid}/latest"


_STRUCTURE_PARAMS = {"references": "all", "detail": "referencepartial"}


def _constraint(data: dict[str, Any], fid: str) -> dict[str, Any]:
    """Codes with data, last update, observation count and time range."""
    constraints = [c for c in list_or_empty(data, "contentConstraints") if isinstance(c, dict)]
    chosen = next(
        (
            c
            for c in constraints
            if c.get("type") == "Actual"
            and any(
                f":{fid}(" in str(u)
                for u in list_or_empty(c.get("constraintAttachment") or {}, "dataflows")
            )
        ),
        constraints[0] if len(constraints) == 1 else None,
    )
    result: dict[str, Any] = {"values": {}, "updated": None, "count": None, "start": None}
    if chosen is None:
        return result
    result["updated"] = chosen.get("validFrom")
    for note in list_or_empty(chosen, "annotations"):
        if isinstance(note, dict) and note.get("id") == "obs_count":
            try:
                result["count"] = int(str(note.get("title")))
            except ValueError:
                pass
    for region in list_or_empty(chosen, "cubeRegions"):
        if not isinstance(region, dict) or region.get("isIncluded") is False:
            continue
        for kv in list_or_empty(region, "keyValues"):
            if not isinstance(kv, dict) or not kv.get("id"):
                continue
            if kv.get("values"):
                result["values"][str(kv["id"])] = [str(v) for v in kv["values"]]
            span = kv.get("timeRange") or {}
            if span:
                result["start"] = str((span.get("startPeriod") or {}).get("period") or "")[:10]
                result["end"] = str((span.get("endPeriod") or {}).get("period") or "")[:10]
    return result


async def _structure(fid: str, info: dict[str, Any], lang: str) -> tuple[dict[str, Any], bool]:
    url = _structure_url(info["agency"], fid)

    async def fetch() -> dict[str, Any]:
        response = await _get(
            url,
            _STRUCTURE_PARAMS,
            accept=constants.STRUCTURE_ACCEPT,
            timeout=constants.STRUCTURE_TIMEOUT_SECONDS,
            not_found=(
                f"No structure for OECD dataset {fid}.",
                f"aucune structure pour le jeu de données {fid} de l'OCDE.",
            ),
            lang=lang,
            data=False,
        )
        data = (decode_json(response, url) or {}).get("data") or {}
        flow = next(
            (f for f in list_or_empty(data, "dataflows") if isinstance(f, dict) and f.get("id")),
            {},
        )
        wanted = _urn_key(str(flow.get("structure") or ""))
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
        constraint = _constraint(data, fid)
        components = dsd.get("dataStructureComponents") or {}
        dims = list_or_empty(components.get("dimensionList") or {}, "dimensions")
        dimensions = []
        for dim in sorted(
            (d for d in dims if isinstance(d, dict)), key=lambda d: int(d.get("position") or 0)
        ):
            dim_id = str(dim.get("id") or "")
            enumeration = (dim.get("localRepresentation") or {}).get("enumeration") or ""
            names = {
                str(c["id"]): str(c.get("name") or c["id"])
                for c in list_or_empty(codelists.get(_urn_key(enumeration)) or {}, "codes")
                if isinstance(c, dict) and c.get("id")
            }
            used = constraint["values"].get(dim_id)
            ids = used if used is not None else list(names)
            dimensions.append(
                {
                    "id": dim_id,
                    "name": concepts.get(dim_id) or dim_id,
                    "codes": [[code, names.get(code, code)] for code in ids],
                    "constrained": used is not None,
                }
            )
        if not dimensions:
            raise_localized(
                UpstreamError,
                f"{fid}: the data structure lists no dimensions.",
                f"{fid} : la structure ne contient aucune dimension.",
                lang,
            )
        return {
            "dimensions": dimensions,
            "name": str(flow.get("name") or info["name"]),
            "version": str(flow.get("version") or info["version"]),
            "updated": constraint["updated"],
            "count": constraint["count"],
            "start": constraint.get("start"),
            "end": constraint.get("end"),
        }

    return await cached_fetch(
        f"oecd:structure:{fid}:{lang}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )


def _example_key(dimensions: list[dict[str, Any]]) -> str:
    """A key for Canada: CAN where a dimension has it, the only code of a
    one-code dimension, a wildcard (empty part) elsewhere."""
    parts = []
    for dim in dimensions:
        ids = [c[0] for c in dim["codes"]]
        if constants.CANADA in ids:
            parts.append(constants.CANADA)
        elif len(ids) == 1:
            parts.append(ids[0])
        else:
            parts.append("")
    return ".".join(parts)


def _updated(structure: dict[str, Any]) -> datetime | None:
    raw = structure.get("updated")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _citation(fid: str, info: dict[str, Any], structure: dict[str, Any], lang: str) -> str:
    updated = _updated(structure)
    year = (updated or datetime.now(UTC)).year
    today = date.today().isoformat()
    return pick(
        lang,
        f"OECD ({year}), {structure['name']}, OECD Data Explorer, "
        f"{_explorer_url(info['agency'], fid)} (accessed on {today}).",
        f"OCDE ({year}), {structure['name']}, Explorateur de données de l'OCDE, "
        f"{_explorer_url(info['agency'], fid)} (consulté le {today}).",
    )


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
    licence, commercial = _licence(info, lang)
    updated = _updated(structure)
    return DatasetStructure(
        id=fid,
        agency=info["agency"],
        version=structure["version"],
        name=structure["name"],
        description=_short(info["description"]),
        last_updated=updated.isoformat() if updated else None,
        observation_count=structure["count"],
        first_period=structure.get("start"),
        last_period=structure.get("end"),
        dimensions=dimensions,
        key_template=".".join(d["id"] for d in structure["dimensions"]),
        example_key=_example_key(structure["dimensions"]),
        citation=_citation(fid, info, structure, lang),
        explorer_url=_explorer_url(info["agency"], fid),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(_structure_url(info["agency"], fid), params=_STRUCTURE_PARAMS)),
            cached=cached,
            schema_name="oecd.DatasetStructure",
            as_of=updated,
            freshness=_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Codes are those the OECD's availability constraint lists as having data in "
                "this dataset.",
                "Les codes sont ceux que la contrainte de disponibilité de l'OCDE déclare comme "
                "ayant des données dans ce jeu.",
            ),
            limits=pick(lang, constants.LIMITS, constants.LIMITS_FR),
            licence=licence,
            commercial_use=commercial,
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
    if start_period:
        params["startPeriod"] = start_period.strip()
    if end_period:
        params["endPeriod"] = end_period.strip()
    if last_n is not None:
        params["lastNObservations"] = last_n
    return params


def _data_url(agency: str, fid: str, key: str) -> str:
    return f"{constants.BASE_URL}data/{agency},{fid},/{key}"


def _check_key(key: str, dimensions: list[dict[str, Any]], fid: str, lang: str) -> str:
    """Normalise `key` and check each code against the codes with data, so a
    typo costs no download (the OECD answers it 404, like a key without data)."""
    template = ".".join(d["id"] for d in dimensions)
    example = _example_key(dimensions)
    parts = key.strip().split(".")
    if len(parts) != len(dimensions) or not all(_KEY_PART.match(p.strip()) for p in parts):
        raise_localized(
            InvalidInput,
            f"{key!r} is not a key for {fid}: it needs {len(dimensions)} parts in the order "
            f"{template}, each a code, codes joined by +, empty (or *) for all (e.g. "
            f"{example!r}). oecd_describe_dataset lists the codes.",
            f"{key!r} n'est pas une clé de {fid} : il faut {len(dimensions)} parties dans "
            f"l'ordre {template}, chacune un code, des codes joints par +, vide (ou *) pour "
            f"tous (p. ex. {example!r}). oecd_describe_dataset donne les codes.",
            lang,
        )
    normalised = []
    for part, dim in zip(parts, dimensions, strict=True):
        part = part.strip()
        if part in ("", "*"):
            normalised.append("")
            continue
        known = {c[0].upper(): c[0] for c in dim["codes"]}
        codes = []
        for code in part.split("+"):
            canonical = known.get(code.upper())
            if canonical is None and dim["constrained"]:
                sample = ", ".join(c[0] for c in dim["codes"][:20])
                more = "…" if len(dim["codes"]) > 20 else ""
                raise_localized(
                    InvalidInput,
                    f"{code} is not a {dim['id']} code with data in {fid}. Codes: {sample}{more} "
                    "(oecd_describe_dataset lists them all).",
                    f"{code} n'est pas un code {dim['id']} ayant des données dans {fid}. Codes : "
                    f"{sample}{more} (oecd_describe_dataset les énumère tous).",
                    lang,
                )
            codes.append(canonical or code)
        normalised.append("+".join(codes))
    return ".".join(normalised)


def _max_series(key: str, dimensions: list[dict[str, Any]]) -> int:
    """Upper bound on the number of series a key can match (codes with data)."""
    total = 1
    for part, dim in zip(key.split("."), dimensions, strict=True):
        total *= len(part.split("+")) if part else max(1, len(dim["codes"]))
    return total


def _split(cell: str) -> tuple[str, str]:
    """'CAN: Canada' -> ('CAN', 'Canada'); '0: ' -> ('0', '0')."""
    code, sep, label = cell.partition(":")
    code, label = code.strip(), label.strip()
    return (code, label or code) if sep else (cell.strip(), cell.strip())


_SERIES_ATTRIBUTES = ("UNIT_MEASURE", "UNIT_MULT", "BASE_PER")


def _parse_csv(
    text: str, dimensions: list[dict[str, Any]]
) -> list[tuple[list[DimensionValue], dict[str, str], list[tuple[str, float, str | None]]]]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return []
    columns = [h.split(":", 1)[0].strip() for h in header]
    index = {c: i for i, c in enumerate(columns)}
    dim_ids = [d["id"] for d in dimensions]
    if (
        "TIME_PERIOD" not in index
        or "OBS_VALUE" not in index
        or any(d not in index for d in dim_ids)
    ):
        raise UpstreamError(f"unexpected SDMX-CSV columns: {', '.join(columns)}")

    series: dict[
        tuple[str, ...],
        tuple[list[DimensionValue], dict[str, str], list[tuple[str, float, str | None]]],
    ] = {}
    for row in reader:
        if len(row) < len(columns):
            row = row + [""] * (len(columns) - len(row))
        period = row[index["TIME_PERIOD"]].strip()
        if not period:
            continue
        values = [_split(row[index[d]]) for d in dim_ids]
        codes = tuple(v[0] for v in values)
        entry = series.get(codes)
        if entry is None:
            dims = [
                DimensionValue(id=d, code=code, label=label)
                for d, (code, label) in zip(dim_ids, values, strict=True)
            ]
            entry = series[codes] = (dims, {}, [])
        for name in _SERIES_ATTRIBUTES:
            cell = row[index[name]].strip() if name in index else ""
            if cell:
                entry[1].setdefault(name, cell)
        raw = row[index["OBS_VALUE"]].strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        status_cell = row[index["OBS_STATUS"]].strip() if "OBS_STATUS" in index else ""
        status = _split(status_cell)[1] if status_cell else None
        entry[2].append((period, value, status))
    return list(series.values())


async def _fetch(
    fid: str,
    info: dict[str, Any],
    key: str,
    params: dict[str, Any],
    dimensions: list[dict[str, Any]],
    lang: str,
) -> tuple[list[tuple[SeriesInfo, list[DataRow]]], bool, str]:
    url = _data_url(info["agency"], fid, key)
    # `format=csvfilewithlabels` makes the same URL answer CSV with labels and
    # no Accept header, so it opens in a browser, Excel or read.csv as is.
    csv_url = str(httpx.URL(url, params={**params, "format": "csvfilewithlabels"}))

    async def fetch() -> str:
        response = await _get(
            url,
            params,
            accept=constants.DATA_ACCEPT,
            timeout=constants.DATA_TIMEOUT_SECONDS,
            not_found=(
                f"No data in OECD dataset {fid} for key {key!r}"
                + (" in the periods asked for" if params else "")
                + ". Check the codes with oecd_describe_dataset.",
                f"aucune donnée dans le jeu {fid} de l'OCDE pour la clé {key!r}"
                + (" pour les périodes demandées" if params else "")
                + ". Vérifiez les codes avec oecd_describe_dataset.",
            ),
            lang=lang,
            data=True,
        )
        return response.text

    text, cached = await cached_fetch(
        f"oecd:data:{fid}:{key}:{sorted(params.items())}:{lang}",
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
    dim_ids = [d["id"] for d in dimensions]
    result = []
    for dims, attrs, observations in parsed:
        if not observations:
            continue
        observations.sort(key=lambda o: o[0])
        series_key = ".".join(d.code for d in dims)
        area = dims[dim_ids.index("REF_AREA")] if "REF_AREA" in dim_ids else None
        freq = dims[dim_ids.index("FREQ")] if "FREQ" in dim_ids else None
        unit = _split(attrs["UNIT_MEASURE"])[1] if attrs.get("UNIT_MEASURE") else None
        multiplier = _split(attrs["UNIT_MULT"])[1] if attrs.get("UNIT_MULT") else None
        info_row = SeriesInfo(
            key=series_key,
            ref_area=area.code if area else None,
            ref_area_name=area.label if area else None,
            frequency=freq.label if freq else None,
            unit=unit,
            unit_multiplier=multiplier,
            base_period=_split(attrs["BASE_PER"])[0] if attrs.get("BASE_PER") else None,
            dimensions=dims,
            observation_count=len(observations),
            latest_period=observations[-1][0],
            latest_value=observations[-1][1],
        )
        rows = [
            DataRow(
                series_key=series_key,
                ref_area=info_row.ref_area,
                period=period,
                value=value,
                unit=unit,
                frequency=info_row.frequency,
                status=status,
            )
            for period, value, status in observations
        ]
        result.append((info_row, rows))
    result.sort(key=lambda item: item[0].key)
    return result, cached, csv_url


def _too_broad(fid: str, key: str, bound: int, lang: str) -> NoReturn:
    raise_localized(
        InvalidInput,
        f"{fid} key {key!r} can match up to {bound:,} series. Name more codes, or add last_n or "
        "start_period to keep the answer small (each query spends one of the OECD's hourly "
        "downloads).",
        f"la clé {key!r} de {fid} peut correspondre à {fr_number(bound)} séries. Précisez des "
        "codes, ou ajoutez last_n ou start_period pour garder la réponse courte (chaque "
        "requête consomme un des téléchargements horaires de l'OCDE).",
        lang,
    )


def _data_provenance(
    fid: str,
    info: dict[str, Any],
    key: str,
    params: dict[str, Any],
    structure: dict[str, Any],
    cached: bool,
    schema: str,
    lang: str,
    limits: str | None = None,
) -> Any:
    licence, commercial = _licence(info, lang)
    base_limits = pick(lang, constants.LIMITS, constants.LIMITS_FR)
    return make_provenance(
        source=constants.SOURCE,
        url=str(httpx.URL(_data_url(info["agency"], fid, key), params=params)),
        cached=cached,
        schema_name=schema,
        as_of=_updated(structure),
        freshness=_FRESHNESS[lang],
        coverage=pick(
            lang,
            f"OECD dataset {fid} ({structure['name']}), key {key}. Periods without a value are "
            "left out.",
            f"Jeu de données {fid} de l'OCDE ({structure['name']}), clé {key}. Les périodes sans "
            "valeur sont omises.",
        ),
        limits=f"{limits} {base_limits}" if limits else base_limits,
        licence=licence,
        commercial_use=commercial,
        lang=lang,
    )


async def get_data(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: str = "en",
) -> DataResult:
    lang = _lang(lang)
    _check_periods(start_period, end_period, last_n, lang)
    fid, info = await _dataflow(dataset, lang)
    structure, _ = await _structure(fid, info, lang)
    dimensions = structure["dimensions"]
    key = _check_key(key, dimensions, fid, lang)
    # The bound multiplies the codes of every wildcard dimension, far above the
    # series that exist, so it only stops an unbounded history of many series,
    # or a key so open that even one period per series would be huge.
    bound = _max_series(key, dimensions)
    if bound > constants.MAX_KEY_BOUND or (bound > 50 and last_n is None and start_period is None):
        _too_broad(fid, key, bound, lang)

    params = _data_params(start_period, end_period, last_n)
    fetched, cached, csv_url = await _fetch(fid, info, key, params, dimensions, lang)
    if not fetched:
        raise_localized(
            NotFound,
            f"OECD dataset {fid} has no values for key {key!r} in the periods asked for.",
            f"le jeu {fid} de l'OCDE n'a aucune valeur pour la clé {key!r} pour les périodes "
            "demandées.",
            lang,
        )

    notes: list[str] = []
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
    total_rows = sum(len(rows) for _, rows in fetched)
    if total_rows > constants.MAX_ROWS:
        keep = max(1, constants.MAX_ROWS // len(fetched))
        for series_info, rows in fetched:
            del rows[:-keep]
            series_info.observation_count = len(rows)
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
    notes.extend(limits)
    return DataResult(
        dataset=fid,
        agency=info["agency"],
        dataset_name=structure["name"],
        key=key,
        series=[s for s, _ in fetched],
        rows=[row for _, rows in fetched for row in rows],
        csv_url=csv_url,
        citation=_citation(fid, info, structure, lang),
        notes=notes,
        provenance=_data_provenance(
            fid,
            info,
            key,
            params,
            structure,
            cached,
            "oecd.DataResult",
            lang,
            " ".join(limits) or None,
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
                    f"{raw!r} is not an OECD area code or group. Use G7, or codes such as USA, "
                    "GBR, AUS, NZL, SWE, OECD (two-letter codes like US also work).",
                    f"{raw!r} n'est ni un code de zone de l'OCDE ni un groupe. Utilisez G7, ou "
                    "des codes comme USA, GBR, AUS, NZL, SWE, OECD (les codes à deux lettres "
                    "comme US fonctionnent aussi).",
                    lang,
                )
            if code not in areas:
                areas.append(code)
    return areas


def _rank(countries: list[CountrySeries]) -> tuple[int | None, str | None, int | None]:
    """Canada's rank (1 = highest), in the period most compared countries report.

    Countries publish on different lags, so the latest period of Canada alone
    would rank it against few of them.
    """
    ranked = [c for c in countries if c.area_code not in constants.AGGREGATES]
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
    name = indicator.strip().lower()
    spec = constants.INDICATORS.get(name)
    if spec is None:
        choices = ", ".join(constants.INDICATORS)
        raise_localized(
            InvalidInput,
            f"Unknown indicator {indicator!r}. Indicators: {choices}. For any other OECD "
            "series use oecd_search_datasets and oecd_get_data.",
            f"indicateur inconnu {indicator!r}. Indicateurs : {choices}. Pour toute autre "
            "série de l'OCDE, utilisez oecd_search_datasets et oecd_get_data.",
            lang,
        )
    _check_periods(start_period, end_period, last_n, lang)
    if last_n is None and start_period is None:
        last_n = spec.default_last_n
    areas = _areas(compare_with, lang)
    fid, info = await _dataflow(spec.dataflow, lang)
    structure, _ = await _structure(fid, info, lang)
    dimensions = structure["dimensions"]
    area_index = spec.key.split(".").index("{area}")
    covered = {c[0] for c in dimensions[area_index]["codes"]}
    if constants.CANADA not in covered:
        raise_localized(
            NotFound,
            f"OECD dataset {fid} has no data for Canada.",
            f"le jeu {fid} de l'OCDE n'a pas de données pour le Canada.",
            lang,
        )
    asked = [a for a in areas if a in covered]
    not_covered = [a for a in areas if a not in covered]
    key = _check_key(spec.key.format(area="+".join(asked)), dimensions, fid, lang)
    params = _data_params(start_period, end_period, last_n)
    fetched, cached, csv_url = await _fetch(fid, info, key, params, dimensions, lang)

    by_area: dict[str, CountrySeries] = {}
    # One series per country, the first kept: a preset that asks for a national
    # measure and a harmonised fallback (CPI_YTYPCT+CPIH_YTYPCT) must keep the
    # national one where a country has both; CPIH sorts first by key otherwise.
    fetched = sorted(fetched, key=lambda item: "CPIH" in item[0].key)
    for series_info, rows in fetched:
        area = series_info.dimensions[area_index]
        if area.code in by_area:
            continue
        by_area[area.code] = CountrySeries(
            area_code=area.code,
            area_name=area.label,
            key=series_info.key,
            unit=pick(lang, spec.unit_en, spec.unit_fr or spec.unit_en)
            if spec.unit_en
            else series_info.unit,
            observations=[Observation(period=r.period, value=r.value) for r in rows],
            latest_period=series_info.latest_period,
            latest_value=series_info.latest_value,
        )
    if constants.CANADA not in by_area:
        raise_localized(
            NotFound,
            f"The OECD has no {name} values for Canada in the periods asked for.",
            f"l'OCDE n'a aucune valeur {name} pour le Canada pour les périodes demandées.",
            lang,
        )
    # lastNObservations counts per series, so a series that stopped long ago
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
    if spec.note_en:
        notes.append(pick(lang, spec.note_en, spec.note_fr or spec.note_en))
    if spec.dataflow == "DSD_EO@DF_EO":
        notes.append(
            pick(
                lang,
                f"{structure['name']}: values for the latest years are OECD estimates and "
                "projections, not outturns; the Economic Outlook is revised each June and "
                "December.",
                f"{structure['name']} : les valeurs des dernières années sont des estimations "
                "et des projections de l'OCDE, non des résultats observés ; les Perspectives "
                "économiques sont révisées chaque juin et chaque décembre.",
            )
        )
    rank, rank_period, ranked = _rank(countries)
    return ComparisonResult(
        indicator=name,
        indicator_label=pick(lang, spec.label_en, spec.label_fr),
        dataset=fid,
        dataset_name=structure["name"],
        countries=countries,
        canada_rank=rank,
        rank_period=rank_period,
        ranked_countries=ranked,
        csv_url=csv_url,
        citation=_citation(fid, info, structure, lang),
        notes=notes,
        provenance=_data_provenance(
            fid, info, key, params, structure, cached, "oecd.ComparisonResult", lang
        ),
    )
