from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class FirYear(BaseModel):
    year: int
    last_updated: str | None = Field(
        default=None, description="Date the year's file was last updated (YYYY-MM-DD)."
    )
    posted: str | None = Field(default=None, description="Date the file was posted (YYYY-MM-DD).")
    url: str


class Schedule(BaseModel):
    code: str = Field(description="Schedule code from the SLC, e.g. '40X' or '26A'.")
    name: str
    sub_schedules: list[str] = Field(default_factory=list)
    lines: int = Field(description="Distinct lines reported on the schedule this year.")
    data_points: int = Field(description="Distinct schedule-line-column codes (SLC).")


class ScheduleList(BaseModel):
    year: int
    municipalities_filed: int = Field(
        description="Municipalities whose return for the year is in the file."
    )
    years: list[FirYear] = Field(description="Every year the Ministry publishes, newest first.")
    schedules: list[Schedule]
    provenance: Provenance


class Municipality(BaseModel):
    munid: str = Field(description="Ministry municipal ID (MUNID), the key the other tools take.")
    name: str = Field(description="Name with its type suffix, e.g. 'Toronto C', 'Peel R'.")
    tier: str = Field(description="UT (upper tier), LT (lower tier) or ST (single tier).")
    tier_name: str
    municipal_type: str | None = None
    upper_tier_number: str | None = Field(
        default=None, description="UT_NUMBER: the upper tier a lower tier belongs to."
    )
    assessment_code: str | None = None
    sgc_code: str | None = Field(default=None, description="Standard Geographical Classification.")
    service_office: str | None = Field(
        default=None, description="Ministry Municipal Services Office region."
    )
    population: float | None = Field(default=None, description="Schedule 02, line 0041.")
    households: float | None = Field(default=None, description="Schedule 02, line 0040.")
    last_updated: str | None = Field(
        default=None, description="When this municipality's return was last updated."
    )


class MunicipalitySearch(BaseModel):
    query: str
    year: int
    total: int
    municipalities: list[Municipality]
    provenance: Provenance


class Line(BaseModel):
    slc: str = Field(description="Schedule-line-column code, e.g. 'slc.40X.L0410.C01.11'.")
    schedule: str
    schedule_name: str
    sub_schedule: str | None = None
    line: str
    line_desc: str | None = None
    column: str
    column_desc: str | None = None
    datatype: str | None = Field(
        default=None, description="currency, non-currency, percentage, text or unspecified."
    )
    municipalities: int = Field(description="Municipalities reporting a value this year.")


class LineSearch(BaseModel):
    query: str
    year: int
    total: int
    lines: list[Line]
    provenance: Provenance


class ScheduleValue(BaseModel):
    slc: str
    sub_schedule: str | None = None
    line: str
    line_desc: str | None = None
    column: str
    column_desc: str | None = None
    datatype: str | None = None
    amount: float | None = Field(default=None, description="Dollars for currency data points.")
    text: str | None = None


class ScheduleResult(BaseModel):
    municipality: Municipality
    year: int
    schedule: str = Field(
        description="The schedule asked for; a bare number ('26') covers all its parts (26A, 26B)."
    )
    schedule_name: str
    total: int = Field(description="Data points on the schedule before the row cap.")
    values: list[ScheduleValue]
    provenance: Provenance


class ComparisonRow(BaseModel):
    year: int
    munid: str
    municipality: str
    tier: str
    amount: float | None = None
    text: str | None = None
    population: float | None = None
    per_capita: float | None = Field(
        default=None, description="amount / population, when per_capita was asked for."
    )


class ComparisonResult(BaseModel):
    slc: str
    schedule_name: str | None = None
    line_desc: str | None = None
    column_desc: str | None = None
    datatype: str | None = None
    label_changes: list[str] = Field(
        default_factory=list,
        description="Years where the line or column label differs: the code may mean something else.",
    )
    years: list[int]
    per_capita: bool
    total: int = Field(description="Matching rows before the limit.")
    rows: list[ComparisonRow]
    provenance: Provenance
