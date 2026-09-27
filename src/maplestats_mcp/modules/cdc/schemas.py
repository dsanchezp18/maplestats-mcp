"""Typed responses for the Canadian Dairy Commission module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

MarketDataset = Literal["production", "sales_p10", "sales_by_region", "farms"]
MarketSegment = Literal[
    "volume",
    "butterfat_sales",
    "butterfat_revenue",
    "protein_sales",
    "protein_revenue",
    "other_solids_sales",
    "other_solids_revenue",
    "farm_count",
]


class DatasetInfo(BaseModel):
    key: str = Field(description="Dataset key, as used in this module's tool names.")
    title: str
    description: str
    tool: str = Field(description="The tool that returns this dataset.")
    source_format: str = Field(description="What the CDC publishes: 'csv' or 'html table'.")
    source_url: str
    coverage: str
    update_frequency: str


class RelatedSource(BaseModel):
    name: str
    url: str
    status: str = Field(
        description=(
            "'pdf_only', 'blocked_terms', 'blocked_access', 'no_data' or 'use_other_tool'."
        )
    )
    detail: str
    alternative: str | None = Field(
        default=None, description="Where to get comparable data instead, when there is a route."
    )


class CdcCatalogue(BaseModel):
    datasets: list[DatasetInfo]
    related_sources: list[RelatedSource] = Field(
        description="Provincial marketing boards and national agencies checked, with why they "
        "have no tool here."
    )
    provenance: Provenance


class ComponentPrice(BaseModel):
    milk_class: str = Field(
        description="Milk class as the CDC writes it on its pages, e.g. '5(a)'."
    )
    milk_class_code: str = Field(description="Code as in the CSV file, e.g. '5A'.")
    effective_date: date = Field(description="First day of the month the price applies to.")
    butterfat_per_kg: float | None = Field(
        default=None, description="$/kg butterfat; None where the file has 0 or a blank."
    )
    protein_per_kg: float | None = Field(default=None, description="$/kg protein.")
    other_solids_per_kg: float | None = Field(default=None, description="$/kg other solids.")


class ComponentPriceResult(BaseModel):
    year_from: int
    year_to: int
    milk_class: str | None = None
    rows: list[ComponentPrice]
    row_count: int
    source_files: list[str]
    notes: list[str]
    provenance: Provenance


class SupportPrice(BaseModel):
    effective_label: str = Field(description="The row label as published, e.g. '2024 (May)'.")
    effective_date: date | None = Field(
        default=None,
        description="A plain year means February 1 of that year, the usual effective date.",
    )
    butter_per_kg: float | None = None


class SupportPriceResult(BaseModel):
    rows: list[SupportPrice]
    row_count: int
    source_page: str
    notes: list[str]
    provenance: Provenance


class QuotaMonth(BaseModel):
    year: int
    month: int
    period: str = Field(description="YYYY-MM.")
    total_quota_kg_butterfat: int | None = Field(
        default=None, description="None when the published figure is malformed."
    )
    published_value: str = Field(description="The figure exactly as it appears on the page.")
    change_from_year_ago_pct: float | None = Field(
        default=None, description="Published only on the 2017 and early-2018 pages."
    )


class QuotaResult(BaseModel):
    year_from: int
    year_to: int
    rows: list[QuotaMonth]
    row_count: int
    source_pages: list[str]
    notes: list[str]
    provenance: Provenance


class MilkClass(BaseModel):
    milk_class: str = Field(description="Class or subclass as published, e.g. '3(c) 4'.")
    class_group: str = Field(description="Top-level class: '1' to '5'.")
    products: list[str]


class MilkClassResult(BaseModel):
    classes: list[MilkClass]
    class_count: int
    source_page: str
    provenance: Provenance


class MarketDataRow(BaseModel):
    period_end: date = Field(description="Period end date; farm counts are dated August 1.")
    dataset: MarketDataset
    dataset_label: str
    milk_class: str | None = Field(default=None, description="Product level 1, e.g. 'Class 3'.")
    milk_subclass: str | None = Field(default=None, description="Product level 2, e.g. 'Class 3D'.")
    province: str | None = Field(default=None, description="Two-letter code; production and farms.")
    region: str | None = Field(default=None, description="East or West; sales_by_region only.")
    segment: str = Field(description="Measure and unit, e.g. 'Butterfat Sales (kg)'.")
    unit: str = Field(description="'L', 'kg', '$' or 'count'.")
    value: float | None = None


class MarketDataResult(BaseModel):
    dataset: MarketDataset
    total_matched: int
    returned_count: int
    rows: list[MarketDataRow]
    latest_date: date | None = None
    dictionary_url: str
    notes: list[str]
    provenance: Provenance
