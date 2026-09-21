"""Typed responses for StatCan's official Indicators JSON feeds."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class Indicator(BaseModel):
    registry_number: int
    indicator_number: int
    geo_code: int
    geo_name: str | None = None
    title: str
    value: str
    reference_period: str | None = None
    daily_url: str | None = None
    daily_title: str | None = None
    source_table: str | None = None
    release_date: str | None = None
    growth: str | None = None
    growth_details: str | None = None


class IndicatorList(BaseModel):
    dataset: str
    indicators: list[Indicator] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance
