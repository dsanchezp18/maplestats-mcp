"""Typed responses for the 2016 Census Profile Web Data Service."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class Census2016Geography(BaseModel):
    geo_uid: str
    province_territory_code: str | None = None
    province_territory_name: str | None = None
    geo_id: str | None = None
    geo_name: str
    geo_type: str | None = None
    non_response_rate_short_form: float | None = None
    non_response_rate_long_form: float | None = None
    data_quality_flag: str | None = None


class Census2016GeographyList(BaseModel):
    level: str
    geographies: list[Census2016Geography] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance


class Census2016Value(BaseModel):
    geo_uid: str
    geo_name: str
    topic: str | None = None
    text_id: int | None = None
    hierarchy_id: str | None = None
    indent_level: int | None = None
    label: str
    note: str | None = None
    total_value: float | None = None
    total_symbol: str | None = None
    male_value: float | None = None
    male_symbol: str | None = None
    female_value: float | None = None
    female_symbol: str | None = None


class Census2016DataResult(BaseModel):
    dguid: str
    topic: str
    values: list[Census2016Value] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance
