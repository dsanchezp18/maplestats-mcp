"""Tests for electricity/client.py, shaped around file structures and quirks
confirmed live 2026-09-29 (see the client module docstring).
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.electricity import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

NS = 'xmlns="http://www.ieso.ca/schema"'
BASE = constants.BASE_URL

_DEMAND_CSV = """\\\\Hourly Demand Report,,,
\\\\Created at 2026-09-28 07:30:15,,,
\\\\For 2026,,,
Date,Hour,Market Demand,Ontario Demand
2026-09-26,23,17000,15000
2026-09-27,1,16500,14000
2026-09-27,2,16000,
2026-09-28,1,16286,13844
"""

_FUEL_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocBody><DeliveryYear>2026</DeliveryYear>
<DailyData><Day>2026-01-01</Day>
<HourlyData><Hour>1</Hour>
<FuelTotal><Fuel>NUCLEAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality>
<Output>9000</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>GAS</Fuel><EnergyValue><OutputQuality>-1</OutputQuality>
<Output>1000</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>CONTROL ACTIONS</Fuel><EnergyValue><OutputQuality>0</OutputQuality>
<Output>50</Output></EnergyValue></FuelTotal>
</HourlyData>
<HourlyData><Hour>2</Hour>
<FuelTotal><Fuel>NUCLEAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality>
<Output>9000</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>GAS</Fuel><EnergyValue><OutputQuality>-3</OutputQuality></EnergyValue></FuelTotal>
</HourlyData></DailyData></DocBody></Document>"""

_DA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocHeader><CreatedAt>2026-09-28T12:31:16</CreatedAt></DocHeader>
<DocBody><DeliveryDate>2026-09-29</DeliveryDate>
<HourlyPriceComponents><PricingHour>1</PricingHour><ZonalPrice>39.09</ZonalPrice>
<LossPriceCapped>0.26</LossPriceCapped><CongestionPriceCapped>0</CongestionPriceCapped>
<Flag>DSO-RD</Flag></HourlyPriceComponents>
<HourlyPriceComponents><PricingHour>2</PricingHour><ZonalPrice>41.11</ZonalPrice>
<LossPriceCapped>0.34</LossPriceCapped><CongestionPriceCapped>0</CongestionPriceCapped>
<Flag>DSO-RD</Flag></HourlyPriceComponents>
</DocBody></Document>"""

_RT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocBody><DeliveryDate>2026-09-29</DeliveryDate><DeliveryHour>2</DeliveryHour>
<ZonalPrice><Interval>1</Interval><Flag>DSO-RD</Flag><LmpCap>46.65</LmpCap>
<LossPriceCap>0.63</LossPriceCap><CongPriceCap>0.00</CongPriceCap></ZonalPrice>
<ZonalPrice><Interval>2</Interval><Flag>DSO-RD</Flag><LmpCap>54.43</LmpCap>
<LossPriceCap>0.73</LossPriceCap><CongPriceCap>0.00</CongPriceCap></ZonalPrice>
</DocBody></Document>"""

