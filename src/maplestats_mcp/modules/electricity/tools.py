"""MCP tools for Ontario electricity system data (IESO public reports)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.electricity import client
from maplestats_mcp.modules.electricity.schemas import (
    AdequacyOutlook,
    HoepHistory,
    HourlyDemand,
    IntertieFlows,
    PriceMarket,
    RealtimeDemand,
    SupplyByFuel,
    ZonalPrices,
)

Lang = Literal["en", "fr"]


@tool
async def electricity_ontario_get_hourly_demand(
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 48,
    lang: Lang = "en",
) -> HourlyDemand:
    """Ontario hourly electricity demand in MW, 2002 to the previous day.

    Returns hour-ending rows (Eastern Standard Time all year) with Market
    Demand (Ontario demand plus exports) and Ontario Demand, plus the peak
    hour and average over the whole matched range. One calendar year per call;
    with no dates, the latest `limit` hours of `year` (default the current
    year). Use electricity_ontario_get_realtime_demand for the current hour.
    Use for: Ontario electricity load, peak demand, daily or seasonal demand
    profile, demand history, how much power Ontario uses.
    Keywords: Ontario, IESO, electricity demand, hourly demand, peak demand,
    load, MW, market demand, Ontario demand, power grid, consumption.
    Mots-clés : Ontario, SIERE, demande d'électricité, demande horaire, pointe,
    charge, MW, demande du marché, réseau électrique, consommation.
    """
    return await client.get_hourly_demand(year, start_date, end_date, limit, lang=lang)


@tool
async def electricity_ontario_get_realtime_demand(
    date: str | None = None, hour: int | None = None, lang: Lang = "en"
) -> RealtimeDemand:
    """Ontario demand every 5 minutes for the latest delivery hour (or a past hour).

    Twelve intervals with Ontario Demand, total energy, load and losses in MW.
    Give both `date` (YYYY-MM-DD) and `hour` (1-24, hour ending, EST) for a
    past hour; IESO keeps about three months of them.
    Use for: right-now Ontario electricity demand, 5-minute load, real-time
    grid conditions in Ontario.
    Keywords: Ontario, IESO, real-time demand, 5-minute, current load, live,
    electricity, MW, dispatch, grid, now.
    Mots-clés : Ontario, SIERE, demande en temps réel, 5 minutes, charge
    actuelle, électricité, MW, réseau, maintenant, répartition.
    """
    return await client.get_realtime_demand(date, hour, lang=lang)


@tool
async def electricity_ontario_get_supply_by_fuel(
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 48,
    lang: Lang = "en",
) -> SupplyByFuel:
    """Ontario hourly generator output by fuel (nuclear, gas, hydro, wind, solar, biofuel), 2015 onward.

    Hour-ending rows in MW plus energy totals and generation shares over the
    whole matched range. Covers IESO-metered generators, not embedded
    distribution-connected solar. One calendar year per call; the current-year
    file ends about a day behind the clock and is about 6 MB.
    Use for: Ontario generation mix, nuclear or wind share, gas-fired output,
    supply by fuel type, clean electricity share.
    Keywords: Ontario, IESO, generation mix, supply by fuel, nuclear, gas,
    hydro, wind, solar, biofuel, output, MW, MWh, energy mix.
    Mots-clés : Ontario, SIERE, bouquet énergétique, production par
    combustible, nucléaire, gaz, hydroélectricité, éolien, solaire, MW, MWh.
    """
    return await client.get_supply_by_fuel(year, start_date, end_date, limit, lang=lang)


@tool
async def electricity_ontario_get_prices(
    market: PriceMarket = "day_ahead",
    date: str | None = None,
    hour: int | None = None,
    lang: Lang = "en",
) -> ZonalPrices:
    """Ontario Zonal Price (CAD/MWh): day-ahead hourly or real-time 5-minute.

    The Ontario Zonal Price replaced HOEP as Ontario's wholesale settlement
    price on 2025-05-01. `market="day_ahead"` returns 24 hourly prices for
    `date` (omit for the latest published day, tomorrow's appears about 12:30
    EST); `market="real_time"` returns 12 five-minute prices for one delivery
    hour (give both `date` and `hour` 1-24, or neither for the latest). Dated
    files are kept about three months. Older HOEP averages:
    electricity_ontario_get_hoep_history.
    Use for: Ontario wholesale electricity price, day-ahead price, spot price
    now, price spikes, congestion and loss components.
    Keywords: Ontario, IESO, electricity price, zonal price, OZP, day-ahead,
    real-time, LMP, CAD/MWh, wholesale, spot, market renewal, congestion.
    Mots-clés : Ontario, SIERE, prix de l'électricité, prix zonal, prévisionnel,
    temps réel, prix marginal, $/MWh, gros, marché au comptant, congestion.
    """
    return await client.get_zonal_prices(market, date, hour, lang=lang)


@tool
async def electricity_ontario_get_hoep_history(
    year: int | None = None, lang: Lang = "en"
) -> HoepHistory:
    """Monthly averages of the Hourly Ontario Energy Price (HOEP), 2002-2025.

    Arithmetic and demand-weighted averages, all hours and on-/off-peak, for one
    year (default 2025, which stops in April: HOEP ended 2025-05-01 and was
    replaced by the Ontario Zonal Price, a different series).
    Use for: historical Ontario electricity spot prices, HOEP by month, price
    trends before the 2025 market renewal.
    Keywords: Ontario, IESO, HOEP, hourly Ontario energy price, historical
    price, monthly average, on-peak, off-peak, weighted average, wholesale.
    Mots-clés : Ontario, SIERE, PHEO, prix horaire de l'énergie de l'Ontario,
    historique des prix, moyenne mensuelle, période de pointe, hors pointe.
    """
    return await client.get_hoep_history(year, lang=lang)


@tool
async def electricity_ontario_get_adequacy_outlook(
    date: str | None = None, lang: Lang = "en"
) -> AdequacyOutlook:
    """Ontario's hourly supply-adequacy outlook for one delivery day (today by default).

    Per hour: forecast supply, total requirements, excess capacity, forecast
    Ontario demand and peak demand, and internal-resource outages, in MW, with
    the tightest hour. Dates run from about three months back to about 34 days
    ahead; future days have many empty (null) series.
    Use for: will Ontario have enough power, reserve margin, forecast peak
    demand, supply outlook, generator outages.
    Keywords: Ontario, IESO, adequacy, outlook, reserve margin, excess
    capacity, forecast demand, supply, outages, reliability, MW.
    Mots-clés : Ontario, SIERE, suffisance, perspective, marge de réserve,
    capacité excédentaire, demande prévue, approvisionnement, pannes, fiabilité.
    """
    return await client.get_adequacy_outlook(date, lang=lang)


@tool
async def electricity_ontario_get_intertie_flows(
    date: str | None = None, lang: Lang = "en"
) -> IntertieFlows:
    """Ontario electricity imports and exports by intertie zone (Manitoba, Quebec, New York, ...).

    Hourly scheduled import and export MW per zone and in total, plus the mean
    of the 5-minute actual flows so far that day (positive = export from
    Ontario). Omit `date` for today; dated files are kept about three months.
    Use for: Ontario electricity trade, imports from Quebec, exports to the
    United States, interprovincial power flows.
    Keywords: Ontario, IESO, intertie, imports, exports, Quebec, Manitoba,
    New York, Michigan, Minnesota, flows, schedule, interprovincial, trade.
    Mots-clés : Ontario, SIERE, interconnexion, importations, exportations,
    Québec, Manitoba, New York, flux, échanges d'électricité, interprovincial.
    """
    return await client.get_intertie_flows(date, lang=lang)
