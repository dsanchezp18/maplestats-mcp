"""Client for the IESO public reports (reports-public.ieso.ca/public).

Confirmed live 2026-09-29:

- Reports are static files in per-report folders. The undated
  `PUB_<Report>.xml` is the latest publication; `PUB_<Report>_YYYYMMDD.xml`
  (and `_YYYYMMDDHH.xml` for hourly reports) are dated copies kept for about
  three months. A missing file is an HTTP 404 HTML page.
- Hourly Demand: `Demand/PUB_Demand_<year>.csv`, three `\\` comment lines,
  then `Date,Hour,Market Demand,Ontario Demand`. The current-year file ends
  about a day behind the clock (2026-09-28 hour 1 on 2026-09-29).
- Generator output by fuel: one XML per year (7.9 MB for 2025), hours as
  `HourlyData/FuelTotal/EnergyValue/{OutputQuality,Output}`. OutputQuality is
  the number of unavailable data points as a negative integer (0 to -30 in the
  2025 file, about 7,500 of 59,000 values below 0). Those values come with an
  `Output` (gas 3247 MW at quality -1), so a negative quality means "some
  units not reported", not "no value"; `Output` itself is absent for a few
  fuel-hours; a `CONTROL ACTIONS` fuel appears on 24.
- Prices: HOEP ended with the 2025-05-01 market renewal (`DispUnconsHOEP` is
  an empty folder); its successor is the Ontario Zonal Price, published as
  `DAHourlyOntarioZonalPrice` (24 hours, tomorrow's file appears about 12:30
  EST) and `RealtimeOntarioZonalPrice` (12 five-minute intervals per hour).
- RealtimeTotals XML carries `ONTARIO DEMAND` per interval; its CSV twin does
  not, so the XML is used.
- Adequacy3 dated files exist for roughly the previous three months through
  34 days ahead; the undated file is the furthest-out day, not today.
  Future days have empty elements for many series.
- IntertieScheduleFlow: hourly `Import`/`Export` schedules per zone and
  5-minute `Actual` flows; positive flow is an export from Ontario.
"""

from __future__ import annotations

import csv
import statistics
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta, timezone

import httpx

from maplestats_mcp.modules.electricity import constants
from maplestats_mcp.modules.electricity.schemas import (
    AdequacyHour,
    AdequacyOutlook,
    DemandHour,
    FuelHour,
    FuelTotal,
    HoepHistory,
    HoepMonth,
    HourlyDemand,
    IntertieFlows,
    IntertieSchedule,
    IntertieZone,
    PriceMarket,
    PricePoint,
    RealtimeDemand,
    RealtimeInterval,
    SupplyByFuel,
    ZonalPrices,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.licences import IESO_TERMS
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_IESO_TZ = timezone(timedelta(hours=constants.IESO_UTC_OFFSET_HOURS))


def ieso_today() -> date:
    return datetime.now(UTC).astimezone(_IESO_TZ).date()


# ---------------------------------------------------------------- fetching


async def _get_text(path: str, context: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(f"{constants.BASE_URL}/{path}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(
                f"electricity:{context} has no published file at {path}. IESO keeps dated "
                "files for about three months; check the date, or omit it for the latest."
            ) from exc
        raise UpstreamError(
            f"electricity:{context} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"electricity:{context} did not respond in time.") from exc
    return response.text


_LICENCE = IESO_TERMS  # every reproduction must carry the IESO copyright notice


def _limits(extra: str = "") -> str | None:
    return extra or None


# -------------------------------------------------------------- XML helpers


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [child for child in element if _local(child.tag) == name]


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    found = _children(element, name)
    return found[0] if found else None


def _text(element: ET.Element | None, name: str) -> str | None:
    node = _child(element, name)
    if node is None or node.text is None or not node.text.strip():
        return None
    return node.text.strip()


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_xml(text: str, context: str) -> ET.Element:
    try:
        return ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise UpstreamError(f"electricity:{context} returned XML that did not parse.") from exc


def _hourly_series(container: ET.Element | None) -> dict[int, float | None]:
    """Map DeliveryHour -> value for a container of <X><DeliveryHour/><Value/></X>.

    The value element differs by series (EnergyMW, EnergyMWhr, AvgDemand) and is
    missing when IESO has no value yet, so read the first non-hour child.
    """
    series: dict[int, float | None] = {}
    if container is None:
        return series
    for item in container:
        hour = _number(_text(item, "DeliveryHour"))
        if hour is None:
            continue
        value = next((c for c in item if _local(c.tag) != "DeliveryHour"), None)
        series[int(hour)] = _number(value.text) if value is not None and value.text else None
    return series


def _date_from_text(value: str | None, context: str) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError as exc:
        raise UpstreamError(f"electricity:{context} has no valid delivery date.") from exc


def _dated_path(folder: str, report: str, target: date | None, hour: int | None = None) -> str:
    if target is None:
        return f"{folder}/PUB_{report}.xml"
    stamp = target.strftime("%Y%m%d") + (f"{hour:02d}" if hour is not None else "")
    return f"{folder}/PUB_{report}_{stamp}.xml"


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


def _check_hour(hour: int | None) -> None:
    if hour is not None and not 1 <= hour <= 24:
        raise InvalidInput(f"hour must be 1-24 (hour ending, EST), got {hour}.")


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= constants.MAX_LIMIT:
        raise InvalidInput(f"limit must be between 1 and {constants.MAX_LIMIT}, got {limit}.")


def _year_for_range(year: int | None, start: date | None, end: date | None, first: int) -> int:
    if start and end and start > end:
        raise InvalidInput("start_date must not be after end_date.")
    if start and end and start.year != end.year:
        raise InvalidInput("IESO publishes one file per calendar year; use one year per call.")
    anchor = start or end
    if year and anchor and anchor.year != year:
        raise InvalidInput("year does not match the year of start_date/end_date.")
    chosen = year or (anchor or ieso_today()).year
    last = ieso_today().year
    if not first <= chosen <= last:
        raise InvalidInput(f"year must be between {first} and {last}, got {chosen}.")
    return chosen


def _ttl_for_year(year: int) -> int:
    if year == ieso_today().year:
        return constants.CACHE_TTL_HOURLY_SECONDS
    return constants.CACHE_TTL_ARCHIVE_SECONDS


# ------------------------------------------------------------------ demand


def parse_demand_csv(text: str) -> list[DemandHour]:
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("\\")]
    reader = csv.DictReader(lines)
    needed = {"Date", "Hour", "Market Demand", "Ontario Demand"}
    if not reader.fieldnames or not needed <= set(reader.fieldnames):
        raise UpstreamError("electricity:hourly_demand CSV no longer has the expected columns.")

    def whole(value: str | None) -> int | None:
        number = _number(value)
        return None if number is None else int(number)

    rows = []
    for record in reader:
        hour = whole(record["Hour"])
        if hour is None:
            continue
        rows.append(
            DemandHour(
                date=_date_from_text(record["Date"], "hourly_demand"),
                hour_ending=hour,
                market_demand_mw=whole(record["Market Demand"]),
                ontario_demand_mw=whole(record["Ontario Demand"]),
            )
        )
    return rows


async def get_hourly_demand(
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> HourlyDemand:
    del lang
    _check_limit(limit)
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    chosen = _year_for_range(year, start, end, constants.FIRST_DEMAND_YEAR)
    path = f"Demand/PUB_Demand_{chosen}.csv"

    async def fetch() -> list[DemandHour]:
        return parse_demand_csv(await _get_text(path, "hourly_demand"))

    all_rows, was_cached = await cached_fetch(
        f"electricity:demand:{chosen}", _ttl_for_year(chosen), fetch
    )
    matched = [
        row
        for row in all_rows
        if (start is None or row.date >= start) and (end is None or row.date <= end)
    ]
    shown = matched[:limit] if (start or end) else matched[-limit:]
    valid = [row for row in matched if row.ontario_demand_mw is not None]
    peak = max(valid, key=lambda row: row.ontario_demand_mw or 0, default=None)
    return HourlyDemand(
        year=chosen,
        rows=shown,
        rows_matched=len(matched),
        peak_ontario_demand_mw=peak.ontario_demand_mw if peak else None,
        peak_date=peak.date if peak else None,
        peak_hour_ending=peak.hour_ending if peak else None,
        # Blank demand cells are skipped, not treated as zero.
        average_ontario_demand_mw=(
            round(statistics.fmean(r.ontario_demand_mw or 0 for r in valid), 1) if valid else None
        ),
        last_row_date=all_rows[-1].date if all_rows else None,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.HourlyDemand",
            freshness="current-year file refreshed daily; lags the clock by about a day",
            coverage="Ontario only (IESO-controlled grid)",
            licence=_LICENCE,
            limits=_limits(
                f"Rows capped at {limit}; peak and average cover all {len(matched)} matched hours."
            ),
        ),
    )


async def get_realtime_demand(
    date_text: str | None = None, hour: int | None = None, *, lang: str = "en"
) -> RealtimeDemand:
    del lang
    _check_hour(hour)
    target = _parse_date(date_text, "date")
    if (target is None) != (hour is None):
        raise InvalidInput("Give both date and hour for a past hour, or neither for the latest.")
    path = _dated_path("RealtimeTotals", "RealtimeTotals", target, hour)

    async def fetch() -> str:
        return await _get_text(path, "realtime_demand")

    text, was_cached = await cached_fetch(
        f"electricity:{path}", constants.CACHE_TTL_LATEST_SECONDS, fetch
    )
    root = _parse_xml(text, "realtime_demand")
    body = _child(root, "DocBody")
    if body is None:
        raise UpstreamError("electricity:realtime_demand has no DocBody.")
    intervals = []
    for item in _children(_child(body, "Energies"), "IntervalEnergy"):
        quantities = {
            (_text(mq, "MarketQuantity") or "").upper(): _number(_text(mq, "EnergyMW"))
            for mq in _children(item, "MQ")
        }
        number = int(_number(_text(item, "Interval")) or 0)
        intervals.append(
            RealtimeInterval(
                interval=number,
                minute_ending=number * 5,
                ontario_demand_mw=quantities.get("ONTARIO DEMAND"),
                total_energy_mw=quantities.get("TOTAL ENERGY"),
                total_load_mw=quantities.get("TOTAL LOAD"),
                total_loss_mw=quantities.get("TOTAL LOSS"),
                flag=_text(item, "Flag"),
            )
        )
    demands = [i.ontario_demand_mw for i in intervals if i.ontario_demand_mw is not None]
    return RealtimeDemand(
        delivery_date=_date_from_text(_text(body, "DeliveryDate"), "realtime_demand"),
        delivery_hour=int(_number(_text(body, "DeliveryHour")) or 0),
        intervals=intervals,
        average_ontario_demand_mw=round(statistics.fmean(demands), 1) if demands else None,
        created_at=_text(_child(root, "DocHeader"), "CreatedAt"),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.RealtimeDemand",
            freshness="updated about every hour with 12 five-minute intervals",
            licence=_LICENCE,
            limits=_limits("One delivery hour per call; dated files are kept about three months."),
        ),
    )


# ------------------------------------------------------------ supply / fuel


def parse_fuel_xml(text: str) -> list[FuelHour]:
    root = _parse_xml(text, "supply_by_fuel")
    body = _child(root, "DocBody")
    rows: list[FuelHour] = []
    for day in _children(body, "DailyData"):
        day_date = _date_from_text(_text(day, "Day"), "supply_by_fuel")
        for hourly in _children(day, "HourlyData"):
            output: dict[str, int | None] = {}
            without_output: list[str] = []
            unavailable: dict[str, int] = {}
            for total in _children(hourly, "FuelTotal"):
                fuel = (_text(total, "Fuel") or "").lower().replace(" ", "_")
                value = _child(total, "EnergyValue")
                amount = _number(_text(value, "Output"))
                output[fuel] = None if amount is None else int(amount)
                quality = _number(_text(value, "OutputQuality"))
                if amount is None:
                    without_output.append(fuel)
                elif quality is not None and quality < 0:
                    unavailable[fuel] = int(-quality)
            rows.append(
                FuelHour(
                    date=day_date,
                    hour_ending=int(_number(_text(hourly, "Hour")) or 0),
                    output_mw=output,
                    fuels_without_output=without_output,
                    unavailable_data_points=unavailable,
                )
            )
    if not rows:
        raise UpstreamError("electricity:supply_by_fuel file has no DailyData.")
    return rows


async def get_supply_by_fuel(
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> SupplyByFuel:
    del lang
    _check_limit(limit)
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    chosen = _year_for_range(year, start, end, constants.FIRST_FUEL_YEAR)
    path = f"GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_{chosen}.xml"

    async def fetch() -> list[FuelHour]:
        return parse_fuel_xml(await _get_text(path, "supply_by_fuel"))

    all_rows, was_cached = await cached_fetch(
        f"electricity:fuel:{chosen}", _ttl_for_year(chosen), fetch
    )
    matched = [
        row
        for row in all_rows
        if (start is None or row.date >= start) and (end is None or row.date <= end)
    ]
    shown = matched[:limit] if (start or end) else matched[-limit:]
    sums: dict[str, int] = {}
    gaps: dict[str, int] = {}
    partial: dict[str, int] = {}
    for row in matched:
        for fuel, amount in row.output_mw.items():
            if amount is not None:
                # An hour's average MW over one hour is that hour's MWh.
                sums[fuel] = sums.get(fuel, 0) + amount
        for fuel in row.fuels_without_output:
            gaps[fuel] = gaps.get(fuel, 0) + 1
        for fuel in row.unavailable_data_points:
            partial[fuel] = partial.get(fuel, 0) + 1
    generation = sum(v for f, v in sums.items() if f != constants.CONTROL_ACTIONS_FUEL)
    totals = [
        FuelTotal(
            fuel=fuel,
            energy_mwh=amount,
            share_percent=(
                round(100 * amount / generation, 2)
                if generation and fuel != constants.CONTROL_ACTIONS_FUEL
                else None
            ),
            hours_without_output=gaps.get(fuel, 0),
            hours_with_unavailable_points=partial.get(fuel, 0),
        )
        for fuel, amount in sorted(sums.items(), key=lambda item: -item[1])
    ]
    return SupplyByFuel(
        year=chosen,
        rows=shown,
        rows_matched=len(matched),
        totals=totals,
        first_date=matched[0].date if matched else None,
        last_date=matched[-1].date if matched else None,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.SupplyByFuel",
            freshness="current-year file refreshed daily; ends about a day behind the clock",
            coverage="IESO-metered generators; embedded (distribution-connected) supply excluded",
            licence=_LICENCE,
            limits=_limits(
                f"Rows capped at {limit}; totals cover all {len(matched)} matched hours. "
                "Shares exclude the control_actions series."
            ),
        ),
    )


# ------------------------------------------------------------------- prices


def _price_stats(points: list[PricePoint]) -> tuple[float | None, float | None, float | None]:
    prices = [p.price_cad_per_mwh for p in points if p.price_cad_per_mwh is not None]
    if not prices:
        return None, None, None
    return round(statistics.fmean(prices), 2), min(prices), max(prices)


async def get_zonal_prices(
    market: PriceMarket = "day_ahead",
    date_text: str | None = None,
    hour: int | None = None,
    *,
    lang: str = "en",
) -> ZonalPrices:
    del lang
    if market not in ("day_ahead", "real_time"):
        raise InvalidInput(f"market must be 'day_ahead' or 'real_time', got {market!r}.")
    _check_hour(hour)
    target = _parse_date(date_text, "date")
    if market == "day_ahead":
        if hour is not None:
            raise InvalidInput("hour applies to real_time only; day_ahead returns all 24 hours.")
        path = _dated_path("DAHourlyOntarioZonalPrice", "DAHourlyOntarioZonalPrice", target)
    else:
        if (target is None) != (hour is None):
            raise InvalidInput(
                "Give both date and hour for a past hour, or neither for the latest."
            )
        path = _dated_path("RealtimeOntarioZonalPrice", "RealtimeOntarioZonalPrice", target, hour)

    async def fetch() -> str:
        return await _get_text(path, f"{market}_prices")

    text, was_cached = await cached_fetch(
        f"electricity:{path}", constants.CACHE_TTL_LATEST_SECONDS, fetch
    )
    root = _parse_xml(text, f"{market}_prices")
    body = _child(root, "DocBody")
    if body is None:
        raise UpstreamError(f"electricity:{market}_prices has no DocBody.")
    points: list[PricePoint] = []
    if market == "day_ahead":
        for item in _children(body, "HourlyPriceComponents"):
            points.append(
                PricePoint(
                    period=int(_number(_text(item, "PricingHour")) or 0),
                    price_cad_per_mwh=_number(_text(item, "ZonalPrice")),
                    loss_component=_number(_text(item, "LossPriceCapped")),
                    congestion_component=_number(_text(item, "CongestionPriceCapped")),
                    flag=_text(item, "Flag"),
                )
            )
    else:
        for item in _children(body, "ZonalPrice"):
            points.append(
                PricePoint(
                    period=int(_number(_text(item, "Interval")) or 0),
                    price_cad_per_mwh=_number(_text(item, "LmpCap")),
                    loss_component=_number(_text(item, "LossPriceCap")),
                    congestion_component=_number(_text(item, "CongPriceCap")),
                    flag=_text(item, "Flag"),
                )
            )
    if not points:
        raise UpstreamError(f"electricity:{market}_prices file has no price rows.")
    average, low, high = _price_stats(points)
    delivery_hour = _number(_text(body, "DeliveryHour"))
    return ZonalPrices(
        market=market,
        delivery_date=_date_from_text(_text(body, "DeliveryDate"), f"{market}_prices"),
        delivery_hour=None if delivery_hour is None else int(delivery_hour),
        points=points,
        average_cad_per_mwh=average,
        minimum_cad_per_mwh=low,
        maximum_cad_per_mwh=high,
        created_at=_text(_child(root, "DocHeader"), "CreatedAt"),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.ZonalPrices",
            freshness=(
                "day-ahead file for tomorrow appears about 12:30 EST"
                if market == "day_ahead"
                else "one file per delivery hour, 12 five-minute intervals"
            ),
            coverage="Ontario Zonal Price only, the settlement price since 2025-05-01",
            licence=_LICENCE,
            limits=_limits(
                "Prices in CAD/MWh, capped values as published; dated files kept about "
                "three months. HOEP no longer exists after 2025-04."
            ),
        ),
    )


async def get_hoep_history(year: int | None = None, *, lang: str = "en") -> HoepHistory:
    del lang
    chosen = year or ieso_today().year - 1
    if not constants.FIRST_DEMAND_YEAR <= chosen <= 2025:
        raise InvalidInput(
            "HOEP year must be 2002-2025 (HOEP ended with the 2025-05-01 market renewal), "
            f"got {chosen}."
        )
    path = f"PriceHOEPAverage/PUB_PriceHOEPAverage_{chosen}.xml"

    async def fetch() -> str:
        return await _get_text(path, "hoep_history")

    text, was_cached = await cached_fetch(
        f"electricity:{path}", constants.CACHE_TTL_ARCHIVE_SECONDS, fetch
    )
    root = _parse_xml(text, "hoep_history")
    months = [
        HoepMonth(
            month=_text(item, "Month") or "",
            arithmetic_average=_number(_text(item, "ArithmeticAve")),
            weighted_average=_number(_text(item, "WeightedAve")),
            on_peak_arithmetic=_number(_text(item, "ArithmeticOnPeakAve")),
            off_peak_arithmetic=_number(_text(item, "ArithmeticOffPeakAve")),
            on_peak_weighted=_number(_text(item, "WeightedOnPeakAve")),
            off_peak_weighted=_number(_text(item, "WeightedOffPeakAve")),
        )
        for item in _children(_child(root, "DocBody"), "HOEP")
    ]
    if not months:
        raise UpstreamError("electricity:hoep_history file has no monthly rows.")
    return HoepHistory(
        year=chosen,
        months=months,
        note=(
            "Hourly Ontario Energy Price in CAD/MWh, replaced by the Ontario Zonal Price on "
            "2025-05-01; the two are not the same series."
        ),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.HoepHistory",
            freshness="closed series; the final year, 2025, is partial (to April)",
            licence=_LICENCE,
            limits=_limits(),
        ),
    )


# ----------------------------------------------------------------- adequacy


async def get_adequacy_outlook(
    date_text: str | None = None, *, lang: str = "en"
) -> AdequacyOutlook:
    del lang
    target = _parse_date(date_text, "date") or ieso_today()
    path = _dated_path("Adequacy3", "Adequacy3", target)

    async def fetch() -> str:
        return await _get_text(path, "adequacy_outlook")

    text, was_cached = await cached_fetch(
        f"electricity:{path}", constants.CACHE_TTL_HOURLY_SECONDS, fetch
    )
    root = _parse_xml(text, "adequacy_outlook")
    body = _child(root, "DocBody")
    if body is None:
        raise UpstreamError("electricity:adequacy_outlook has no DocBody.")
    supply = _child(body, "ForecastSupply")
    demand = _child(body, "ForecastDemand")
    ontario = _child(demand, "OntarioDemand")
    total_supply = _hourly_series(_child(supply, "TotalSupplies"))
    requirements = _hourly_series(_child(demand, "TotalRequirements"))
    excess = _hourly_series(_child(demand, "ExcessCapacities"))
    forecast = _hourly_series(_child(ontario, "ForecastOntDemand"))
    peak = _hourly_series(_child(ontario, "PeakDemand"))
    totals_node = _child(_child(supply, "InternalResources"), "TotalInternalResources")
    outages = _hourly_series(_child(totals_node, "Outages"))
    hours = [
        AdequacyHour(
            hour_ending=hour,
            total_supply_mw=total_supply.get(hour),
            total_requirements_mw=requirements.get(hour),
            excess_capacity_mw=excess.get(hour),
            forecast_ontario_demand_mw=forecast.get(hour),
            peak_ontario_demand_mw=peak.get(hour),
            internal_resource_outages_mw=outages.get(hour),
        )
        for hour in sorted(set(total_supply) | set(requirements) | set(excess) | set(forecast))
    ]
    if not hours:
        raise UpstreamError("electricity:adequacy_outlook file has no hourly series.")
    with_excess = [h for h in hours if h.excess_capacity_mw is not None]
    tightest = min(with_excess, key=lambda h: h.excess_capacity_mw or 0, default=None)
    forecasts = [h.forecast_ontario_demand_mw for h in hours if h.forecast_ontario_demand_mw]
    return AdequacyOutlook(
        delivery_date=_date_from_text(_text(body, "DeliveryDate"), "adequacy_outlook"),
        created_at=_text(_child(root, "DocHeader"), "CreatedAt"),
        hours=hours,
        minimum_excess_capacity_mw=tightest.excess_capacity_mw if tightest else None,
        minimum_excess_hour=tightest.hour_ending if tightest else None,
        peak_forecast_demand_mw=max(forecasts) if forecasts else None,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.AdequacyOutlook",
            freshness="one file per delivery day, revised through the day; about 34 days ahead",
            licence=_LICENCE,
            limits=_limits(
                "Future days leave many series empty (null). Per-fuel, zonal and area detail "
                "in the XML is not returned."
            ),
        ),
    )


