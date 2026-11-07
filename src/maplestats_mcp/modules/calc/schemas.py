"""Typed inputs and results of the calc_ tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


# One published series: a StatCan vector, a StatCan table and coordinate, or a
# Bank of Canada Valet series (exactly one form). No class docstring on purpose:
# Pydantic would make it the schema's description, which tool_catalogue.json
# inlines into each parameter and the live tool's $ref does not, so search_tools
# and the discovery benchmark's second index would rank the calc_ tools apart.
class SeriesRef(BaseModel):
    vector_id: int | None = Field(
        default=None, description="StatCan vector id (v41690973 is 41690973)."
    )
    product_id: str | None = Field(
        default=None, description="StatCan table (14-10-0287 or 14100287), with coordinate."
    )
    coordinate: str | None = Field(
        default=None, description="Member ids of the table's series, e.g. '10.7.1.1.1.1'."
    )
    boc_series: str | None = Field(
        default=None, description="Bank of Canada Valet series name, e.g. 'V39079' or 'FXUSDCAD'."
    )


class SeriesValue(BaseModel):
    period: str = Field(description="2026-09 (month), 2026-Q3, 2026, or a date for daily data.")
    value: float | None = Field(
        description="In full units: the published value times its scale factor. Null if missing."
    )


class InputSeries(BaseModel):
    """A series a calculation read, with what is needed to cite it."""

    source: Literal["statcan", "boc"]
    id: str = Field(description="v41690973 for a StatCan vector, the Valet name for the Bank.")
    label: str | None = Field(default=None, description="The publisher's series title.")
    geography: str | None = Field(default=None, description="The Geography member, if any.")
    citation: str = Field(
        description=(
            "Ready to quote beside the result: publisher, table or series, vector, release or "
            "retrieval date. Add the reference periods used (values_used)."
        )
    )
    table_id: str | None = Field(
        default=None, description="StatCan table number, e.g. 14-10-0287-01."
    )
    url: str = Field(description="The table's page, or the Valet series' observations URL.")
    unit: str | None = Field(default=None, description="Unit of measure as published.")
    scale: str | None = Field(
        default=None, description="StatCan scalar factor as published, e.g. 'thousands'."
    )
    scale_multiplier: float = Field(
        default=1.0, description="Applied to every published value before the calculation."
    )
    frequency: str = Field(description="Frequency as published (monthly, quarterly, daily...).")
    periods_per_year: int | None = Field(
        default=None, description="12, 4, 1...; null for daily, weekly or irregular series."
    )
    release: str | None = Field(
        default=None, description="Release date of the newest value read (StatCan), YYYY-MM-DD."
    )
    values_used: list[SeriesValue] = Field(
        default_factory=list, description="The values the calculation used, in full units."
    )


class RatioPoint(BaseModel):
    period: str
    numerator: float | None
    denominator: float | None
    value: float | None = Field(description="Computed with `formula`; null if an input is missing.")


class RatioResult(BaseModel):
    numerator: InputSeries
    denominator: InputSeries
    frequency: str = Field(description="Frequency of the points, after any aggregation.")
    aggregation: str | None = Field(
        default=None,
        description="How published values were combined into each period, if they were.",
    )
    multiplier: float
    formula: str = Field(description="Exactly how each value was computed.")
    unit: str = Field(description="Unit of `value`.")
    points: list[RatioPoint]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class RankEntry(BaseModel):
    rank: int | None = Field(
        description="1 is the highest (or lowest with order='ascending'); ties share a rank. "
        "Null when the series has no value for the period."
    )
    label: str = Field(description="The place (Geography member) or the series title.")
    value: float | None
    series: InputSeries


class RankResult(BaseModel):
    period: str = Field(description="The period ranked.")
    order: str
    frequency: str
    aggregation: str | None = None
    unit: str = Field(description="Unit of every value ranked (they all share it).")
    formula: str
    entries: list[RankEntry] = Field(description="Ranked first, then those with no value.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class GrowthResult(BaseModel):
    series: InputSeries
    start_period: str
    end_period: str
    start_value: float
    end_value: float
    years: float = Field(
        description="Years between the two periods (periods apart / periods per year)."
    )
    cagr_percent: float = Field(description="Compound annual growth rate, percent a year.")
    total_change_percent: float = Field(description="Change from start to end, percent.")
    frequency: str
    aggregation: str | None = None
    formula: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class ChangeEvent(BaseModel):
    period: str = Field(description="The period (or date) whose value differs from the one before.")
    previous: float
    value: float
    change: float = Field(description="value - previous, in `change_unit`.")


class ChangeCountResult(BaseModel):
    series: InputSeries
    start: str
    end: str
    changes: int = Field(description="Number of changes larger than `threshold` in the window.")
    increases: int
    decreases: int
    threshold: float
    change_unit: str = Field(description="Unit of each change (percentage points for a rate).")
    baseline: SeriesValue | None = Field(
        default=None,
        description="The last value before the window, against which its first value is compared.",
    )
    events: list[ChangeEvent]
    formula: str
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
