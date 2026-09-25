"""Typed response for plan_query."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class StepOut(BaseModel):
    tool: str = Field(description="Tool to invoke with call_tool.")
    purpose: str


class TopicMatch(BaseModel):
    topic: str
    label: str
    matched_terms: list[str]
    steps: list[StepOut]
    caveats: list[str]


class PlaceMatch(BaseModel):
    place: str
    kind: Literal["province", "city"]
    steps: list[StepOut] = Field(description="Local portals and sources for this place.")


class QueryPlan(BaseModel):
    question: str
    topics: list[TopicMatch] = Field(description="Best match first; at most 4.")
    places: list[PlaceMatch]
    fallback_steps: list[StepOut] = Field(description="Only when no topic matched.")
    guidance: list[str]
    provenance: Provenance
