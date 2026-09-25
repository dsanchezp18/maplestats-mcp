"""HTTP client for StatCan's SDMX REST API.

Parses SDMX-ML (XML) directly — confirmed live this session that
StatCan's SDMX REST endpoint ignores format=jsondata/sdmx-json and any
Accept header, always returning SDMX 2.1 Generic Data XML for data
queries and structure-message XML for structure queries. See
constants.py for the confirmation note.
"""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element

# defusedxml, not stdlib xml.etree, to guard against entity-expansion
# ("billion laughs") DoS in the XML this module parses — StatCan is a
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
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import DataLocked, InvalidInput, NotFound
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

NS = constants.SDMX_NS


def _qn(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


async def _fetch_xml(url: str, *, params: dict[str, Any] | None = None) -> Element:
    await _limiter().acquire()
    response = await get_raw(url, params=params)
    if response.status_code == 409:
        raise DataLocked(f"{url} is locked during StatCan's daily update window (12am-8:30am ET).")
    if response.status_code == 406:
        raise InvalidInput(
            "StatCan's SDMX API rejected this combination of parameters "
            "(commonly: lastNObservations combined with startPeriod/endPeriod)."
        )
    return defused_ET.fromstring(response.content)


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


async def get_structure(product_id: int) -> SdmxStructure:
    url = f"{constants.BASE_URL}structure/Data_Structure_{product_id}"
    root = await _fetch_xml(url)
    dataflow_id, dimensions = _parse_structure(root)
    return SdmxStructure(
        dataflow_id=dataflow_id,
        dimensions=dimensions,
        provenance=make_provenance(
            source="statcan-sdmx", url=url, cached=False, schema_name="statcan.sdmx.SdmxStructure"
        ),
    )


async def get_key_for_dimension(product_id: int, dimension_position: int) -> SdmxOrKey:
    """Build a complete OR key covering every leaf code of one dimension.

    StatCan's SDMX API returns a sparse, unpredictable sample when a
    dimension with more than ~30 codes is wildcarded (left empty) in a
    query key. The fix is not to widen the wildcard — it is to never
    wildcard that dimension at all: fetch its full codelist from the
    structure document, keep only the leaf codes (any code that is
    never itself listed as another code's parent), and join their ids
    with '+' as an explicit OR key.
    """
    structure = await get_structure(product_id)
    dimension = next((d for d in structure.dimensions if d.position == dimension_position), None)
    if dimension is None:
        raise NotFound(f"No dimension at position {dimension_position} for productId {product_id}.")

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
    hit the per-series `max_rows` cap — the caller must not infer
    truncation from the *summed* row count across series, since several
    untruncated series can sum past max_rows on their own.
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
            if len(observations) >= max_rows:
                any_series_truncated = True
                break

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
) -> SdmxData:
    if last_n_observations is not None and (start_period or end_period):
        raise InvalidInput(
            "lastNObservations cannot be combined with startPeriod/endPeriod "
            "— StatCan's SDMX API rejects that combination with HTTP 406."
        )

    structure = await get_structure(product_id)
    dataflow_id = structure.dataflow_id or f"DF_{product_id}"
    url = f"{constants.BASE_URL}data/{dataflow_id}/{key}"
    params: dict[str, Any] = {}
    if start_period:
        params["startPeriod"] = start_period
    if end_period:
        params["endPeriod"] = end_period
    if last_n_observations is not None:
        params["lastNObservations"] = last_n_observations

    root = await _fetch_xml(url, params=params or None)
    series, any_series_truncated = _parse_data(root, max_rows=constants.MAX_ROWS)
    row_count = sum(len(s.observations) for s in series)

    return SdmxData(
        dataflow_id=dataflow_id,
        key=key,
        series=series,
        row_count=row_count,
        provenance=make_provenance(
            source="statcan-sdmx",
            url=url,
            cached=False,
            schema_name="statcan.sdmx.SdmxData",
            limits=f"capped at {constants.MAX_ROWS} rows per series"
            if any_series_truncated
            else None,
        ),
    )


async def get_vector_data(
    vector_id: int,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
) -> SdmxData:
    series_info = await wds_client.get_series_info_from_vector(vector_id)
    structure = await get_structure(series_info.product_id)
    n_non_time_dims = len(structure.dimensions)
    parts = series_info.coordinate.split(".")[:n_non_time_dims]
    key = ".".join(parts)
    return await get_data(
        series_info.product_id,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
    )