# --------------------------------------------------------------- interties


def _schedules(container: ET.Element | None) -> list[IntertieSchedule]:
    return [
        IntertieSchedule(
            hour=int(_number(_text(item, "Hour")) or 0),
            import_mw=_number(_text(item, "Import")),
            export_mw=_number(_text(item, "Export")),
        )
        for item in _children(container, "Schedule")
    ]


def _mean_flow(container: ET.Element | None) -> tuple[float | None, int]:
    flows = [
        flow
        for item in _children(container, "Actual")
        if (flow := _number(_text(item, "Flow"))) is not None
    ]
    return (round(statistics.fmean(flows), 1) if flows else None), len(flows)


async def get_intertie_flows(date_text: str | None = None, *, lang: str = "en") -> IntertieFlows:
    del lang
    target = _parse_date(date_text, "date")
    path = _dated_path("IntertieScheduleFlow", "IntertieScheduleFlow", target)

    async def fetch() -> str:
        return await _get_text(path, "intertie_flows")

    text, was_cached = await cached_fetch(
        f"electricity:{path}", constants.CACHE_TTL_LATEST_SECONDS, fetch
    )
    root = _parse_xml(text, "intertie_flows")
    body = _child(root, "IMODocBody")
    if body is None:
        raise UpstreamError("electricity:intertie_flows has no IMODocBody.")
    zones = []
    for zone in _children(body, "IntertieZone"):
        mean, count = _mean_flow(_child(zone, "Actuals"))
        zones.append(
            IntertieZone(
                zone=_text(zone, "IntertieZoneName") or "",
                schedules=_schedules(_child(zone, "Schedules")),
                mean_actual_flow_mw=mean,
                intervals_reported=count,
            )
        )
    totals = _child(body, "Totals")
    total_mean, _ = _mean_flow(_child(totals, "Actuals"))
    return IntertieFlows(
        date=_date_from_text(_text(body, "Date"), "intertie_flows"),
        zones=zones,
        total_schedules=_schedules(_child(totals, "Schedules")),
        total_mean_actual_flow_mw=total_mean,
        sign_convention="Positive actual flow is an export from Ontario; negative is an import.",
        created_at=_text(_child(root, "IMODocHeader"), "CreatedAt"),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.BASE_URL}/{path}",
            cached=was_cached,
            schema_name="electricity.IntertieFlows",
            freshness="updated through the day; hourly schedules, 5-minute actual flows",
            licence=_LICENCE,
            limits=_limits("Means are over the 5-minute intervals reported so far that day."),
        ),
    )
