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


class GeoQueryResult(BaseModel):
    year: str
    service: str
    layer_id: int
    where: str
    features: list[GeoFeature] = Field(default_factory=list)
    returned_count: int
    exceeded_transfer_limit: bool
    result_offset: int
    provenance: Provenance
