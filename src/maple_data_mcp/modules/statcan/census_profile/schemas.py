"""Typed responses for the 2021 Census Profile SDMX API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class GeographyMatch(BaseModel):
    code: str
    name: str


class GeographySearchResult(BaseModel):
    level: str
    matches: list[GeographyMatch] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance


class CharacteristicMatch(BaseModel):
    code: str
    name: str


class CharacteristicSearchResult(BaseModel):
    matches: list[CharacteristicMatch] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance


class CensusProfileValue(BaseModel):
    geography_code: str
    geography_name: str
    characteristic_code: str
    characteristic_name: str
    topic: str | None = None
    gender: str
    statistic: str
    value: float | None = None
    value_raw: str | None = None
    flag: str | None = None
    confidence_interval_low: float | None = None
    confidence_interval_high: float | None = None


class CensusProfileDataResult(BaseModel):
    level: str
    values: list[CensusProfileValue] = Field(default_factory=list)
    release_date: str | None = None
    provenance: Provenance
