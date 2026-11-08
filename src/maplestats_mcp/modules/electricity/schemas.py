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
    average_ontario_demand_mw: float | None = Field(
        description="Computed by MapleStats: mean of the hour's 5-minute ontario_demand_mw "
        "values that are not null (IESO publishes no hourly average in this file)."
    )
    created_at: str | None
    provenance: Provenance


class FuelHour(BaseModel):
    date: date
    hour_ending: int
    output_mw: dict[str, int | None] = Field(
        description="Metered output per fuel (nuclear, gas, hydro, wind, solar, biofuel, other)."
    )
    fuels_without_output: list[str] = Field(
        description="Fuels with no Output value for the hour (output_mw is null)."
    )
    unavailable_data_points: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Fuels whose Output is reported but IESO's OutputQuality flag is below 0: "
            "the number of data points (units) not available for the hour, so the "
            "value may be understated."
        ),
    )


class FuelTotal(BaseModel):
    fuel: str
    energy_mwh: int = Field(description="Sum of hourly output over the matched hours.")
    share_percent: float | None
    hours_without_output: int = Field(description="Matched hours with no Output for the fuel.")
    hours_with_unavailable_points: int = Field(
        description="Matched hours with an Output but some data points unavailable."
    )


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
    average_cad_per_mwh: float | None = Field(
        description="Computed by MapleStats: unweighted mean of the points' "
        "price_cad_per_mwh (nulls skipped), rounded to cents; not a published price."
    )
    minimum_cad_per_mwh: float | None = Field(
        description="Computed by MapleStats: lowest price_cad_per_mwh among the points."
    )
    maximum_cad_per_mwh: float | None = Field(
        description="Computed by MapleStats: highest price_cad_per_mwh among the points."
    )
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
    minimum_excess_capacity_mw: float | None = Field(
        description="Computed by MapleStats: lowest excess_capacity_mw among the hours."
    )
    minimum_excess_hour: int | None = Field(
        description="Computed by MapleStats: the hour_ending of minimum_excess_capacity_mw."
    )
    peak_forecast_demand_mw: float | None = Field(
        description="Computed by MapleStats: highest forecast_ontario_demand_mw among the hours."
    )
    provenance: Provenance


class IntertieSchedule(BaseModel):
    hour: int
    import_mw: float | None
    export_mw: float | None


class IntertieZone(BaseModel):
    zone: str
    schedules: list[IntertieSchedule]
    mean_actual_flow_mw: float | None = Field(
        description="Computed by MapleStats: mean of the zone's reported actual flows."
    )
    intervals_reported: int = Field(description="Actual flows the mean is taken over.")


class IntertieFlows(BaseModel):
    date: date
    zones: list[IntertieZone]
    total_schedules: list[IntertieSchedule]
    total_mean_actual_flow_mw: float | None = Field(
        description="Computed by MapleStats: mean of the reported total actual flows."
    )
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
    peak_demand_mw: float | None = Field(
        description="Computed by MapleStats: highest demand_mw among the returned points "
        "only, not over every rows_matched row."
    )
    average_demand_mw: float | None = Field(
        description="Computed by MapleStats: mean demand_mw of the returned points only "
        "(nulls skipped), not over every rows_matched row."
    )
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
        description="Computed by MapleStats: each source's mean output over the returned "
        "points (nulls skipped) as a percent of the sum of those means; not over every "
        "rows_matched row."
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


class QuebecFlowSeriesInfo(BaseModel):
    measure: str = Field(
        description="Hydro-Quebec's label, e.g. 'Débit total', 'Débit turbiné - Manic-2', "
        "'Débit déversé - Manic-2', 'Apport filtré'."
    )
    kind: str = Field(
        description="total (all water released), turbined (through the turbines), spilled "
        "(through spillways or dams), inflow (filtered natural inflow) or other."
    )
    time_step: str = Field(description="hourly or daily.")
    statistic: str = Field(description="Hydro-Quebec's 'type_mesure', e.g. 'Moyenne' (mean).")
    unit: str
    points: int
    first: datetime | None
    last: datetime | None
    latest_value: float | None


class QuebecFacility(BaseModel):
    facility_id: str = Field(description="Hydro-Quebec site id, e.g. '3-130'.")
    name: str
    region: str
    region_code: str | None
    latitude: float | None
    longitude: float | None
    records_since: str | None = Field(description="Site's 'date debut' as published.")
    series: list[QuebecFlowSeriesInfo]


class QuebecFacilityList(BaseModel):
    total_facilities: int
    total_matches: int
    facilities: list[QuebecFacility]
    provenance: Provenance


class QuebecFlowPoint(BaseModel):
    time: datetime = Field(description="UTC; daily values are stamped 00:00Z.")
    value: float


class QuebecFlowSeries(BaseModel):
    info: QuebecFlowSeriesInfo
    values: list[QuebecFlowPoint]


class QuebecFacilityFlows(BaseModel):
    facility: QuebecFacility
    series: list[QuebecFlowSeries]
    provenance: Provenance


# ------------------------------------------------------------- Alberta (AESO)

_AESO_NOTICE = (
    "AESO terms allow non-commercial use only: commercial use needs the AESO's written "
    "permission (https://www.aeso.ca/legal/)."
)


