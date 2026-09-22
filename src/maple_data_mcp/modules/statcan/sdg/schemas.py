"""Typed responses for StatCan's Sustainable Development Goals (SDG) Data Hub."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class SdgIndicatorSummary(BaseModel):
    code: str
    goal_number: str | None = None
    target_number: str | None = None
    indicator_name: str
    reporting_status: str | None = None


class SdgIndicatorSearchResult(BaseModel):
    framework: str
    query: str
    indicators: list[SdgIndicatorSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class SdgSource(BaseModel):
    organisation: str | None = None
    url: str | None = None
    url_text: str | None = None
    periodicity: str | None = None


class SdgIndicatorMetadata(BaseModel):
    code: str
    framework: str
    goal_number: str | None = None
    target_number: str | None = None
    indicator_name: str
    description: str | None = None
    computation_units: str | None = None
    reporting_status: str | None = None
    published: bool | None = None
    sources: list[SdgSource] = Field(default_factory=list)
    provenance: Provenance


class SdgObservation(BaseModel):
    year: int
    value: float | None = None
    disaggregations: dict[str, Any] = Field(default_factory=dict)


class SdgIndicatorData(BaseModel):
    code: str
    framework: str
    observations: list[SdgObservation] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance
