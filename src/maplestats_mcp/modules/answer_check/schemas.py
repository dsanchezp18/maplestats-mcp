"""Typed input and output of check_answer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

CheckKind = Literal[
    "value",
    "scale",
    "newer_period",
    "period",
    "geography",
    "not_published",
    "seasonal_adjustment",
    "quality_flag",
    "unit",
    "sum",
    "fitness_rule",
    "series",
]


class CitedFigure(BaseModel):
    """One figure the answer will report, and where it comes from."""

    value: float | str | None = Field(
        default=None,
        description=(
            "The number as the answer writes it (6.6, 2.06, 20512); text ('6.50') keeps "
            "trailing zeros. It is matched at its written precision: 170 means 169.5 to "
            "170.5. Null when the answer will say the figure is not published."
        ),
    )
    unit: str | None = Field(
        default=None,
        description=(
            "As written: 'percent', 'thousands of persons', 'billion dollars', "
            "'chained 2017 dollars', 'index'. A scale word (thousand, million, billion; "
            "in French milliard = 10^9, billion = 10^12) is applied to value."
        ),
    )
    period: str | None = Field(
        default=None,
        description=(
            "Reference period: 2024, 2026-09, 2026-Q2 or 2026-09-01. A year cited for a "
            "monthly series is compared with that year's average."
        ),
    )
    geography: str | None = Field(default=None, description="The place the figure is for.")
    vector_id: int | None = Field(
        default=None, description="StatCan vector id (v41690973 is 41690973)."
    )
    product_id: str | None = Field(
        default=None, description="StatCan table (11-10-0135 or 11100135), with coordinate."
    )
    coordinate: str | None = Field(default=None, description="Member ids, e.g. '12.1.7.2'.")
    boc_series: str | None = Field(
        default=None, description="Bank of Canada Valet series name, e.g. 'FXUSDCAD'."
    )


class AnswerProblem(BaseModel):
    figure: int | None = Field(
        description="Index of the figure in `figures` (from 0); null for the whole answer."
    )
    check: CheckKind
    problem: str
    fix: str


class AnswerCheck(BaseModel):
    problems: list[AnswerProblem] = Field(
        description="Only what is wrong or must be said; empty when the figures check out."
    )
    checked: int = Field(description="Figures re-read from their source.")
    notes: list[str] = Field(
        default_factory=list,
        description="Figures not checked (another source than StatCan or the Bank of Canada).",
    )
    provenance: Provenance