_TOTALS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocBody><DeliveryDate>2026-09-29</DeliveryDate><DeliveryHour>2</DeliveryHour>
<Energies><IntervalEnergy><Interval>1</Interval>
<MQ><MarketQuantity>Total Energy</MarketQuantity><EnergyMW>16232</EnergyMW></MQ>
<MQ><MarketQuantity>ONTARIO DEMAND</MarketQuantity><EnergyMW>13930.8</EnergyMW></MQ>
<Flag>DSO-RD</Flag></IntervalEnergy>
<IntervalEnergy><Interval>2</Interval>
<MQ><MarketQuantity>ONTARIO DEMAND</MarketQuantity><EnergyMW>14206.6</EnergyMW></MQ>
<Flag>DSO-RD</Flag></IntervalEnergy></Energies></DocBody></Document>"""

_ADEQUACY_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocHeader><CreatedAt>2026-09-28T15:27:53</CreatedAt></DocHeader>
<DocBody><DeliveryDate>2026-09-30</DeliveryDate>
<ForecastSupply>
<TotalSupplies>
<Supply><DeliveryHour>1</DeliveryHour><EnergyMW>22000</EnergyMW></Supply>
<Supply><DeliveryHour>2</DeliveryHour><EnergyMW>21000</EnergyMW></Supply></TotalSupplies>
<InternalResources><TotalInternalResources><Outages>
<Outage><DeliveryHour>1</DeliveryHour><EnergyMW>14000</EnergyMW></Outage>
<Outage><DeliveryHour>2</DeliveryHour></Outage></Outages></TotalInternalResources>
</InternalResources></ForecastSupply>
<ForecastDemand>
<OntarioDemand>
<ForecastOntDemand>
<Demand><DeliveryHour>1</DeliveryHour><EnergyMW>14143</EnergyMW></Demand>
<Demand><DeliveryHour>2</DeliveryHour></Demand></ForecastOntDemand>
<PeakDemand><Demand><DeliveryHour>1</DeliveryHour><EnergyMW>14201</EnergyMW></Demand>
</PeakDemand></OntarioDemand>
<TotalRequirements>
<Requirement><DeliveryHour>1</DeliveryHour><EnergyMW>15201</EnergyMW></Requirement>
<Requirement><DeliveryHour>2</DeliveryHour><EnergyMW>18000</EnergyMW></Requirement>
</TotalRequirements>
<ExcessCapacities>
<Capacity><DeliveryHour>1</DeliveryHour><EnergyMW>6799</EnergyMW></Capacity>
<Capacity><DeliveryHour>2</DeliveryHour><EnergyMW>3000</EnergyMW></Capacity>
</ExcessCapacities></ForecastDemand></DocBody></Document>"""

