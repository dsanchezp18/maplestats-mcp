from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

PriceMarket = Literal["day_ahead", "real_time"]


class DemandHour(BaseModel):
    date: date
    hour_ending: int = Field(description="Hour ending 1-24, Eastern Standard Time all year.")
    market_demand_mw: int | None = Field(description="Ontario demand plus exports.")
    ontario_demand_mw: int | None = Field(description="Ontario's own consumption incl. losses.")


class HourlyDemand(BaseModel):
    year: int
    rows: list[DemandHour]
    rows_matched: int
    peak_ontario_demand_mw: int | None
    peak_date: date | None
    peak_hour_ending: int | None
    average_ontario_demand_mw: float | None
    last_row_date: date | None = Field(description="Latest date in the yearly file.")
    provenance: Provenance


class RealtimeInterval(BaseModel):
    interval: int = Field(description="5-minute interval 1-12 within the delivery hour.")
    minute_ending: int = Field(description="Minute of the hour the interval ends at (5-60).")
    ontario_demand_mw: float | None
    total_energy_mw: float | None
    total_load_mw: float | None
    total_loss_mw: float | None
    flag: str | None


class RealtimeDemand(BaseModel):
    delivery_date: date
    delivery_hour: int = Field(description="Hour ending 1-24, Eastern Standard Time.")
    intervals: list[RealtimeInterval]
    average_ontario_demand_mw: float | None
    created_at: str | None
    provenance: Provenance


class FuelHour(BaseModel):
    date: date
    hour_ending: int
    output_mw: dict[str, int | None] = Field(
        description="Metered output per fuel (nuclear, gas, hydro, wind, solar, biofuel, other)."
    )
    fuels_with_missing_data: list[str] = Field(
        description="Fuels whose hour has unavailable data points (OutputQuality below 0)."
    )


class FuelTotal(BaseModel):
    fuel: str
    energy_mwh: int = Field(description="Sum of hourly output over the matched hours.")
    share_percent: float | None
    hours_with_missing_data: int


class SupplyByFuel(BaseModel):
    year: int
    rows: list[FuelHour]
    rows_matched: int
    totals: list[FuelTotal]
    first_date: date | None
    last_date: date | None
    provenance: Provenance


class PricePoint(BaseModel):
    period: int = Field(description="Pricing hour 1-24 (day-ahead) or 5-minute interval 1-12.")
    price_cad_per_mwh: float | None = Field(
        description="Ontario Zonal Price incl. loss and congestion."
    )
    loss_component: float | None
    congestion_component: float | None
    flag: str | None


class ZonalPrices(BaseModel):
    market: PriceMarket
    delivery_date: date
    delivery_hour: int | None = Field(description="Set for real_time; null for day_ahead.")
    points: list[PricePoint]
    average_cad_per_mwh: float | None
    minimum_cad_per_mwh: float | None
    maximum_cad_per_mwh: float | None
    created_at: str | None
    provenance: Provenance


class HoepMonth(BaseModel):
    month: str
    arithmetic_average: float | None
    weighted_average: float | None
    on_peak_arithmetic: float | None
    off_peak_arithmetic: float | None
    on_peak_weighted: float | None
    off_peak_weighted: float | None


class HoepHistory(BaseModel):
    year: int
    months: list[HoepMonth]
    note: str
    provenance: Provenance


class AdequacyHour(BaseModel):
    hour_ending: int
    total_supply_mw: float | None
    total_requirements_mw: float | None
    excess_capacity_mw: float | None
    forecast_ontario_demand_mw: float | None
    peak_ontario_demand_mw: float | None
    internal_resource_outages_mw: float | None


class AdequacyOutlook(BaseModel):
    delivery_date: date
    created_at: str | None
    hours: list[AdequacyHour]
    minimum_excess_capacity_mw: float | None
    minimum_excess_hour: int | None
    peak_forecast_demand_mw: float | None
    provenance: Provenance


class IntertieSchedule(BaseModel):
    hour: int
    import_mw: float | None
    export_mw: float | None


class IntertieZone(BaseModel):
    zone: str
    schedules: list[IntertieSchedule]
    mean_actual_flow_mw: float | None
    intervals_reported: int


class IntertieFlows(BaseModel):
    date: date
    zones: list[IntertieZone]
    total_schedules: list[IntertieSchedule]
    total_mean_actual_flow_mw: float | None
    sign_convention: str
    created_at: str | None
    provenance: Provenance


QuebecDataset = Literal["recent", "history"]


class QuebecDemandPoint(BaseModel):
    timestamp: datetime = Field(description="Interval timestamp, UTC.")
    demand_mw: float | None


class QuebecDemand(BaseModel):
    dataset: QuebecDataset
    interval: str
    points: list[QuebecDemandPoint]
    rows_matched: int
    latest_timestamp: datetime | None
    latest_demand_mw: float | None
    peak_demand_mw: float | None
    average_demand_mw: float | None
    provenance: Provenance


class QuebecGenerationPoint(BaseModel):
    timestamp: datetime = Field(description="Interval timestamp, UTC.")
    total_mw: float | None
    hydro_mw: float | None
    wind_mw: float | None
    solar_mw: float | None
    thermal_mw: float | None
    other_mw: float | None


class QuebecGeneration(BaseModel):
    dataset: QuebecDataset
    points: list[QuebecGenerationPoint]
    rows_matched: int
    average_share_percent: dict[str, float] = Field(
        description="Mean share of each source in the mean total, over the matched rows."
    )
    provenance: Provenance


class QuebecTradePoint(BaseModel):
    timestamp: datetime = Field(description="Hour timestamp, UTC.")
    exports_total_mw: float | None = Field(
        description="Sum of the markets with positive net flow (verified on 48 live rows)."
    )
    net_exports_mw: dict[str, float | None] = Field(
        description="Per market; negative means Quebec is a net importer from it."
    )
    imports_mw: dict[str, float | None] = Field(description="Total imports per market.")
    import_sources_mw: dict[str, dict[str, float | None]] = Field(
        description="Imports per market by generation source (null where not reported)."
    )


class QuebecTrade(BaseModel):
    points: list[QuebecTradePoint]
    rows_matched: int
    provenance: Provenance