class AlbertaPoolPriceHour(BaseModel):
    date: date
    hour_ending: int = Field(
        description="Hour ending 1-24 on `date`, Alberta clock time (Mountain, with daylight "
        "saving)."
    )
    repeated_hour: bool = Field(
        description="True for the second hour ending 02 on the autumn daylight-saving day "
        "(AESO's '02*' row)."
    )
    pool_price: float | None = Field(description="Pool price, $/MWh.")
    rolling_30day_average: float | None = Field(
        description="AESO's 30-day rolling average pool price, $/MWh."
    )
    ail_demand_mw: float | None = Field(description="Alberta Internal Load, MW.")


class AlbertaPoolPrice(BaseModel):
    start_date: date
    end_date: date
    rows: list[AlbertaPoolPriceHour]
    rows_matched: int = Field(description="Published hours in the date range.")
    hours_not_yet_published: int = Field(
        description="Hours in the range that AESO lists without values (not yet settled)."
    )
    latest_published_date: date | None
    latest_published_hour_ending: int | None
    commercial_use_notice: str = _AESO_NOTICE
    provenance: Provenance


class AlbertaDailyPrice(BaseModel):
    date: date
    average: float | None = Field(description="Daily average pool price, $/MWh.")
    on_peak_average: float | None = Field(description="On-peak (HE 8-23) average, $/MWh.")
    off_peak_average: float | None = Field(description="Off-peak average, $/MWh.")
    rolling_30day_average: float | None
    rolling_30day_on_peak_average: float | None
    rolling_30day_off_peak_average: float | None


class AlbertaDailyPrices(BaseModel):
    start_date: date
    end_date: date
    days: list[AlbertaDailyPrice]
    requests_made: int = Field(description="31-day report requests behind this result.")
    commercial_use_notice: str = _AESO_NOTICE
    provenance: Provenance


class AlbertaMonth(BaseModel):
    month: str = Field(description="YYYY-MM.")
    layout: Literal["monthly_statistics", "legacy_daily_table"] = Field(
        description="monthly_statistics: AESO's summary table (about 2009 onward); "
        "legacy_daily_table: the older report's 'Monthly Value' row."
    )
    pool_price_minimum: float | None = Field(description="$/MWh.")
    pool_price_average: float | None = Field(description="$/MWh, simple mean of hours.")
    pool_price_maximum: float | None = Field(description="$/MWh.")
    pool_price_weighted_average: float | None = Field(
        description="$/MWh, hourly price times demand over total demand (newer layout only)."
    )
    on_peak_average: float | None = Field(
        description="$/MWh, from AESO's summary sentence (newer layout only)."
    )
    off_peak_average: float | None = Field(
        description="$/MWh, from AESO's summary sentence (newer layout only)."
    )
    ail_minimum_mw: float | None
    ail_average_mw: float | None
    ail_maximum_mw: float | None
    total_energy_gwh: float | None = Field(
        description="GWh as published (newer layout); for the legacy layout, AESO's MWh "
        "total divided by 1,000."
    )
    load_factor_percent: float | None = Field(description="Newer layout only.")
    url: str


class AlbertaMonthlySummary(BaseModel):
    months: list[AlbertaMonth]
    months_not_published: list[str] = Field(
        description="Requested months with no AESO summary yet (the current month, or a "
        "future one)."
    )
    commercial_use_notice: str = _AESO_NOTICE
    provenance: Provenance


class AlbertaFuelGroup(BaseModel):
    fuel: str = Field(description="AESO group name, e.g. WIND, COGENERATION, COMBINED CYCLE.")
    maximum_capability_mw: float | None
    total_net_generation_mw: float | None
    dispatched_contingency_reserve_mw: float | None


class AlbertaInterchange(BaseModel):
    path: str = Field(description="British Columbia, Montana or Saskatchewan.")
    actual_flow_mw: float | None = Field(
        description="Positive means flow out of Alberta (export), negative into Alberta "
        "(import); AIL = total net generation minus net actual interchange."
    )


class AlbertaAsset(BaseModel):
    group: str = Field(description="Section of the report, e.g. 'Wind', 'Gas: Cogeneration'.")
    asset: str = Field(description="Asset name with its AESO id in parentheses.")
    maximum_capability_mw: float | None
    total_net_generation_mw: float | None
    dispatched_contingency_reserve_mw: float | None
    net_to_grid: bool = Field(description="AESO's '*' mark: MC is the gross MW value.")
    includes_storage: bool = Field(description="AESO's '^' mark.")


class AlbertaSupplyDemand(BaseModel):
    last_update: str | None = Field(description="AESO's 'Last Update' stamp, Alberta time.")
    alberta_internal_load_mw: float | None
    total_net_generation_mw: float | None
    net_actual_interchange_mw: float | None
    net_to_grid_generation_mw: float | None
    other_measures_mw: dict[str, float | None] = Field(
        description="The report's other summary lines (contingency reserve, FFR, long lead "
        "time volume), keyed in snake_case."
    )
    generation_by_fuel: list[AlbertaFuelGroup]
    interchange: list[AlbertaInterchange]
    assets: list[AlbertaAsset] = Field(
        description="Per-asset rows, only when include_assets is true (filtered by group)."
    )
    commercial_use_notice: str = _AESO_NOTICE
    provenance: Provenance
