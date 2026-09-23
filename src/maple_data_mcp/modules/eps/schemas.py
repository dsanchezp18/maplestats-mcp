from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance

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


class OccurrenceSummary(BaseModel):
    dataset: Dataset
    group_by: GroupBy
    where: str
    total_matches: int
    groups: list[OccurrenceCount]
    provenance: Provenance


class LoadDate(BaseModel):
    last_load_date: date | None
    raw_value: str | None
    provenance: Provenance
