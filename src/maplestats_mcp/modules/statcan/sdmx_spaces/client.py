"""Client for StatCan's extra .Stat Suite SDMX spaces (CCEI and stcshared).

Verified live 2026-10-02, and what this client is built around:

- Structures come as SDMX-JSON 1.0 (`Accept: application/vnd.sdmx.structure+json;
  version=1.0`); the v2 structure media types answer 406. `references=all` returns
  the dataflow, its DSD, codelists, concept scheme and availability constraint in
  one document (180 KB for the GHG flow).
- Data comes as SDMX-CSV 2.0. Observations arrive newest-first with
  lastNObservations and oldest-first otherwise. The version in the data URL must be
  explicit ("latest" answers 400), so it is resolved from the structure.
- A data key with MORE segments than the flow has dimensions is accepted and the
  extra segments silently ignored (HTTP 200), so the segment count is checked here.
- Errors are plain text: 404 "NoRecordsFound" (key matches nothing), 404 "Could not
  find Dataflow and/or DSD", 422 "Semantic Error - Invalid Date Format", 400
  "Invalid version string". A whole large flow ("all") times out.
- Accept-Language: fr turns SDMX-CSV into semicolon-delimited text; data requests
  therefore never send it (the CSV holds codes, not labels), and the parser sniffs
  the delimiter anyway.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import html
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from maplestats_mcp.modules.statcan.sdmx_spaces import constants
from maplestats_mcp.modules.statcan.sdmx_spaces.schemas import (
    FacetValue,
    SearchFacet,
    SearchHit,
    SpaceCode,
    SpaceData,
    SpaceDimension,
    SpaceFlow,
    SpaceFlowList,
    SpaceObservation,
    SpaceSearch,
    SpaceSeries,
    SpaceStructure,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import STATCAN_LICENCE, make_provenance
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import api_post, get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

SOURCE = "statcan-sdmx-spaces"

_ID = re.compile(constants.ID_PATTERN)
_KEY = re.compile(constants.KEY_PATTERN)
_PERIOD = re.compile(constants.PERIOD_PATTERN)
_TAG = re.compile(r"<[^>]+>")
_URN = re.compile(r"=([^:=]+):([^(]+)\(([^)]+)\)$")
_CONCEPT_URN = re.compile(r"=([^:=]+):([^(]+)\(([^)]+)\)\.(.+)$")


def _say(lang: str, en: str, fr: str) -> str:
    return fr if lang == "fr" else en


# Licence text. The StatCan Open Licence covers StatCan content; the services'
# metadata states no licence for flows republished from other departments
# (checked 2026-10-02: no licence in any dataflow annotation, description or
# explorer page beyond a link to StatCan's terms and conditions), whose
# originating datasets are listed on open.canada.ca under the Open Government
# Licence - Canada.
_PARTNER_AGENCIES = ("CCEI", "ECCC", "ISC", "NRCAN")
_PARTNER_CAVEAT = (
    " Flows republished from other departments (ECCC, NRCan, ISC) state no licence in "
    "this service's metadata; their originating datasets are published on open.canada.ca "
    "under the Open Government Licence - Canada. Cite the originating department and "
    "check its terms before redistributing."
)


def licence_for(agency: str | None) -> str:
    if agency is None:
        return STATCAN_LICENCE + _PARTNER_CAVEAT
    tokens = {part.upper() for part in agency.split(".")}
    if tokens & set(_PARTNER_AGENCIES):
        return STATCAN_LICENCE + _PARTNER_CAVEAT
    return STATCAN_LICENCE


_NON_PRODUCTION_NOTE = (
    "Every dataflow in this space carries the NonProductionDataflow annotation: "
    "StatCan has not declared these services production-grade, so flows, codes and "
    "values can change or disappear without notice."
)


def _limiter(source: str = constants.RATE_LIMIT_SOURCE):
    return get_limiter(
        source,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _space(key: str):
    space = constants.SPACES.get(key)
    if space is None:
        raise InvalidInput(f"space must be one of {sorted(constants.SPACES)}, got {key!r}.")
    return space


def _plain(text: str | None, limit: int = constants.DESCRIPTION_CHARS) -> str:
    if not text:
        return ""
    cleaned = " ".join(html.unescape(_TAG.sub(" ", text)).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


async def _get(
    url: str,
    *,
    accept: str,
    params: dict[str, Any] | None = None,
    lang: str = "en",
    send_language: bool = False,
    narrow_hint: str = "",
    key_hint: Any = None,
) -> httpx.Response:
    """GET one SDMX URL, mapping every live failure to a typed error."""
    headers = {"Accept": accept}
    if send_language and lang == "fr":
        headers["Accept-Language"] = "fr"
    await _limiter().acquire()
    try:
        response = await get_raw(
            url, params=params, headers=headers, timeout=constants.READ_TIMEOUT_SECONDS
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = exc.response.text.strip()[:300]
        if status == 404:
            if body.startswith("NoRecordsFound") and key_hint is not None:
                raise key_hint() from exc
            if "mapping set" in body:
                # Live: DF_RURAL_12100138, 12100139 and 14100453 have a structure
                # but no data mapping, so the service cannot serve their data.
                raise NotFound(
                    _say(
                        lang,
                        "This dataflow has a structure but no data behind it (the service "
                        f"reports a missing mapping set: {body[:160]}). Its data cannot be "
                        "fetched from this space.",
                        "Ce flux a une structure mais aucune donnée (le service signale un "
                        f"ensemble de correspondances manquant : {body[:160]}). Ses données "
                        "ne peuvent pas être obtenues dans cet espace.",
                    )
                ) from exc
            raise NotFound(
                _say(
                    lang,
                    f"Not found: {body or url}. List the space's flows with "
                    "sdmx_space_list_flows or sdmx_space_search.",
                    f"Introuvable : {body or url}. Listez les flux de l'espace avec "
                    "sdmx_space_list_flows ou sdmx_space_search.",
                )
            ) from exc
        if status in (400, 422):
            raise InvalidInput(
                _say(
                    lang,
                    f"The SDMX service rejected the request (HTTP {status}: {body}).",
                    f"Le service SDMX a rejeté la requête (HTTP {status} : {body}).",
                )
            ) from exc
        if status in (429, 500, 502, 503, 504):
            raise UpstreamUnavailable(
                _say(
                    lang,
                    f"The SDMX service answered HTTP {status} (already retried). {narrow_hint}"
                    "Try again shortly.",
                    f"Le service SDMX a répondu HTTP {status} (déjà réessayé). {narrow_hint}"
                    "Réessayez sous peu.",
                ).strip()
            ) from exc
        raise UpstreamError(f"The SDMX service answered HTTP {status}: {body}") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            _say(
                lang,
                f"The SDMX service did not answer within {constants.READ_TIMEOUT_SECONDS:.0f} s "
                f"(already retried). {narrow_hint}Try again shortly.",
                f"Le service SDMX n'a pas répondu en {constants.READ_TIMEOUT_SECONDS:.0f} s "
                f"(déjà réessayé). {narrow_hint}Réessayez sous peu.",
            ).strip()
        ) from exc
    if response.status_code == 406:
        raise InvalidInput(
            _say(
                lang,
                f"The SDMX service rejected the request (HTTP 406: "
                f"{response.text.strip()[:200] or 'no message'}).",
                f"Le service SDMX a rejeté la requête (HTTP 406 : "
                f"{response.text.strip()[:200] or 'sans message'}).",
            )
        )
    return response


def _json(response: httpx.Response, what: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(
            f"The SDMX service sent a {what} that is not valid JSON "
            f"({len(response.content)} bytes; truncated?)."
        ) from exc
    if not isinstance(payload, dict):
        raise UpstreamError(f"The SDMX service sent a {what} that is not a JSON object.")
    return payload


def _name(item: dict[str, Any]) -> str:
    name = item.get("name")
    if isinstance(name, str) and name:
        return name
    names = item.get("names")
    if isinstance(names, dict):
        for value in names.values():
            if isinstance(value, str) and value:
                return value
    return str(item.get("id", ""))


# --------------------------------------------------------------------------
# Dataflow list
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _FlowRow:
    agency: str
    id: str
    version: str
    name: str
    description: str
    non_production: bool

    @property
    def ref(self) -> str:
        return f"{self.agency},{self.id},{self.version}"


def _is_non_production(item: dict[str, Any]) -> bool:
    for annotation in item.get("annotations") or []:
        if (
            isinstance(annotation, dict)
            and annotation.get("type") == "NonProductionDataflow"
            and str(annotation.get("text", "")).lower() == "true"
        ):
            return True
    return False


def _parse_flows(payload: dict[str, Any]) -> list[_FlowRow]:
    try:
        raw = payload["data"]["dataflows"]
        rows = [
            _FlowRow(
                agency=str(item["agencyID"]),
                id=str(item["id"]),
                version=str(item["version"]),
                name=_name(item),
                description=_plain(item.get("description")),
                non_production=_is_non_production(item),
            )
            for item in raw
        ]
    except (KeyError, TypeError, AttributeError) as exc:
        raise UpstreamError(
            f"The dataflow list is not shaped like SDMX-JSON 1.0 ({exc!r})."
        ) from exc
    if not rows:
        raise UpstreamError("The dataflow list is empty.")
    return rows


async def _flow_rows(space_key: str, lang: str) -> list[_FlowRow]:
    space = _space(space_key)
    url = f"{space.base_url}/dataflow/all/all/latest"

    async def fetch() -> list[_FlowRow]:
        response = await _get(
            url,
            accept=constants.ACCEPT_STRUCTURE,
            lang=lang,
            send_language=True,
            key_hint=None,
        )
        return _parse_flows(_json(response, "dataflow list"))

    rows, _ = await cached_fetch(
        f"sdmxsp:flows:{space_key}:{lang}", constants.CACHE_TTL_SECONDS, fetch
    )
    return rows


def _agency_matches(agency: str, wanted: str) -> bool:
    a, w = agency.lower(), wanted.strip().lower()
    return a == w or f".{w}." in f".{a}."


async def list_flows(
    space_key: str,
    *,
    query: str = "",
    agency: str = "",
    limit: int = constants.DEFAULT_LIST_LIMIT,
    offset: int = 0,
    lang: str = "en",
) -> SpaceFlowList:
    if limit < 1 or limit > constants.MAX_LIST_LIMIT:
        raise InvalidInput(
            _say(
                lang,
                f"limit must be between 1 and {constants.MAX_LIST_LIMIT}, got {limit}.",
                f"limit doit être entre 1 et {constants.MAX_LIST_LIMIT}, reçu {limit}.",
            )
        )
    if offset < 0:
        raise InvalidInput(_say(lang, "offset must be >= 0.", "offset doit être >= 0."))
    space = _space(space_key)
    rows = await _flow_rows(space_key, lang)

    words = query.lower().split()
    selected: list[tuple[int, _FlowRow]] = []
    for row in rows:
        if agency and not _agency_matches(row.agency, agency):
            continue
        name_l = row.name.lower()
        haystack = f"{row.id} {name_l} {row.description.lower()}".lower()
        if not all(word in haystack for word in words):
            continue
        selected.append((-sum(word in name_l or word in row.id.lower() for word in words), row))
    selected.sort(key=lambda pair: pair[0])
    matched = [row for _, row in selected]
    page = matched[offset : offset + limit]

    agencies: dict[str, int] = {}
    for row in rows:
        agencies[row.agency] = agencies.get(row.agency, 0) + 1
    notes = []
    if len(page) < len(matched):
        notes.append(f"{len(page)} of {len(matched)} matching flows; use limit/offset")
    return SpaceFlowList(
        space=space_key,
        total_flows=len(rows),
        matched=len(matched),
        agencies=dict(sorted(agencies.items())),
        non_production_flows=sum(row.non_production for row in rows),
        flows=[
            SpaceFlow(
                flow=r.ref,
                agency=r.agency,
                id=r.id,
                version=r.version,
                name=r.name,
                description=r.description,
            )
            for r in page
        ],
        provenance=make_provenance(
            source=SOURCE,
            url=f"{space.base_url}/dataflow/all/all/latest",
            cached=False,
            schema_name="statcan.sdmx_spaces.SpaceFlowList",
            coverage=_NON_PRODUCTION_NOTE,
            limits="; ".join(notes) if notes else None,
            licence=licence_for(agency or None),
        ),
    )


# --------------------------------------------------------------------------
# Flow references
# --------------------------------------------------------------------------


async def _resolve_flow(space_key: str, flow: str, lang: str) -> tuple[str, str, str | None]:
    """(agency, id, version or None) from `ID`, `AGENCY,ID` or `AGENCY,ID,VERSION`."""
    parts = [part.strip() for part in flow.split(",")]
    if not 1 <= len(parts) <= 3 or not all(parts) or not all(_ID.match(p) for p in parts):
        raise InvalidInput(
            _say(
                lang,
                f"flow {flow!r} must be a dataflow id, or agency,id or agency,id,version "
                "(letters, digits, '_', '.', '-').",
                f"flow {flow!r} doit être un identifiant de flux, ou agence,id ou "
                "agence,id,version (lettres, chiffres, '_', '.', '-').",
            )
        )
    if len(parts) == 1:
        rows = await _flow_rows(space_key, "en")
        matches = [row for row in rows if row.id == parts[0]]
        if not matches:
            close = difflib.get_close_matches(parts[0], [row.id for row in rows], n=5, cutoff=0.6)
            raise NotFound(
                _say(
                    lang,
                    f"No dataflow with id {parts[0]!r} in space {space_key!r}."
                    + (f" Similar ids: {', '.join(close)}." if close else "")
                    + " Use sdmx_space_list_flows or sdmx_space_search to find one.",
                    f"Aucun flux avec l'id {parts[0]!r} dans l'espace {space_key!r}."
                    + (f" Ids semblables : {', '.join(close)}." if close else "")
                    + " Utilisez sdmx_space_list_flows ou sdmx_space_search.",
                )
            )
        if len(matches) > 1:
            raise InvalidInput(
                _say(
                    lang,
                    f"Dataflow id {parts[0]!r} exists under several agencies; pass one of: "
                    + "; ".join(row.ref for row in matches),
                    f"L'id de flux {parts[0]!r} existe sous plusieurs agences; passez l'un de : "
                    + "; ".join(row.ref for row in matches),
                )
            )
        return matches[0].agency, matches[0].id, matches[0].version
    agency, flow_id = parts[0], parts[1]
    version = parts[2] if len(parts) == 3 and parts[2].lower() not in ("latest", "+") else None
    return agency, flow_id, version


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


@dataclass
class _Structure:
    agency: str
    id: str
    version: str
    name: str
    description: str
    non_production: bool
    dimensions: list[SpaceDimension]
    time_dimension: str | None
    attributes: list[str]
    start_period: str | None
    end_period: str | None
    observation_count: int | None
    valid_from: datetime | None
    availability_known: bool

    @property
    def ref(self) -> str:
        return f"{self.agency},{self.id},{self.version}"


def _urn_key(urn: str) -> str | None:
    match = _URN.search(urn)
    return f"{match.group(1)}:{match.group(2)}({match.group(3)})" if match else None


def _constraint_values(
    constraint: dict[str, Any] | None,
) -> tuple[dict[str, set[str]], str | None, str | None, int | None, datetime | None]:
    if not constraint:
        return {}, None, None, None, None
    values: dict[str, set[str]] = {}
    start = end = None
    for region in constraint.get("cubeRegions") or []:
        if region.get("isIncluded") is False:
            continue
        for key_value in region.get("keyValues") or []:
            if "values" in key_value:
                values.setdefault(key_value["id"], set()).update(map(str, key_value["values"]))
            elif "timeRange" in key_value:
                rng = key_value["timeRange"]
                start = str(rng.get("startPeriod", {}).get("period", ""))[:10] or None
                end = str(rng.get("endPeriod", {}).get("period", ""))[:10] or None
    count = None
    for annotation in constraint.get("annotations") or []:
        if annotation.get("id") == "obs_count":
            try:
                count = int(annotation.get("title", ""))
            except ValueError:
                count = None
    valid_from = None
    raw_from = constraint.get("validFrom")
    if isinstance(raw_from, str):
        try:
            valid_from = datetime.fromisoformat(raw_from)
        except ValueError:
            valid_from = None
    return values, start, end, count, valid_from


def _parse_structure(payload: dict[str, Any], agency: str, flow_id: str) -> _Structure:
    try:
        data = payload["data"]
        flows = data["dataflows"]
        flow = next(
            (f for f in flows if f.get("id") == flow_id and f.get("agencyID") == agency),
            flows[0],
        )
        dsd_key = _urn_key(flow["structure"])
        dsd = next(
            d
            for d in data["dataStructures"]
            if f"{d['agencyID']}:{d['id']}({d['version']})" == dsd_key
        )
        codelists = {
            f"{c['agencyID']}:{c['id']}({c['version']})": c for c in data.get("codelists") or []
        }
        concepts: dict[str, dict[str, str]] = {}
        for scheme in data.get("conceptSchemes") or []:
            concepts[f"{scheme['agencyID']}:{scheme['id']}({scheme['version']})"] = {
                c["id"]: _name(c) for c in scheme.get("concepts") or []
            }
        # A flow can carry two constraints: an "Allowed" one limiting a single
        # dimension (live: DF_25100014 constrains only PRODUCT) and the "Actual"
        # availability constraint (CR_A_<flow>) listing every dimension's values
        # and the observation count. Only the Actual one says what has data.
        attached = [
            c
            for c in data.get("contentConstraints") or []
            if any(
                f"={flow['agencyID']}:{flow['id']}(" in urn
                for urn in (c.get("constraintAttachment") or {}).get("dataflows") or []
            )
        ]
        constraint = next((c for c in attached if c.get("type") == "Actual"), None)
        available, start, end, obs_count, valid_from = _constraint_values(constraint)
        components = dsd["dataStructureComponents"]
        dimensions: list[SpaceDimension] = []
        for dim in components["dimensionList"]["dimensions"]:
            concept_match = _CONCEPT_URN.search(dim.get("conceptIdentity", ""))
            dim_name: str = str(dim["id"])
            if concept_match:
                scheme_key = (
                    f"{concept_match.group(1)}:{concept_match.group(2)}({concept_match.group(3)})"
                )
                dim_name = concepts.get(scheme_key, {}).get(concept_match.group(4)) or dim_name
            enumeration = (dim.get("localRepresentation") or {}).get("enumeration")
            codelist_key = _urn_key(enumeration) if enumeration else None
            codelist = codelists.get(codelist_key or "")
            all_codes = [
                SpaceCode(id=str(c["id"]), name=_name(c), parent_id=c.get("parent"))
                for c in (codelist or {}).get("codes") or []
            ]
            wanted = available.get(dim["id"])
            if wanted is None:
                codes = all_codes
            else:
                known = {c.id for c in all_codes}
                codes = [c for c in all_codes if c.id in wanted]
                codes += [SpaceCode(id=v, name=v) for v in sorted(wanted - known)]
            dimensions.append(
                SpaceDimension(
                    position=int(dim["position"]),
                    id=dim["id"],
                    name=dim_name,
                    codelist=codelist_key,
                    code_count=len(codes),
                    codelist_size=len(all_codes),
                    codes=codes,
                )
            )
        dimensions.sort(key=lambda d: d.position)
        time_dims = components["dimensionList"].get("timeDimensions") or []
        attributes = [
            a["id"] for a in (components.get("attributeList") or {}).get("attributes") or []
        ]
        return _Structure(
            agency=str(flow["agencyID"]),
            id=str(flow["id"]),
            version=str(flow["version"]),
            name=_name(flow),
            description=_plain(flow.get("description"), 1500),
            non_production=_is_non_production(flow),
            dimensions=dimensions,
            time_dimension=time_dims[0]["id"] if time_dims else None,
            attributes=attributes,
            start_period=start,
            end_period=end,
            observation_count=obs_count,
            valid_from=valid_from,
            availability_known=constraint is not None,
        )
    except (KeyError, TypeError, AttributeError, IndexError, StopIteration, ValueError) as exc:
        raise UpstreamError(
            f"The structure of {agency},{flow_id} is not shaped like SDMX-JSON 1.0 ({exc!r})."
        ) from exc


async def _load_structure(
    space_key: str, agency: str, flow_id: str, version: str | None, lang: str
) -> _Structure:
    space = _space(space_key)
    url = f"{space.base_url}/dataflow/{agency}/{flow_id}/{version or 'latest'}"

    async def fetch() -> _Structure:
        response = await _get(
            url,
            accept=constants.ACCEPT_STRUCTURE,
            params={"references": "all"},
            lang=lang,
            send_language=True,
        )
        return _parse_structure(_json(response, "structure"), agency, flow_id)

    value, _ = await cached_fetch(
        f"sdmxsp:structure:{space_key}:{agency}:{flow_id}:{version or 'latest'}:{lang}",
        constants.CACHE_TTL_SECONDS,
        fetch,
    )
    return value


async def get_structure(
    space_key: str,
    flow: str,
    *,
    dimension: str = "",
    code_query: str = "",
    limit: int = constants.DEFAULT_CODE_LIMIT,
    offset: int = 0,
    lang: str = "en",
) -> SpaceStructure:
    """A flow's dimensions in key order, with the codes that have data, paged."""
    if limit < 1 or limit > constants.MAX_CODE_LIMIT:
        raise InvalidInput(
            _say(
                lang,
                f"limit must be between 1 and {constants.MAX_CODE_LIMIT}, got {limit}.",
                f"limit doit être entre 1 et {constants.MAX_CODE_LIMIT}, reçu {limit}.",
            )
        )
    if offset < 0:
        raise InvalidInput(_say(lang, "offset must be >= 0.", "offset doit être >= 0."))
    space = _space(space_key)
    agency, flow_id, version = await _resolve_flow(space_key, flow, lang)
    structure = await _load_structure(space_key, agency, flow_id, version, lang)

    selected = [
        d for d in structure.dimensions if not dimension or d.id.lower() == dimension.lower()
    ]
    if dimension and not selected:
        raise NotFound(
            _say(
                lang,
                f"No dimension {dimension!r} in {structure.ref}; its dimensions are "
                + ", ".join(d.id for d in structure.dimensions)
                + ".",
                f"Aucune dimension {dimension!r} dans {structure.ref}; ses dimensions sont "
                + ", ".join(d.id for d in structure.dimensions)
                + ".",
            )
        )
    needle = code_query.strip().lower()
    notes: list[str] = []
    paged: list[SpaceDimension] = []
    for dim in selected:
        matching = [
            c for c in dim.codes if not needle or needle in c.name.lower() or needle == c.id.lower()
        ]
        page = matching[offset : offset + limit]
        if len(page) < len(matching):
            notes.append(f"{dim.id}: {len(page)} of {len(matching)} codes")
        paged.append(dim.model_copy(update={"codes": page}))
    return SpaceStructure(
        space=space_key,
        flow=structure.ref,
        name=structure.name,
        description=structure.description,
        non_production=structure.non_production,
        dimensions=paged,
        key_order=[d.id for d in structure.dimensions],
        time_dimension=structure.time_dimension,
        attributes=structure.attributes,
        start_period=structure.start_period,
        end_period=structure.end_period,
        observation_count=structure.observation_count,
        provenance=make_provenance(
            source=SOURCE,
            url=f"{space.base_url}/dataflow/{structure.agency}/{structure.id}/{structure.version}",
            cached=False,
            schema_name="statcan.sdmx_spaces.SpaceStructure",
            as_of=structure.valid_from,
            coverage=(
                (_NON_PRODUCTION_NOTE + " " if structure.non_production else "")
                + (
                    "Codes listed are those with data (from the flow's availability "
                    "constraint); codelist_size is the whole codelist."
                    if structure.availability_known
                    else "The flow has no availability constraint, so the codes are the whole "
                    "codelists and some may have no data."
                )
            ),
            limits=(
                "codes paged (" + "; ".join(notes) + "); use limit/offset, code_query or dimension"
                if notes
                else None
            ),
            licence=licence_for(structure.agency),
        ),
    )


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _check_period(value: str | None, name: str, lang: str) -> None:
    if value and not _PERIOD.match(value):
        raise InvalidInput(
            _say(
                lang,
                f"{name} {value!r} is not an SDMX period; use 2024, 2024-03, 2024-03-15 or 2024-Q1.",
                f"{name} {value!r} n'est pas une période SDMX; utilisez 2024, 2024-03, "
                "2024-03-15 ou 2024-Q1.",
            )
        )


