from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Dataset = Literal["current", "2023"]
GroupBy = Literal["category", "group", "type", "month", "intersection"]


class Occurrence(BaseModel):
    reported_date: date | None
    category: str | None
    group: str | None
    type_group: str | None
    intersection: str | None
    longitude: float | None
    latitude: float | None


class OccurrenceList(BaseModel):
    dataset: Dataset
    where: str
    total_matches: int
    offset: int
    occurrences: list[Occurrence]
    provenance: Provenance


class OccurrenceCount(BaseModel):
    keys: dict[str, str | int | None]
    count: int
    partial: bool | None = Field(
        default=None,
        description="group_by='month' only: true when the dataset (and the date filters) "
        "cover only part of this month, so its count is not comparable to a full month.",
    )


class OccurrenceSummary(BaseModel):
    dataset: Dataset
    group_by: GroupBy
    where: str
    total_matches: int
    groups: list[OccurrenceCount]
    data_from: date | None = Field(
        default=None,
        description="group_by='month' only: first reported date the counts can include "
        "(the dataset's first date, or start_date if later).",
    )
    data_to: date | None = Field(
        default=None,
        description="group_by='month' only: last reported date the counts can include "
        "(the dataset's last date, or end_date if earlier).",
    )
    provenance: Provenance


class LoadDate(BaseModel):
    last_load_date: date | None
    raw_value: str | None
    provenance: Provenance
