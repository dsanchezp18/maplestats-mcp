"""Typed response models for the StatCan SDMX submodule.

Field names verified against a live structure fetch (Data_Structure_18100004)
and a live data fetch (DF_18100004 key 2.2) this session.
"""

from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class SdmxCode(BaseModel):
    id: str
    name_en: str
    name_fr: str
    parent_id: str | None = None


class SdmxDimension(BaseModel):
    position: int
    dimension_id: str
    codelist_id: str
    codes: list[SdmxCode]


class SdmxStructure(BaseModel):
    dataflow_id: str
    dimensions: list[SdmxDimension]
    provenance: Provenance


class SdmxOrKey(BaseModel):
    """The answer to "how do I query every leaf code of a large dimension?"."""

    product_id: int
    dimension_position: int
    dimension_id: str
    leaf_code_count: int
    or_key: str
    provenance: Provenance


class SdmxObservation(BaseModel):
    period: str
    value: float | None


class SdmxSeries(BaseModel):
    series_key: dict[str, str]
    vector_id: int | None = None
    scalar_factor: int | None = None
    decimals: int | None = None
    dguid: str | None = None
    uom_code: str | None = None
    observations: list[SdmxObservation]


class SdmxData(BaseModel):
    dataflow_id: str
    key: str
    series: list[SdmxSeries]
    row_count: int
    provenance: Provenance