@dataclass
class _ParsedCsv:
    series: list[SpaceSeries]
    truncated_body: bool


def _to_float(raw: str) -> tuple[float | None, str | None]:
    if raw == "":
        return None, None
    try:
        number = float(raw)
    except ValueError:
        return None, raw
    if not math.isfinite(number):
        return None, raw
    return number, None


def _parse_csv(text: str, *, max_rows_per_series: int) -> _ParsedCsv:
    """SDMX-CSV 2.0 into series (dimension columns), oldest observation first."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise NotFound("The SDMX service returned an empty body: no observations.")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header = rows[0]
    if header[:3] != ["STRUCTURE", "STRUCTURE_ID", "ACTION"] or "OBS_VALUE" not in header:
        raise UpstreamError(
            "The SDMX service did not send SDMX-CSV 2.0 (header: " + ",".join(header)[:120] + ")."
        )
    obs_idx = header.index("OBS_VALUE")
    time_idx = header.index("TIME_PERIOD") if "TIME_PERIOD" in header else None
    dim_end = time_idx if time_idx is not None else obs_idx
    dim_cols = header[3:dim_end]
    attr_cols = header[obs_idx + 1 :]

    data_rows = [row for row in rows[1:] if row]
    # A body cut off mid-transfer ends without a newline: its last row is partial.
    truncated_body = bool(data_rows) and not text.endswith("\n")
    if truncated_body:
        data_rows = data_rows[:-1]

    grouped: dict[tuple[str, ...], list[tuple[str, str, list[str]]]] = {}
    for number, row in enumerate(data_rows, start=2):
        if len(row) > len(header):
            raise UpstreamError(
                f"Malformed SDMX-CSV: row {number} has {len(row)} fields, header {len(header)}."
            )
        row = row + [""] * (len(header) - len(row))
        period = row[time_idx] if time_idx is not None else ""
        grouped.setdefault(tuple(row[3:dim_end]), []).append(
            (period, row[obs_idx], row[obs_idx + 1 :])
        )

    series: list[SpaceSeries] = []
    for dim_values, entries in grouped.items():
        entries.sort(key=lambda entry: entry[0])
        constant: dict[str, str] = {}
        varying: list[str] = []
        for column, name in enumerate(attr_cols):
            distinct = {entry[2][column] for entry in entries}
            if len(distinct) == 1:
                value = next(iter(distinct))
                if value:
                    constant[name] = value
            else:
                varying.append(name)
        observations: list[SpaceObservation] = []
        for period, raw_value, attrs in entries:
            value, text_value = _to_float(raw_value)
            observations.append(
                SpaceObservation(
                    period=period,
                    value=value,
                    value_text=text_value,
                    attributes={
                        name: attrs[attr_cols.index(name)]
                        for name in varying
                        if attrs[attr_cols.index(name)]
                    },
                )
            )
        series.append(
            SpaceSeries(
                series_key=dict(zip(dim_cols, dim_values, strict=True)),
                attributes=constant,
                observations=observations[-max_rows_per_series:],
            )
        )
    return _ParsedCsv(series=series, truncated_body=truncated_body)


def _segments(key: str) -> list[str]:
    return key.split(".")


def _unknown_codes(structure: _Structure, key: str) -> list[str]:
    unknown: list[str] = []
    for dim, segment in zip(structure.dimensions, _segments(key), strict=False):
        known = {c.id for c in dim.codes}
        if not known:
            continue
        unknown += [f"{dim.id}={code}" for code in segment.split("+") if code and code not in known]
    return unknown


async def get_data(
    space_key: str,
    flow: str,
    key: str = "all",
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    max_rows: int = 1000,
    lang: str = "en",
) -> SpaceData:
    space = _space(space_key)
    key = key.strip() or "all"
    if not _KEY.match(key):
        raise InvalidInput(
            _say(
                lang,
                f"key {key!r} may only contain member ids, '.', and '+'.",
                f"key {key!r} ne peut contenir que des identifiants de membres, '.' et '+'.",
            )
        )
    if last_n_observations is not None and not 1 <= last_n_observations <= constants.MAX_LAST_N:
        raise InvalidInput(
            _say(
                lang,
                f"last_n_observations must be between 1 and {constants.MAX_LAST_N}.",
                f"last_n_observations doit être entre 1 et {constants.MAX_LAST_N}.",
            )
        )
    if not 1 <= max_rows <= 5000:
        raise InvalidInput(
            _say(
                lang,
                f"max_rows must be between 1 and 5000, got {max_rows}.",
                f"max_rows doit être entre 1 et 5000, reçu {max_rows}.",
            )
        )
    _check_period(start_period, "start_period", lang)
    _check_period(end_period, "end_period", lang)

    agency, flow_id, version = await _resolve_flow(space_key, flow, lang)
    structure = await _load_structure(space_key, agency, flow_id, version, lang)
    n_dims = len(structure.dimensions)
    order = ".".join(d.id for d in structure.dimensions)
    wildcard_only = key == "all" or all(not part for part in _segments(key))
    if key != "all" and len(_segments(key)) != n_dims:
        raise InvalidInput(
            _say(
                lang,
                f"key {key!r} has {len(_segments(key))} segments but {structure.ref} has "
                f"{n_dims} dimensions ({order}); the service would silently ignore extra "
                "segments. Use one segment per dimension, empty for a wildcard.",
                f"key {key!r} a {len(_segments(key))} segments mais {structure.ref} a "
                f"{n_dims} dimensions ({order}); le service ignorerait en silence les segments "
                "en trop. Utilisez un segment par dimension, vide pour un joker.",
            )
        )
    if (
        wildcard_only
        and structure.observation_count is not None
        and structure.observation_count > constants.MAX_UNFILTERED_OBSERVATIONS
    ):
        raise InvalidInput(
            _say(
                lang,
                f"{structure.ref} holds {structure.observation_count:,} observations and the "
                "service times out (HTTP 504) when a whole flow is requested. Filter at least "
                f"one dimension of {order} (see sdmx_space_get_structure).",
                f"{structure.ref} contient {structure.observation_count:,} observations et le "
                "service expire (HTTP 504) quand tout un flux est demandé. Filtrez au moins "
                f"une dimension de {order} (voir sdmx_space_get_structure).",
            )
        )

    params: dict[str, Any] = {}
    default_applied = False
    if start_period:
        params["startPeriod"] = start_period
    if end_period:
        params["endPeriod"] = end_period
    if last_n_observations is not None:
        params["lastNObservations"] = last_n_observations
    elif not start_period and not end_period:
        params["lastNObservations"] = constants.DEFAULT_LAST_N
        default_applied = True

    url = f"{space.base_url}/data/{structure.agency},{structure.id},{structure.version}/{key}"

    def no_match() -> NotFound:
        unknown = _unknown_codes(structure, key) if key != "all" else []
        return NotFound(
            _say(
                lang,
                f"Key {key!r} matched no series in {structure.ref}."
                + (f" Codes without data: {', '.join(unknown)}." if unknown else "")
                + " Check codes with sdmx_space_get_structure.",
                f"La clé {key!r} ne correspond à aucune série de {structure.ref}."
                + (f" Codes sans données : {', '.join(unknown)}." if unknown else "")
                + " Vérifiez les codes avec sdmx_space_get_structure.",
            )
        )

    response = await _get(
        url,
        accept=constants.ACCEPT_DATA,
        params=params or None,
        lang=lang,
        narrow_hint=_say(
            lang,
            "Whole or very wide selections time out: filter more dimensions or use a shorter "
            "period. ",
            "Les sélections entières ou très larges expirent : filtrez plus de dimensions ou "
            "raccourcissez la période. ",
        ),
        key_hint=no_match,
    )
    try:
        parsed = _parse_csv(response.text, max_rows_per_series=constants.MAX_ROWS)
    except NotFound as exc:
        raise no_match() from exc

    series_total = len(parsed.series)
    series = parsed.series[: constants.MAX_SERIES]
    budget = max_rows
    kept: list[SpaceSeries] = []
    total_rows = sum(len(s.observations) for s in series)
    for item in series:
        if budget <= 0:
            break
        if len(item.observations) > budget:
            item = item.model_copy(update={"observations": item.observations[-budget:]})
        budget -= len(item.observations)
        kept.append(item)
    row_count = sum(len(s.observations) for s in kept)

    notes: list[str] = []
    if default_applied:
        notes.append(
            f"no period filter given: latest {constants.DEFAULT_LAST_N} observations per series "
            "(pass last_n_observations or start_period/end_period for more)"
        )
    if any(len(s.observations) >= constants.MAX_ROWS for s in series):
        notes.append(f"newest {constants.MAX_ROWS} rows kept per series")
    if series_total > constants.MAX_SERIES:
        notes.append(f"first {constants.MAX_SERIES} of {series_total} series; narrow the key")
    if row_count < total_rows:
        notes.append(f"{row_count} of {total_rows} rows (max_rows={max_rows}); narrow the key")
    if parsed.truncated_body:
        notes.append("the response ended mid-row (truncated); its last row was dropped")
    return SpaceData(
        space=space_key,
        flow=structure.ref,
        key=key,
        series=kept,
        row_count=row_count,
        series_total=series_total,
        non_production=structure.non_production,
        provenance=make_provenance(
            source=SOURCE,
            url=str(httpx.URL(url, params=params)),
            cached=False,
            schema_name="statcan.sdmx_spaces.SpaceData",
            coverage=_NON_PRODUCTION_NOTE if structure.non_production else None,
            limits="; ".join(notes) if notes else None,
            licence=licence_for(structure.agency),
        ),
    )


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

_FACET_TAIL = re.compile(r"#[^#]*#$")


def _facet_label(raw: str) -> str:
    parts = raw.split("|")
    return _FACET_TAIL.sub("", parts[-1] if len(parts) > 1 else parts[0]).strip()


async def _search_tenant(
    tenant: str, body: dict[str, Any], lang: str
) -> tuple[int, list[SearchHit], dict[str, dict[str, tuple[int, str]]]]:
    url = f"{constants.SEARCH_URL}?tenant={constants.SEARCH_TENANTS[tenant]}"
    await _limiter(constants.RATE_LIMIT_SEARCH_SOURCE).acquire()
    try:
        payload = await api_post(url, json_body=body, timeout=constants.READ_TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (400, 422):
            raise InvalidInput(
                _say(
                    lang,
                    f"The search service rejected the request (HTTP {status}): "
                    f"{exc.response.text.strip()[:200]}",
                    f"Le service de recherche a rejeté la requête (HTTP {status}) : "
                    f"{exc.response.text.strip()[:200]}",
                )
            ) from exc
        raise UpstreamUnavailable(
            _say(
                lang,
                f"The search service answered HTTP {status} for tenant {tenant!r} "
                "(already retried).",
                f"Le service de recherche a répondu HTTP {status} pour le locataire {tenant!r} "
                "(déjà réessayé).",
            )
        ) from exc
    except httpx.DecodingError as exc:
        raise UpstreamError(f"The search service sent invalid JSON for tenant {tenant!r}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            _say(
                lang,
                f"The search service did not answer for tenant {tenant!r} (already retried).",
                f"Le service de recherche n'a pas répondu pour le locataire {tenant!r} "
                "(déjà réessayé).",
            )
        ) from exc
    try:
        found = int(payload["numFound"])
        hits = [
            SearchHit(
                flow=f"{item['agencyId']},{item['dataflowId']},{item['version']}",
                agency=str(item["agencyId"]),
                id=str(item["dataflowId"]),
                version=str(item["version"]),
                tenant=tenant,
                name=str(item.get("name", "")),
                description=_plain(item.get("description")),
                dimensions=[str(d) for d in item.get("dimensions") or []],
                last_updated=item.get("lastUpdated"),
                score=item.get("score"),
            )
            for item in payload["dataflows"]
        ]
        facets: dict[str, dict[str, tuple[int, str]]] = {}
        for name, facet in (payload.get("facets") or {}).items():
            if name == "datasourceId":
                continue
            for bucket in facet.get("buckets") or []:
                raw = str(bucket["val"])
                count = int(bucket["count"])
                previous = facets.setdefault(name, {}).get(raw, (0, raw))[0]
                facets[name][raw] = (previous + count, raw)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise UpstreamError(
            f"The search response for tenant {tenant!r} is not shaped as expected ({exc!r})."
        ) from exc
    return found, hits, facets


async def search_flows(
    space_key: str,
    query: str,
    *,
    tenant: str | None = None,
    filters: dict[str, list[str]] | None = None,
    limit: int = constants.DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    lang: str = "en",
) -> SpaceSearch:
    space = _space(space_key)
    if limit < 1 or offset < 0 or limit + offset > constants.MAX_SEARCH_ROWS:
        raise InvalidInput(
            _say(
                lang,
                f"limit must be >= 1, offset >= 0 and limit + offset <= {constants.MAX_SEARCH_ROWS}.",
                f"limit doit être >= 1, offset >= 0 et limit + offset <= {constants.MAX_SEARCH_ROWS}.",
            )
        )
    if tenant is not None and tenant not in space.tenants:
        raise InvalidInput(
            _say(
                lang,
                f"tenant {tenant!r} is not part of space {space_key!r}; its tenants are "
                + ", ".join(space.tenants)
                + ".",
                f"le locataire {tenant!r} ne fait pas partie de l'espace {space_key!r}; ses "
                "locataires sont " + ", ".join(space.tenants) + ".",
            )
        )
    tenants = [tenant] if tenant else list(space.tenants)
    body: dict[str, Any] = {
        "lang": lang,
        "search": query,
        "rows": limit + offset,
        "start": 0,
    }
    if filters:
        # Verified live: the service filters on a `facets` object of facet name to raw
        # values; `filters`, `constraints` and `fq` are silently ignored (full count).
        body["facets"] = filters
    results = await asyncio.gather(*(_search_tenant(t, body, lang) for t in tenants))

    found = sum(r[0] for r in results)
    hits = sorted((h for r in results for h in r[1]), key=lambda h: -(h.score or 0.0))
    merged: dict[str, dict[str, tuple[int, str]]] = {}
    for _, _, facets in results:
        for name, buckets in facets.items():
            for raw, (count, _) in buckets.items():
                previous = merged.setdefault(name, {}).get(raw, (0, raw))[0]
                merged[name][raw] = (previous + count, raw)
    facet_list = [
        SearchFacet(
            name=name,
            values=[
                FacetValue(label=_facet_label(raw), count=count, filter_value=raw)
                for raw, (count, _) in sorted(buckets.items(), key=lambda kv: -kv[1][0])[
                    : constants.MAX_FACET_VALUES
                ]
            ],
        )
        for name, buckets in list(merged.items())[: constants.MAX_FACETS]
    ]
    page = hits[offset : offset + limit]
    notes = []
    if found > len(page) + offset:
        notes.append(f"{len(page)} of {found} matching flows; use limit/offset")
    return SpaceSearch(
        space=space_key,
        query=query,
        tenants=tenants,
        found=found,
        flows=page,
        facets=facet_list,
        provenance=make_provenance(
            source=SOURCE,
            url=constants.SEARCH_URL
            + "?tenant="
            + ",".join(constants.SEARCH_TENANTS[t] for t in tenants),
            cached=False,
            schema_name="statcan.sdmx_spaces.SpaceSearch",
            coverage=(
                "Only flows indexed by the search tenants are searched (ccei 122 of 245 "
                "flows; stcshared: rural, cith and pceip only, so QOL and MEA flows are "
                "found with sdmx_space_list_flows). " + _NON_PRODUCTION_NOTE
            ),
            limits="; ".join(notes) if notes else None,
            licence=licence_for(None),
        ),
    )
