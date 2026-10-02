"""HTTP client for StatCan's SDMX REST API.

Parses SDMX-ML (XML) directly -- confirmed live that StatCan's SDMX REST
endpoint ignores format=jsondata/sdmx-json and any Accept header, always
returning SDMX 2.1 Generic Data XML for data queries and structure-message
XML for structure queries. See constants.py for the confirmation note.

Live behaviour this client is built around (verified 2026-10-02): the
structure document is empty (HTTP 200, zero bytes) or cut off for some
large tables, so data queries never need it (the dataflow id is always
DF_<productId>) and structure requests fall back to WDS getCubeMetadata,
whose members equal the SDMX codelists.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import httpx

# defusedxml, not stdlib xml.etree, to guard against entity-expansion
# ("billion laughs") DoS in the XML this module parses -- StatCan is a
# trusted host today, but there's no reason to carry that risk when a
# drop-in replacement removes it for free. `Element` itself is just a
# plain data structure (not a parser) and is safe to import from
# stdlib for the type hints below.
from defusedxml import ElementTree as defused_ET

from maplestats_mcp.modules.statcan.sdmx import constants
from maplestats_mcp.modules.statcan.sdmx.schemas import (
    SdmxCode,
    SdmxData,
    SdmxDimension,
    SdmxObservation,
    SdmxOrKey,
    SdmxSeries,
    SdmxStructure,
)
from maplestats_mcp.modules.statcan.wds import client as wds_client
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

NS = constants.SDMX_NS

_PERIOD = re.compile(constants.PERIOD_PATTERN)
_KEY = re.compile(r"^[A-Za-z0-9_+.\-]*$")


def _qn(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _say(lang: str, en: str, fr: str) -> str:
    return fr if lang == "fr" else en


class _BadBodyError(Exception):
    """HTTP 200 whose body is not well-formed XML (empty, truncated, malformed)."""

    def __init__(self, size: int, detail: str) -> None:
        super().__init__(f"{size} bytes: {detail}")
        self.size = size


def _upstream_message(response: httpx.Response) -> str:
    """The `message` StatCan puts in its JSON error bodies, or ''."""
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("message", "")) if isinstance(body, dict) else ""


async def _fetch_xml(
    url: str, *, params: dict[str, Any] | None = None, lang: str = "en", hint: str = ""
) -> Element:
    """GET and parse SDMX-ML, mapping every live failure to a typed error.

    Confirmed live 2026-10-02: unknown table -> 406 {"message":"The parameter
    is not valid"}; bad period or key -> 406 {"message":"Wrong date format or
    value, check manual"}; a key matching no series -> HTTP 200 with a
    malformed GenericData document; some structure URLs -> HTTP 200 with an
    empty or truncated body.
    """
    await _limiter().acquire()
    try:
        response = await get_raw(url, params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise NotFound(_say(lang, f"{url} was not found.", f"{url} est introuvable.")) from exc
        raise UpstreamUnavailable(
            _say(
                lang,
                f"StatCan's SDMX service answered HTTP {status} (already retried). "
                "Try again shortly.",
                f"Le service SDMX de StatCan a répondu HTTP {status} (déjà réessayé). "
                "Réessayez sous peu.",
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            _say(
                lang,
                "StatCan's SDMX service did not respond in time (already retried). "
                "Try again shortly.",
                "Le service SDMX de StatCan n'a pas répondu à temps (déjà réessayé). "
                "Réessayez sous peu.",
            )
        ) from exc
    if response.status_code == 409:
        raise DataLocked(
            _say(
                lang,
                f"{url} is locked during StatCan's daily update window (12am-8:30am ET).",
                f"{url} est verrouillé pendant la mise à jour quotidienne de StatCan "
                "(0 h à 8 h 30, HE).",
            )
        )
    if response.status_code == 406:
        upstream = _upstream_message(response)
        raise InvalidInput(
            _say(
                lang,
                f"StatCan's SDMX API rejected the request (HTTP 406: {upstream or 'no message'}). "
                f"{hint}",
                f"L'API SDMX de StatCan a rejeté la requête (HTTP 406 : "
                f"{upstream or 'sans message'}). {hint}",
            ).strip()
        )
    try:
        return defused_ET.fromstring(response.content)
    except ParseError as exc:
        raise _BadBodyError(len(response.content), str(exc)) from exc


def _check_period(value: str | None, name: str, lang: str) -> None:
    if value and not _PERIOD.match(value):
        raise InvalidInput(
            _say(
                lang,
                f"{name} {value!r} is not an SDMX period; use 2026, 2026-03, 2026-03-15 "
                "or 2026-Q1.",
                f"{name} {value!r} n'est pas une période SDMX; utilisez 2026, 2026-03, "
                "2026-03-15 ou 2026-Q1.",
            )
        )


def _dataflow_id_from_structure(root: Element) -> str:
    dataflow = root.find(f".//{_qn('str', 'Dataflow')}")
    if dataflow is None:
        raise NotFound("No Dataflow found in SDMX structure response.")
    return dataflow.get("id", "")


def _parse_structure(root: Element) -> tuple[str, list[SdmxDimension]]:
    dataflow_id = _dataflow_id_from_structure(root)

    codelists: dict[str, dict[str, SdmxCode]] = {}
    for codelist_el in root.findall(f".//{_qn('str', 'Codelist')}"):
        codelist_id = codelist_el.get("id", "")
        codes: dict[str, SdmxCode] = {}
        for code_el in codelist_el.findall(_qn("str", "Code")):
            code_id = code_el.get("id", "")
            name_en, name_fr = "", ""
            for name_el in code_el.findall(_qn("com", "Name")):
                lang = name_el.get("{http://www.w3.org/XML/1998/namespace}lang")
                if lang == "en":
                    name_en = name_el.text or ""
                elif lang == "fr":
                    name_fr = name_el.text or ""
            parent_el = code_el.find(f"{_qn('str', 'Parent')}/Ref")
            parent_id = parent_el.get("id") if parent_el is not None else None
            codes[code_id] = SdmxCode(
                id=code_id, name_en=name_en, name_fr=name_fr, parent_id=parent_id
            )
        codelists[codelist_id] = codes

    dimensions: list[SdmxDimension] = []
    dimension_list = root.find(f".//{_qn('str', 'DimensionList')}")
    if dimension_list is not None:
        for dim_el in dimension_list.findall(_qn("str", "Dimension")):
            dim_id = dim_el.get("id", "")
            position = int(dim_el.get("position", "0"))
            ref = dim_el.find(
                f"{_qn('str', 'LocalRepresentation')}/{_qn('str', 'Enumeration')}/Ref"
            )
            codelist_id = ref.get("id", "") if ref is not None else ""
            dimensions.append(
                SdmxDimension(
                    position=position,
                    dimension_id=dim_id,
                    codelist_id=codelist_id,
                    codes=list(codelists.get(codelist_id, {}).values()),
                )
            )
    dimensions.sort(key=lambda d: d.position)
    return dataflow_id, dimensions


def _dimension_id(name: str) -> str:
    # SDMX dimension ids are the English names with every non-alphanumeric
    # character replaced by "_" (verified against Data_Structure_14100355:
    # "North American Industry Classification System (NAICS)" ->
    # "North_American_Industry_Classification_System__NAICS_").
    return re.sub(r"[^0-9A-Za-z]", "_", name)


def _no_table(product_id: int, lang: str) -> NotFound:
    return NotFound(
        _say(
            lang,
            f"No StatCan table with productId {product_id}.",
            f"Aucun tableau StatCan avec le productId {product_id}.",
        )
    )


async def _structure_from_wds(product_id: int, lang: str) -> list[SdmxDimension]:
    """Rebuild the dimension/codelist structure from WDS getCubeMetadata.

    Verified live 2026-10-02 for 18100004, 14100355 and 14100287: WDS
    member ids, names and parents equal the SDMX codelists one-for-one, so
    this is a faithful substitute when the SDMX structure document is empty
    or truncated (14100063 returned HTTP 200 with zero bytes).
    """
    try:
        metadata = await wds_client.get_cube_metadata(product_id)
    except (InvalidInput, NotFound, UpstreamError) as exc:
        raise _no_table(product_id, lang) from exc
    dimensions: list[SdmxDimension] = []
    for dim in metadata.dimensions:
        codes = [
            SdmxCode(
                id=str(m.member_id),
                name_en=m.member_name_en,
                name_fr=m.member_name_fr,
                parent_id=str(m.parent_member_id) if m.parent_member_id is not None else None,
            )
            for m in dim.members
        ]
        dim_id = _dimension_id(dim.dimension_name_en)
        dimensions.append(
            SdmxDimension(
                position=dim.dimension_position_id,
                dimension_id=dim_id,
                codelist_id=f"CL_{dim_id}",
                codes=codes,
            )
        )
    dimensions.sort(key=lambda d: d.position)
    return dimensions


async def _load_structure(product_id: int, lang: str) -> tuple[str, list[SdmxDimension], str]:
    """(dataflow_id, dimensions, source), cached 24 h so a warm call costs no round trip."""

    async def fetch() -> tuple[str, list[SdmxDimension], str]:
        url = f"{constants.BASE_URL}structure/Data_Structure_{product_id}"
        try:
            root = await _fetch_xml(url, lang=lang)
            dataflow_id, dimensions = _parse_structure(root)
        except InvalidInput as exc:
            # The structure endpoint's only 406 means an unknown table id.
            raise _no_table(product_id, lang) from exc
        except (_BadBodyError, NotFound):
            return f"DF_{product_id}", await _structure_from_wds(product_id, lang), "wds"
        return dataflow_id or f"DF_{product_id}", dimensions, "sdmx"

    value, _ = await cached_fetch(
        f"sdmx:structure:{product_id}", constants.CACHE_TTL_STRUCTURE_SECONDS, fetch
    )
    return value


async def get_structure(
    product_id: int,
    *,
    dimension_position: int | None = None,
    code_query: str = "",
    limit: int = constants.DEFAULT_CODE_LIMIT,
    offset: int = 0,
    lang: str = "en",
) -> SdmxStructure:
    """Dimension structure, with the codes of each dimension paged.

    `limit`/`offset` page the codes of each returned dimension, `code_query`
    keeps codes whose English or French name (or exact id) matches, and
    `dimension_position` returns a single dimension.
    """
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
    dataflow_id, all_dimensions, source = await _load_structure(product_id, lang)
    selected = [
        d for d in all_dimensions if dimension_position is None or d.position == dimension_position
    ]
    if dimension_position is not None and not selected:
        raise NotFound(
            _say(
                lang,
                f"No dimension at position {dimension_position} for productId {product_id}.",
                f"Aucune dimension à la position {dimension_position} pour le productId "
                f"{product_id}.",
            )
        )
    needle = code_query.strip().lower()
    notes: list[str] = []
    dimensions: list[SdmxDimension] = []
    for dim in selected:
        matching = [
            c
            for c in dim.codes
            if not needle
            or needle in c.name_en.lower()
            or needle in c.name_fr.lower()
            or needle == c.id
        ]
        page = matching[offset : offset + limit]
        if len(page) < len(matching):
            notes.append(f"{dim.dimension_id}: {len(page)} of {len(matching)} codes")
        dimensions.append(dim.model_copy(update={"codes": page, "code_count": len(dim.codes)}))
    return SdmxStructure(
        dataflow_id=dataflow_id,
        dimensions=dimensions,
        provenance=make_provenance(
            source="statcan-sdmx",
            url=f"{constants.BASE_URL}structure/Data_Structure_{product_id}",
            cached=False,
            schema_name="statcan.sdmx.SdmxStructure",
            coverage=(
                "Built from WDS getCubeMetadata because StatCan's SDMX structure document "
                "for this table is empty or truncated; member ids and names are identical."
                if source == "wds"
                else None
            ),
            limits=(
                "codes paged ("
                + "; ".join(notes)
                + "); use limit/offset, code_query or dimension_position for the rest"
                if notes
                else None
            ),
        ),
    )


async def get_key_for_dimension(
    product_id: int, dimension_position: int, *, lang: str = "en"
) -> SdmxOrKey:
    """Build a complete OR key covering every leaf code of one dimension.

    StatCan's SDMX API returns a sparse, unpredictable sample when a
    dimension with more than ~30 codes is wildcarded (left empty) in a
    query key. The fix is not to widen the wildcard -- it is to never
    wildcard that dimension at all: take its full codelist, keep only the
    leaf codes (any code never listed as another code's parent), and join
    their ids with '+' as an explicit OR key.
    """
    _, dimensions, _ = await _load_structure(product_id, lang)
    dimension = next((d for d in dimensions if d.position == dimension_position), None)
    if dimension is None:
        raise NotFound(
            _say(
                lang,
                f"No dimension at position {dimension_position} for productId {product_id}.",
                f"Aucune dimension à la position {dimension_position} pour le productId "
                f"{product_id}.",
            )
        )

    parent_ids = {code.parent_id for code in dimension.codes if code.parent_id}
    leaf_codes = [code for code in dimension.codes if code.id not in parent_ids]
    or_key = "+".join(code.id for code in leaf_codes)

    return SdmxOrKey(
        product_id=product_id,
        dimension_position=dimension_position,
        dimension_id=dimension.dimension_id,
        leaf_code_count=len(leaf_codes),
        or_key=or_key,
        provenance=make_provenance(
            source="statcan-sdmx",
            url=f"{constants.BASE_URL}structure/Data_Structure_{product_id}",
            cached=False,
            schema_name="statcan.sdmx.SdmxOrKey",
            coverage=f"{len(leaf_codes)} leaf codes of {len(dimension.codes)} total codes",
        ),
    )


def _parse_data(root: Element, *, max_rows: int) -> tuple[list[SdmxSeries], bool]:
    """Return (series, any_series_truncated).

    `any_series_truncated` reflects whether an individual series actually
    hit the per-series `max_rows` cap -- the caller must not infer
    truncation from the *summed* row count across series, since several
    untruncated series can sum past max_rows on their own. Observations
    arrive oldest-first; when capped, the newest `max_rows` are kept.
    """
    series_list: list[SdmxSeries] = []
    any_series_truncated = False
    for series_el in root.findall(f".//{_qn('generic', 'Series')}"):
        series_key = {
            v.get("id", ""): v.get("value", "")
            for v in series_el.findall(f"{_qn('generic', 'SeriesKey')}/{_qn('generic', 'Value')}")
        }
        attrs = {
            v.get("id", ""): v.get("value", "")
            for v in series_el.findall(f"{_qn('generic', 'Attributes')}/{_qn('generic', 'Value')}")
        }
        observations: list[SdmxObservation] = []
        for obs_el in series_el.findall(_qn("generic", "Obs")):
            dim_el = obs_el.find(_qn("generic", "ObsDimension"))
            val_el = obs_el.find(_qn("generic", "ObsValue"))
            period = dim_el.get("value", "") if dim_el is not None else ""
            raw_value = val_el.get("value") if val_el is not None else None
            observations.append(
                SdmxObservation(
                    period=period, value=float(raw_value) if raw_value is not None else None
                )
            )
        if len(observations) > max_rows:
            observations = observations[-max_rows:]
            any_series_truncated = True

        vector_id = attrs.get("VECTOR_ID")
        scalar_factor = attrs.get("SCALAR_FACTOR")
        decimals = attrs.get("NB_DECIMAL")
        series_list.append(
            SdmxSeries(
                series_key=series_key,
                vector_id=int(vector_id) if vector_id else None,
                scalar_factor=int(scalar_factor) if scalar_factor is not None else None,
                decimals=int(decimals) if decimals is not None else None,
                dguid=attrs.get("DGUID"),
                uom_code=attrs.get("UOM"),
                observations=observations,
            )
        )
    return series_list, any_series_truncated


async def get_data(
    product_id: int,
    key: str,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    lang: str = "en",
) -> SdmxData:
    if last_n_observations is not None and (start_period or end_period):
        raise InvalidInput(
            _say(
                lang,
                "lastNObservations cannot be combined with startPeriod/endPeriod "
                "-- StatCan's SDMX API rejects that combination with HTTP 406.",
                "last_n_observations ne peut pas être combiné à start_period/end_period "
                "-- l'API SDMX de StatCan rejette cette combinaison (HTTP 406).",
            )
        )
    if last_n_observations is not None and last_n_observations < 1:
        raise InvalidInput(
            _say(lang, "last_n_observations must be >= 1.", "last_n_observations doit être >= 1.")
        )
    _check_period(start_period, "start_period", lang)
    _check_period(end_period, "end_period", lang)
    if not _KEY.match(key):
        raise InvalidInput(
            _say(
                lang,
                f"key {key!r} may only contain member ids, '.', and '+'.",
                f"key {key!r} ne peut contenir que des identifiants de membres, '.' et '+'.",
            )
        )

    # No structure round trip: the dataflow id is always DF_<productId>
    # (verified live), and the structure document is empty or truncated for
    # several large Labour Force Survey tables.
    dataflow_id = f"DF_{product_id}"
    url = f"{constants.BASE_URL}data/{dataflow_id}/{key}"
    params: dict[str, Any] = {}
    default_applied = False
    if start_period:
        params["startPeriod"] = start_period
    if end_period:
        params["endPeriod"] = end_period
    if last_n_observations is not None:
        params["lastNObservations"] = last_n_observations
    elif not start_period and not end_period:
        # Without a filter StatCan returns each series from its first period.
        params["lastNObservations"] = constants.DEFAULT_LAST_N
        default_applied = True

    hint = _say(
        lang,
        "StatCan sends this message for a malformed key or period as well: the key needs one "
        "segment per non-time dimension (see sdmx_get_structure) and periods look like 2026-03.",
        "StatCan envoie ce message aussi pour une clé ou une période mal formée : la clé exige "
        "un segment par dimension non temporelle (voir sdmx_get_structure) et les périodes "
        "ressemblent à 2026-03.",
    )
    try:
        root = await _fetch_xml(url, params=params or None, lang=lang, hint=hint)
    except _BadBodyError as exc:
        # Confirmed live: a key matching no series answers HTTP 200 with a
        # GenericData document whose only Series tag is a stray closing one.
        raise NotFound(
            _say(
                lang,
                f"Key {key!r} matched no series in table {product_id} (StatCan returned a "
                "malformed empty document). Check each member id with sdmx_get_structure.",
                f"La clé {key!r} ne correspond à aucune série du tableau {product_id} (StatCan "
                "a renvoyé un document vide mal formé). Vérifiez chaque identifiant avec "
                "sdmx_get_structure.",
            )
        ) from exc
    series, any_series_truncated = _parse_data(root, max_rows=constants.MAX_ROWS)
    series_total = len(series)
    if series_total > constants.MAX_SERIES:
        series = series[: constants.MAX_SERIES]
    row_count = sum(len(s.observations) for s in series)

    notes: list[str] = []
    if default_applied:
        notes.append(
            f"no period filter given: latest {constants.DEFAULT_LAST_N} observations per "
            "series (pass last_n_observations or start_period/end_period for more)"
        )
    if any_series_truncated:
        notes.append(f"newest {constants.MAX_ROWS} rows kept per series")
    if series_total > constants.MAX_SERIES:
        notes.append(f"first {constants.MAX_SERIES} of {series_total} series; narrow the key")
    return SdmxData(
        dataflow_id=dataflow_id,
        key=key,
        series=series,
        row_count=row_count,
        series_total=series_total if series_total > constants.MAX_SERIES else None,
        provenance=make_provenance(
            source="statcan-sdmx",
            url=url,
            cached=False,
            schema_name="statcan.sdmx.SdmxData",
            limits="; ".join(notes) if notes else None,
        ),
    )


async def get_vector_data(
    vector_id: int,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    lang: str = "en",
) -> SdmxData:
    series_info = await wds_client.get_series_info_from_vector(vector_id)
    # Non-time dimension count from WDS metadata (cached), not the SDMX
    # structure, which is unusable for some tables.
    metadata = await wds_client.get_cube_metadata(series_info.product_id)
    n_non_time_dims = len(metadata.dimensions)
    key = ".".join(series_info.coordinate.split(".")[:n_non_time_dims])
    return await get_data(
        series_info.product_id,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
        lang=lang,
    )
