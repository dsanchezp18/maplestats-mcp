"""Typed responses for StatCan's geo.statcan.gc.ca ArcGIS REST census-geography service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class GeoServiceSummary(BaseModel):
    name: str
    service_type: str
    language: str = Field(description="'en' or 'fr': every product is published in both.")


class GeoServiceList(BaseModel):
    year: str
    services: list[GeoServiceSummary] = Field(default_factory=list)
    provenance: Provenance


class GeoLayerField(BaseModel):
    name: str
    field_type: str
    alias: str | None = None


class GeoLayerSummary(BaseModel):
    layer_id: int
    name: str
    geometry_type: str | None = None


class GeoLayerDetail(BaseModel):
    year: str
    service: str
    layer_id: int
    name: str
    geometry_type: str | None = None
    fields: list[GeoLayerField] = Field(default_factory=list)
    max_record_count: int | None = None
    spatial_reference_wkid: int | None = None
    provenance: Provenance


class GeoFeature(BaseModel):
    attributes: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | None = None


class SpatialFilter(BaseModel):
    """The spatial predicate applied to a query, echoed back for audit."""

    kind: str = Field(description="'point' or 'bbox'.")
    lon: float | None = None
    lat: float | None = None
    distance_m: float | None = Field(
        default=None, description="Search radius in metres around the point, when given."
    )
    bbox: list[float] | None = Field(
        default=None, description="[min_lon, min_lat, max_lon, max_lat] in WGS84."
    )


class GeoQueryResult(BaseModel):
    year: str
    service: str
    layer_id: int
    where: str
    spatial_filter: SpatialFilter | None = None
    features: list[GeoFeature] = Field(default_factory=list)
    returned_count: int
    exceeded_transfer_limit: bool
    result_offset: int
    provenance: Provenance


class GeoSpatialLayer(BaseModel):
    layer_id: int
    name: str
    parent_layer_id: int | None = None
    is_group: bool = Field(
        default=False, description="A folder of sub-layers: it holds no rows and cannot be queried."
    )
    geometry_type: str | None = None
    province: str | None = Field(default=None, description="NRN only: two-letter code.")
    road_class: str | None = Field(default=None, description="NRN only: English layer family.")


class GeoSpatialLayerList(BaseModel):
    dataset: str
    service_url: str
    max_record_count: int | None = None
    capabilities: str | None = None
    layers: list[GeoSpatialLayer] = Field(default_factory=list)
    provenance: Provenance


class GeoSpatialLayerDetail(BaseModel):
    dataset: str
    layer_id: int
    name: str
    geometry_type: str | None = None
    fields: list[GeoLayerField] = Field(default_factory=list)
    max_record_count: int | None = None
    spatial_reference_wkid: int | None = None
    provenance: Provenance


class GeoSpatialQueryResult(BaseModel):
    dataset: str
    layer_id: int
    layer_name: str | None = None
    where: str
    spatial_filter: SpatialFilter | None = None
    features: list[GeoFeature] = Field(default_factory=list)
    returned_count: int
    exceeded_transfer_limit: bool
    result_offset: int
    provenance: Provenance
