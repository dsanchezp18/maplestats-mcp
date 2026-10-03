"""Typed response models for the extra StatCan SDMX spaces.

Field names verified against live responses of 2026-10-02: the dataflow
list (dataflow/all/all/latest), a structure with references=all, SDMX-CSV 2.0
data and the sdmx-sfs.statcan.gc.ca search service.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class SpaceFlow(BaseModel):
    flow: str = Field(description="agency,id,version: pass as `flow` to the other space tools.")
    agency: str
    id: str
    version: str
    name: str
    description: str = Field(description="Plain text, cut to a few hundred characters.")


class SpaceFlowList(BaseModel):
    space: str
    total_flows: int = Field(description="Dataflows in the whole space.")
    matched: int = Field(description="Dataflows matching `query` and `agency`.")
    agencies: dict[str, int] = Field(description="Dataflows per agency in the whole space.")
    non_production_flows: int = Field(
        description="Flows carrying the NonProductionDataflow annotation (every one so far)."
    )
    flows: list[SpaceFlow]
    provenance: Provenance


class FacetValue(BaseModel):
    label: str
    count: int
    filter_value: str = Field(description="Raw value to pass in `filters` to narrow by it.")


class SearchFacet(BaseModel):
    name: str
    values: list[FacetValue]


class SearchHit(BaseModel):
    flow: str = Field(description="agency,id,version: pass as `flow` to the other space tools.")
    agency: str
    id: str
    version: str
    tenant: str
    name: str
    description: str
    dimensions: list[str] = Field(description="Dimension names as the explorer shows them.")
    last_updated: str | None = None
    score: float | None = None


class SpaceSearch(BaseModel):
    space: str
    query: str
    tenants: list[str]
    found: int = Field(description="Dataflows matching in the searched tenants.")
    flows: list[SearchHit]
    facets: list[SearchFacet]
    provenance: Provenance


class SpaceCode(BaseModel):
    id: str
    name: str
    parent_id: str | None = None


class SpaceDimension(BaseModel):
    position: int = Field(description="0-based position in the data key.")
    id: str
    name: str
    codelist: str | None = None
    code_count: int = Field(description="Codes with data (all codes if no constraint exists).")
    codelist_size: int = Field(description="Codes in the whole codelist.")
    codes: list[SpaceCode]


class SpaceStructure(BaseModel):
    space: str
    flow: str
    name: str
    description: str
    non_production: bool
    dimensions: list[SpaceDimension]
    key_order: list[str] = Field(description="Dimension ids in data-key order, joined by '.'.")
    time_dimension: str | None = None
    attributes: list[str]
    start_period: str | None = None
    end_period: str | None = None
    observation_count: int | None = Field(
        default=None, description="Observations in the flow, from its availability constraint."
    )
    provenance: Provenance


class SpaceObservation(BaseModel):
    period: str
    value: float | None
    value_text: str | None = Field(
        default=None, description="The raw OBS_VALUE when it is not a number."
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Attributes that differ between observations of the series (status, flags).",
    )


class SpaceSeries(BaseModel):
    series_key: dict[str, str]
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Attributes constant over the series (UNIT_MEASURE, DECIMALS...).",
    )
    observations: list[SpaceObservation]


class SpaceData(BaseModel):
    space: str
    flow: str
    key: str
    series: list[SpaceSeries]
    row_count: int
    series_total: int = Field(description="Series in the upstream response.")
    non_production: bool | None = None
    provenance: Provenance
