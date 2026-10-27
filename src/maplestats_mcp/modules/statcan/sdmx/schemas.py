"""Typed response models for the StatCan SDMX submodule.

Field names verified against a live structure fetch (Data_Structure_18100004)
and a live data fetch (DF_18100004 key 2.2) this session.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.transform import TransformedSeries


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
    # Total codes in the dimension; `codes` holds only the requested page
    # (code_query/limit/offset), so this tells the caller what was left out.
    code_count: int | None = None


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
    """One observation. Its SDMX attributes (STATUS_CAN, SYMBOL, SECURITY_LEVEL)
    are only sent when they flag something; absent, the codes are None (normal,
    no symbol, public). Codes are the WDS ones and are decoded from getCodeSets."""

    period: str
    value: float | None = Field(
        description="As published, unscaled; null when StatCan has no value (see status)."
    )
    status_code: int | None = None
    status: str | None = Field(
        default=None,
        description="What status_code means, e.g. 'use with caution', 'too unreliable to be "
        "published', 'not available for a specific reference period'.",
    )
    symbol_code: int | None = None
    symbol: str | None = Field(
        default=None, description="What symbol_code means, e.g. 'preliminary', 'revised'."
    )
    security_level_code: int | None = None
    security_level: str | None = Field(
        default=None, description="What security_level_code means, e.g. suppressed (confidential)."
    )


class SdmxSeries(BaseModel):
    series_key: dict[str, str]
    vector_id: int | None = None
    scalar_factor: int | None = None
    decimals: int | None = None
    dguid: str | None = None
    uom_code: str | None = None
    observations: list[SdmxObservation]
    transformed: TransformedSeries | None = Field(
        default=None,
        description=(
            "Only with `transform` or `frequency`: values computed by MapleStats from "
            "`observations`, with the formula and unit. `observations` stay as published."
        ),
    )


class SdmxData(BaseModel):
    dataflow_id: str
    key: str
    series: list[SdmxSeries]
    row_count: int
    # Series in the response before the per-call cap; None when not capped.
    series_total: int | None = None
    provenance: Provenance
