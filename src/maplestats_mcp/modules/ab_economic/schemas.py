"""Typed responses for the Alberta Economic Dashboard data API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class TableInfo(BaseModel):
    table: str
    statcan_pid: str | None = Field(
        default=None, description="StatCan table the series mirrors, when the name ends in one."
    )


class TableList(BaseModel):
    tables: list[TableInfo]
    total_count: int
    query: str | None = None
    provenance: Provenance


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    distinct_count: int
    values: list[str] = Field(
        default_factory=list, description="Distinct values (capped); use them as filters."
    )
    values_truncated: bool = False


class TableFields(BaseModel):
    table: str
    indicator_name: str | None = None
    period: str | None = None
    columns: list[ColumnInfo]
    provenance: Provenance


class TableData(BaseModel):
    table: str
    filters: dict[str, str]
    rows: list[dict[str, Any]]
    total_rows: int = Field(description="Rows matching the filters and date range.")
    returned_count: int
    first_date: datetime | None = None
    last_date: datetime | None = None
    provenance: Provenance


class Indicator(BaseModel):
    name: str
    topic: str
    updated_at: datetime | None = None
    page_url: str


class PublishedSeries(BaseModel):
    name: str = Field(description="Chart title from the page's API Keys section.")
    table: str
    filters: dict[str, str] = Field(description="Pass to ab_economic_get_data as-is.")
    api_url: str


class IndicatorSeries(BaseModel):
    indicator: str
    page_url: str
    series: list[PublishedSeries]
    provenance: Provenance


class IndicatorList(BaseModel):
    indicators: list[Indicator]
    topics: list[str]
    provenance: Provenance
