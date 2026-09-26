"""Typed responses for Competition Bureau merger reviews."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Outcome = Literal["ARC", "NAL", "CA", "JD", "TA", "Other", "Ongoing"]


class MergerReview(BaseModel):
    parties: str
    opened: date | None = Field(default=None, description="Weekly report only.")
    concluded: date | None = Field(default=None, description="Weekly report only.")
    concluded_month: str | None = Field(
        default=None, description="YYYY-MM: the month concluded (both reports)."
    )
    naics: str | None = Field(default=None, description="NAICS industry code, as reported.")
    outcome: str
    outcome_label: str
    report: Literal["current", "archive"]


class MergerSearchResult(BaseModel):
    reviews: list[MergerReview] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    outcome_counts: dict[str, int] = Field(
        default_factory=dict, description="Outcome code -> number of matching reviews."
    )
    outcome_legend: dict[str, str] = Field(default_factory=dict)
    provenance: Provenance
