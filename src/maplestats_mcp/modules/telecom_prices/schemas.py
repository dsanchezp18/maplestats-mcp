"""Typed responses for the CRTC Communications Market Reports module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Service = Literal["mobile", "internet"]
Region = Literal["national", "urban", "rural"]


class PlanPricePoint(BaseModel):
    year: int = Field(description="Prices as advertised on December 31 of this year.")
    plan: str = Field(
        description="Service basket: a mobile data allowance ('5 GB', 'Talk Plan' / "
        "'Forfait voix') or an Internet speed ('50/10 Mbps')."
    )
    geography: str = Field(
        description="Province or territory code, 'Canada', 'Provinces', 'Territories', or "
        "(2022 on) 'North' and 'South'."
    )
    region: Region
    technology: str | None = Field(
        default=None,
        description="Mobile only: '3G', 'LTE', '5G', or 'lowest' (the average of the lowest "
        "price each provider reported, whatever the technology).",
    )
    average_price: float | None = Field(
        default=None, description="Average monthly price in dollars, before taxes; None if '--'."
    )
    as_published: str | None = Field(
        default=None, description="The cell's text when it is not a number (e.g. '--')."
    )


class PlanPrices(BaseModel):
    service: Service
    dataset: str = Field(description="The CRTC dataset's title.")
    dataset_url: str
    version: str | None = Field(default=None, description="The workbook's version number.")
    released: date | None = Field(default=None, description="The workbook's release date.")
    points: list[PlanPricePoint] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    plans: list[str] = Field(
        default_factory=list, description="Every plan in the sheet, for the `plan` argument."
    )
    years: list[int] = Field(default_factory=list)
    method: str = Field(description="How the CRTC collects and averages these prices.")
    provenance: Provenance


class CityPlanPriceAverage(BaseModel):
    year: int = Field(description="Prices as reported for December 31 of this year.")
    cma: str = Field(description="Census metropolitan area as the CRTC names it ('Montréal').")
    province: str = Field(description="Province or territory code.")
    plan: str = Field(description="Mobile data allowance or talk-only plan, or Internet speed.")
    technology: str | None = Field(
        default=None,
        description="Mobile only: '3G', 'LTE' or '5G' when the call kept one network, 'all' "
        "when every network's rows are averaged.",
    )
    average_price: float = Field(
        description="Computed by MapleStats: mean of the reported monthly prices in the CRTC's "
        "Prix-Prices sheet (every provider, brand and network row once), in dollars before "
        "taxes, rounded to the cent."
    )
    reported_prices: int = Field(description="Number of reported prices behind the average.")
    providers: int | None = Field(
        default=None,
        description="Number of distinct reporting providers; None for 2016, whose rows name none.",
    )
    lowest_per_provider_average: float | None = Field(
        default=None,
        description="Computed by MapleStats: mean of each provider's lowest reported price, the "
        "way the CRTC averages its own published figures; None for 2016 (no provider names).",
    )
    min_price: float
    max_price: float


class CityPlanPriceRow(BaseModel):
    year: int
    cma: str
    province: str
    plan: str
    provider: str | None = Field(default=None, description="Reporting entity (blank in 2016).")
    brand: str | None = None
    technology: str | None = Field(default=None, description="Mobile only: 3G, LTE or 5G.")
    price: float | None = Field(
        default=None, description="Reported monthly price in dollars, before taxes."
    )
    as_published: str | None = Field(
        default=None, description="The cell's text when it is not a number."
    )


class CmaCoverage(BaseModel):
    cma: str
    province: str
    years: list[int] = Field(
        default_factory=list, description="Years with reported prices for this service."
    )


class CityPlanPrices(BaseModel):
    service: Service
    cmas_requested: list[str] = Field(
        default_factory=list, description="The census metropolitan areas the call matched."
    )
    dataset: str = Field(description="The CRTC dataset's title.")
    dataset_url: str
    version: str | None = Field(default=None, description="The workbook's version number.")
    released: date | None = Field(default=None, description="The workbook's release date.")
    average_basis: str = Field(
        description="Says that the averages are computed by MapleStats, not published by the CRTC."
    )
    averages: list[CityPlanPriceAverage] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    rows: list[CityPlanPriceRow] = Field(
        default_factory=list, description="The provider rows behind the averages (include_rows)."
    )
    rows_returned: int
    rows_matched: int
    plans: list[str] = Field(
        default_factory=list, description="Every plan in the sheet, for the `plan` argument."
    )
    years: list[int] = Field(default_factory=list)
    cmas: list[CmaCoverage] = Field(
        default_factory=list,
        description="Every census metropolitan area in the sheet and its years, for `city`.",
    )
    notes: list[str] = Field(default_factory=list)
    method: str = Field(description="How the CRTC collects the prices and how these are averaged.")
    provenance: Provenance


class MarketTableRef(BaseModel):
    table_id: str = Field(description="The workbook tab, e.g. 'MB-S3'; pass it as `table`.")
    label: str = Field(description="'Figure 12', 'Supplementary Table 3'...")
    kind: Literal["infographic", "figure", "table", "supplementary", "other"]
    title: str


class MarketTableList(BaseModel):
    sector: Service
    dataset: str
    dataset_url: str
    tables: list[MarketTableRef] = Field(default_factory=list)
    provenance: Provenance


class MarketObservation(BaseModel):
    block: str | None = Field(
        default=None, description="Sub-table title when a sheet holds several tables."
    )
    series: str = Field(description="The row label (several label columns are joined with ' | ').")
    qualifier: str | None = Field(
        default=None, description="A second header under the years, e.g. Residential/Business."
    )
    year: int
    mobile_phone_only: bool = Field(
        description="True for columns marked '(MP)': from 2020 the CRTC counts mobile phone "
        "services only, so these are not comparable with earlier years."
    )
    value: float | None = Field(
        default=None,
        description="As stored in the workbook; shares are often fractions (0.283 = 28.3%).",
    )
    as_published: str | None = Field(
        default=None, description="The cell's text when it was text ('$59.97', 'N/A')."
    )


class MarketTable(BaseModel):
    sector: Service
    table_id: str
    label: str
    title: str
    dataset: str
    dataset_url: str
    observations: list[MarketObservation] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list, description="Distinct row labels.")
    notes: list[str] = Field(default_factory=list, description="Source line and footnotes.")
    derived_columns_left_out: list[str] = Field(
        default_factory=list,
        description="Growth and CAGR columns, left out: compute them from the observations.",
    )
    provenance: Provenance


class TrendObservation(BaseModel):
    period: str = Field(description="Quarter, e.g. '2026-Q1'.")
    year: int
    quarter: int
    market: str | None = Field(
        default=None, description="Residential, Business or Combined (none for TV distribution)."
    )
    metric: str
    subcategory: str | None = None
    measure: str = Field(description="Revenues, Subscribers, Lines, Minutes, data (GB)...")
    value: float = Field(description="Dollars for revenues; counts or GB otherwise.")


class QuarterlyTrends(BaseModel):
    service: Literal["mobile", "internet", "wireline", "tv_distribution"]
    dataset: str
    dataset_url: str
    version: str | None = None
    released: date | None = None
    observations: list[TrendObservation] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    metrics: list[str] = Field(
        default_factory=list, description="Every metric in the sheet, for the `metric` argument."
    )
    provenance: Provenance
