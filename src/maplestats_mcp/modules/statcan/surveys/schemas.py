"""Typed responses for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class SurveyListing(BaseModel):
    survey_id: int
    name: str


class SurveyListResult(BaseModel):
    query: str
    surveys: list[SurveyListing] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class SurveyMetadata(BaseModel):
    survey_id: int
    name: str
    status: str | None = None
    frequency: str | None = None
    description: str | None = None
    subjects: list[str] = Field(default_factory=list)
    detail_url: str
    provenance: Provenance