_INTERTIE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<IMODocument {NS}><IMODocHeader><CreatedAt>2026-09-29T01:30:30</CreatedAt></IMODocHeader>
<IMODocBody><Date>2026-09-29</Date>
<IntertieZone><IntertieZoneName>MANITOBA</IntertieZoneName>
<Schedules><Schedule><Hour>1</Hour><Import>88</Import><Export>0</Export></Schedule></Schedules>
<Actuals><Actual><Hour>1</Hour><Interval>1</Interval><Flow>-80</Flow></Actual>
<Actual><Hour>1</Hour><Interval>2</Interval><Flow>-60</Flow></Actual></Actuals>
</IntertieZone>
<Totals><Schedules><Schedule><Hour>1</Hour><Import>97</Import><Export>2170</Export></Schedule>
</Schedules><Actuals><Actual><Hour>1</Hour><Interval>1</Interval><Flow>1945.5</Flow></Actual>
</Actuals></Totals></IMODocBody></IMODocument>"""

_HOEP_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document {NS}><DocBody><ReportYear>2024</ReportYear>
<HOEP><Month>January</Month><ArithmeticAve>42.27</ArithmeticAve><WeightedAve>43.0</WeightedAve>
<ArithmeticOnPeakAve>50.0</ArithmeticOnPeakAve><ArithmeticOffPeakAve>35.0</ArithmeticOffPeakAve>
<WeightedOnPeakAve>51.0</WeightedOnPeakAve><WeightedOffPeakAve>36.0</WeightedOffPeakAve></HOEP>
</DocBody></Document>"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_parse_demand_csv_skips_comments_and_blank_cells():
    rows = client.parse_demand_csv(_DEMAND_CSV)
    assert len(rows) == 4
    assert rows[2].ontario_demand_mw is None
    assert rows[2].market_demand_mw == 16000


def test_parse_demand_csv_wrong_columns_raises():
    with pytest.raises(UpstreamError):
        client.parse_demand_csv("Date,Hour\n2026-01-01,1\n")


async def test_hourly_demand_range_and_peak(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/Demand/PUB_Demand_2026.csv", text=_DEMAND_CSV)
    result = await client.get_hourly_demand(start_date="2026-09-27", end_date="2026-09-28")
    assert result.rows_matched == 3
    assert result.peak_ontario_demand_mw == 14000
    assert result.peak_hour_ending == 1
    # The blank Ontario Demand cell is skipped: (14000 + 13844) / 2.
    assert result.average_ontario_demand_mw == 13922.0
    assert result.last_row_date == date(2026, 9, 28)


async def test_hourly_demand_default_returns_latest_rows(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/Demand/PUB_Demand_2026.csv", text=_DEMAND_CSV)
    result = await client.get_hourly_demand(year=2026, limit=2)
    assert [r.hour_ending for r in result.rows] == [2, 1]
    assert result.rows_matched == 4


async def test_hourly_demand_rejects_cross_year_and_bad_limit():
    with pytest.raises(InvalidInput):
        await client.get_hourly_demand(start_date="2025-12-31", end_date="2026-01-01")
    with pytest.raises(InvalidInput):
        await client.get_hourly_demand(limit=0)
    with pytest.raises(InvalidInput):
        await client.get_hourly_demand(year=1990)
    with pytest.raises(InvalidInput):
        await client.get_hourly_demand(start_date="yesterday")


async def test_realtime_demand_latest(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/RealtimeTotals/PUB_RealtimeTotals.xml", text=_TOTALS_XML)
    result = await client.get_realtime_demand()
    assert result.delivery_hour == 2
    assert [i.minute_ending for i in result.intervals] == [5, 10]
    assert result.intervals[0].total_energy_mw == 16232
    assert result.intervals[1].total_energy_mw is None
    assert result.average_ontario_demand_mw == 14068.7


async def test_realtime_demand_dated_file_and_pair_rule(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/RealtimeTotals/PUB_RealtimeTotals_2026092702.xml", text=_TOTALS_XML
    )
    result = await client.get_realtime_demand("2026-09-27", 2)
    assert result.delivery_hour == 2
    with pytest.raises(InvalidInput):
        await client.get_realtime_demand("2026-09-27")
    with pytest.raises(InvalidInput):
        await client.get_realtime_demand("2026-09-27", 25)


def test_parse_fuel_xml_flags_missing_data():
    rows = client.parse_fuel_xml(_FUEL_XML)
    assert len(rows) == 2
    assert rows[0].output_mw["control_actions"] == 50
    # Hour 1: gas has an Output with quality -1 (as live: gas 3247 MW at -1),
    # which is a partial report, not a missing value.
    assert rows[0].output_mw["gas"] == 1000
    assert rows[0].fuels_without_output == []
    assert rows[0].unavailable_data_points == {"gas": 1}
    # Hour 2: gas has no Output element at all (confirmed live for 9 fuel-hours).
    assert rows[1].output_mw["gas"] is None
    assert rows[1].fuels_without_output == ["gas"]
    assert rows[1].unavailable_data_points == {}


async def test_supply_by_fuel_totals_exclude_control_actions_from_shares(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/GenOutputbyFuelHourly/PUB_GenOutputbyFuelHourly_2026.xml", text=_FUEL_XML
    )
    result = await client.get_supply_by_fuel(year=2026)
    totals = {t.fuel: t for t in result.totals}
    assert totals["nuclear"].energy_mwh == 18000
    assert totals["nuclear"].share_percent == round(100 * 18000 / 19000, 2)
    assert totals["control_actions"].share_percent is None
    assert totals["gas"].hours_without_output == 1
    assert totals["gas"].hours_with_unavailable_points == 1
    assert result.first_date == result.last_date == date(2026, 1, 1)


async def test_day_ahead_prices_latest(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/DAHourlyOntarioZonalPrice/PUB_DAHourlyOntarioZonalPrice.xml", text=_DA_XML
    )
    result = await client.get_zonal_prices("day_ahead")
    assert result.delivery_hour is None
    assert [p.price_cad_per_mwh for p in result.points] == [39.09, 41.11]
    assert result.average_cad_per_mwh == 40.1
    assert result.maximum_cad_per_mwh == 41.11


async def test_real_time_prices_dated_hour(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/RealtimeOntarioZonalPrice/PUB_RealtimeOntarioZonalPrice_2026092902.xml",
        text=_RT_XML,
    )
    result = await client.get_zonal_prices("real_time", "2026-09-29", 2)
    assert result.delivery_hour == 2
    assert result.points[1].price_cad_per_mwh == 54.43
    assert result.points[1].congestion_component == 0


async def test_prices_input_rules():
    with pytest.raises(InvalidInput):
        await client.get_zonal_prices("day_ahead", hour=3)
    with pytest.raises(InvalidInput):
        await client.get_zonal_prices("real_time", "2026-09-29")
    with pytest.raises(InvalidInput):
        await client.get_zonal_prices("hourly")  # type: ignore[arg-type]


async def test_missing_dated_file_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/DAHourlyOntarioZonalPrice/PUB_DAHourlyOntarioZonalPrice_20200101.xml",
        status_code=404,
        text="<html><h1>Not Found</h1></html>",
    )
    with pytest.raises(NotFound):
        await client.get_zonal_prices("day_ahead", "2020-01-01")


async def test_malformed_xml_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/DAHourlyOntarioZonalPrice/PUB_DAHourlyOntarioZonalPrice.xml",
        text="<html><body>maintenance",
    )
    with pytest.raises(UpstreamError):
        await client.get_zonal_prices("day_ahead")


async def test_adequacy_outlook_handles_empty_series(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/Adequacy3/PUB_Adequacy3_20260930.xml", text=_ADEQUACY_XML)
    result = await client.get_adequacy_outlook("2026-09-30")
    assert result.delivery_date == date(2026, 9, 30)
    assert result.hours[0].forecast_ontario_demand_mw == 14143
    assert result.hours[0].peak_ontario_demand_mw == 14201
    # Elements present without a value (future hours) come back as null, not zero.
    assert result.hours[1].forecast_ontario_demand_mw is None
    assert result.hours[1].internal_resource_outages_mw is None
    assert result.minimum_excess_capacity_mw == 3000
    assert result.minimum_excess_hour == 2
    assert result.peak_forecast_demand_mw == 14143


async def test_intertie_flows(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/IntertieScheduleFlow/PUB_IntertieScheduleFlow.xml", text=_INTERTIE_XML
    )
    result = await client.get_intertie_flows()
    assert result.zones[0].zone == "MANITOBA"
    assert result.zones[0].mean_actual_flow_mw == -70.0
    assert result.zones[0].intervals_reported == 2
    assert result.total_schedules[0].export_mw == 2170
    assert result.total_mean_actual_flow_mw == 1945.5


async def test_hoep_history(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/PriceHOEPAverage/PUB_PriceHOEPAverage_2024.xml", text=_HOEP_XML
    )
    result = await client.get_hoep_history(2024)
    assert result.months[0].month == "January"
    assert result.months[0].on_peak_weighted == 51.0
    with pytest.raises(InvalidInput):
        await client.get_hoep_history(2026)


async def test_french_notes_provenance_and_errors(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/PriceHOEPAverage/PUB_PriceHOEPAverage_2024.xml", text=_HOEP_XML
    )
    hoep = await client.get_hoep_history(2024, lang="fr")
    assert hoep.note.startswith("Prix horaire de l'énergie en Ontario (PHEO)")
    assert hoep.provenance.freshness == (
        "série close ; la dernière année, 2025, est partielle (jusqu'en avril)"
    )
    assert (hoep.provenance.limits or "").startswith("Les fichiers de la SIERE n'existent")
    assert "Société indépendante d'exploitation" in (hoep.provenance.licence or "")
    httpx_mock.add_response(
        url=f"{BASE}/IntertieScheduleFlow/PUB_IntertieScheduleFlow.xml", text=_INTERTIE_XML
    )
    flows = await client.get_intertie_flows(lang="fr")
    assert flows.sign_convention.startswith("Un flux réel positif est une exportation")
    with pytest.raises(InvalidInput, match="^Entrée invalide : l'année du PHEO"):
        await client.get_hoep_history(2026, lang="fr")
    with pytest.raises(InvalidInput, match="une seule année par appel"):
        await client.get_hourly_demand(start_date="2025-12-31", end_date="2026-01-01", lang="fr")
