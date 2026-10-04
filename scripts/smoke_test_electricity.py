"""Live smoke test for the electricity module: calls every client function
against the real IESO public reports (not mocks), per AGENTS.md's lesson
that a mocked pytest run only proves the code matches shared assumptions.

Usage:
    uv run python scripts/smoke_test_electricity.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

import httpx

from maplestats_mcp.modules.electricity import client, constants, quebec_flows
from maplestats_mcp.modules.electricity import quebec_client as client_qc
from maplestats_mcp.shared.errors import InvalidInput, NotFound


def _report(label: str, passed: bool, detail: str) -> bool:
    print(f"{'OK' if passed else 'FAIL'}: {label} -> {detail}")
    return passed


async def main() -> int:
    ok = True
    today = client.ieso_today()

    demand = await client.get_hourly_demand(limit=24)
    ok &= _report(
        "hourly_demand latest 24",
        len(demand.rows) == 24 and demand.peak_ontario_demand_mw is not None,
        f"{demand.rows_matched} hours in {demand.year}, last {demand.last_row_date}, "
        f"peak {demand.peak_ontario_demand_mw} MW",
    )
    past = await client.get_hourly_demand(start_date="2025-07-01", end_date="2025-07-02")
    ok &= _report(
        "hourly_demand 2025-07-01..02",
        past.rows_matched == 48 and past.year == 2025,
        f"{past.rows_matched} rows, peak {past.peak_ontario_demand_mw} MW",
    )

    realtime = await client.get_realtime_demand()
    ok &= _report(
        "realtime_demand latest",
        len(realtime.intervals) >= 1
        and all(i.ontario_demand_mw is not None for i in realtime.intervals),
        f"{realtime.delivery_date} HE{realtime.delivery_hour}, "
        f"{len(realtime.intervals)} intervals, avg {realtime.average_ontario_demand_mw} MW",
    )
    earlier = today - timedelta(days=2)
    past_rt = await client.get_realtime_demand(earlier.isoformat(), 14)
    ok &= _report(
        "realtime_demand dated hour",
        len(past_rt.intervals) == 12 and past_rt.delivery_hour == 14,
        f"{past_rt.delivery_date} HE{past_rt.delivery_hour}",
    )

    fuel = await client.get_supply_by_fuel(limit=24)
    ok &= _report(
        "supply_by_fuel latest 24",
        len(fuel.rows) == 24
        and any(t.fuel == "nuclear" for t in fuel.totals)
        # A fuel flagged with unavailable points still has its output.
        and all(
            row.output_mw.get(f) is not None
            for row in fuel.rows
            for f in row.unavailable_data_points
        ),
        f"{fuel.first_date}..{fuel.last_date}, "
        + ", ".join(f"{t.fuel} {t.share_percent}%" for t in fuel.totals[:4]),
    )

    day_ahead = await client.get_zonal_prices("day_ahead")
    ok &= _report(
        "prices day_ahead latest",
        len(day_ahead.points) == 24 and day_ahead.average_cad_per_mwh is not None,
        f"{day_ahead.delivery_date}, avg {day_ahead.average_cad_per_mwh} CAD/MWh",
    )
    dated_da = await client.get_zonal_prices("day_ahead", earlier.isoformat())
    ok &= _report(
        "prices day_ahead dated",
        len(dated_da.points) == 24 and dated_da.delivery_date == earlier,
        f"{dated_da.delivery_date}, max {dated_da.maximum_cad_per_mwh}",
    )
    live_rt = await client.get_zonal_prices("real_time")
    ok &= _report(
        "prices real_time latest",
        len(live_rt.points) == 12 and live_rt.delivery_hour is not None,
        f"{live_rt.delivery_date} HE{live_rt.delivery_hour}, avg {live_rt.average_cad_per_mwh}",
    )
    dated_rt = await client.get_zonal_prices("real_time", earlier.isoformat(), 5)
    ok &= _report(
        "prices real_time dated hour",
        len(dated_rt.points) == 12 and dated_rt.delivery_hour == 5,
        f"{dated_rt.delivery_date} HE{dated_rt.delivery_hour}",
    )

    hoep = await client.get_hoep_history(2024)
    ok &= _report(
        "hoep_history 2024",
        len(hoep.months) == 12 and hoep.months[0].arithmetic_average is not None,
        f"{hoep.months[0].month} avg {hoep.months[0].arithmetic_average}",
    )

    adequacy = await client.get_adequacy_outlook()
    ok &= _report(
        "adequacy today",
        len(adequacy.hours) == 24 and adequacy.delivery_date == today,
        f"min excess {adequacy.minimum_excess_capacity_mw} MW at HE{adequacy.minimum_excess_hour}, "
        f"peak forecast {adequacy.peak_forecast_demand_mw}",
    )
    future = await client.get_adequacy_outlook((today + timedelta(days=10)).isoformat())
    ok &= _report(
        "adequacy +10 days",
        len(future.hours) == 24,
        f"{future.delivery_date} supply HE1 {future.hours[0].total_supply_mw}",
    )

    interties = await client.get_intertie_flows()
    ok &= _report(
        "intertie_flows today",
        len(interties.zones) >= 5 and len(interties.total_schedules) >= 1,
        f"{len(interties.zones)} zones, mean net flow {interties.total_mean_actual_flow_mw} MW",
    )
    dated_if = await client.get_intertie_flows(earlier.isoformat())
    ok &= _report(
        "intertie_flows dated",
        len(dated_if.total_schedules) == 24,
        f"{dated_if.date}",
    )

    qc_demand = await client_qc.get_demand(limit=8)
    ok &= _report(
        "quebec demand recent",
        len(qc_demand.points) == 8 and qc_demand.latest_demand_mw is not None,
        f"latest {qc_demand.latest_timestamp} {qc_demand.latest_demand_mw} MW, "
        f"{qc_demand.rows_matched} rows",
    )
    qc_hist = await client_qc.get_demand("history", "2024-01-15", "2024-01-15", limit=24)
    ok &= _report(
        "quebec demand history",
        len(qc_hist.points) >= 23 and qc_hist.peak_demand_mw is not None,
        f"{len(qc_hist.points)} rows, peak {qc_hist.peak_demand_mw} MW on 2024-01-15",
    )
    qc_gen = await client_qc.get_generation(limit=12)
    ok &= _report(
        "quebec generation recent",
        len(qc_gen.points) >= 1 and qc_gen.points[-1].hydro_mw is not None,
        f"latest {qc_gen.points[-1].timestamp}, shares {qc_gen.average_share_percent}",
    )
    qc_gen_hist = await client_qc.get_generation("history", "2025-06-01", "2025-06-01", limit=24)
    ok &= _report(
        "quebec generation history",
        len(qc_gen_hist.points) >= 23,
        f"{len(qc_gen_hist.points)} rows",
    )
    qc_trade = await client_qc.get_trade(limit=6)
    ok &= _report(
        "quebec trade",
        len(qc_trade.points) == 6
        and "ontario" in qc_trade.points[-1].net_exports_mw
        # The latest hours used to be unpublished zero placeholders.
        and bool(qc_trade.points[-1].exports_total_mw),
        f"latest {qc_trade.points[-1].timestamp}, "
        f"exports {qc_trade.points[-1].exports_total_mw} MW",
    )
    # The feed keeps only the most recent days, so ask for the latest point's own date.
    latest_day = str(qc_trade.points[-1].timestamp)[:10]
    qc_trade_range = await client_qc.get_trade(latest_day, latest_day, limit=24)
    ok &= _report("quebec trade date range", len(qc_trade_range.points) >= 1, "ok")

    # Hydro-Quebec flows: an independent read of the same file checks the parse.
    facilities = await quebec_flows.list_facilities(limit=200)
    ok &= _report(
        "quebec flows facilities",
        facilities.total_facilities >= 80
        and facilities.total_matches == facilities.total_facilities,
        f"{facilities.total_facilities} sites",
    )
    async with httpx.AsyncClient(timeout=120) as web:
        raw = (await web.get(constants.QUEBEC_FLOWS_URL)).json()["Site"]
    lg1_raw = next(s for s in raw if s["identifiant"] == "3-130")
    lg1 = await quebec_flows.get_facility_flows("3-130")
    by_measure = {s.info.measure: s for s in lg1.series}
    raw_total = next(c for c in lg1_raw["Composition"] if c["type_point_donnee"] == "Débit total")
    last_stamp = max(raw_total["Donnees"])
    ok &= _report(
        "quebec flows La Grande-1 matches the raw file",
        lg1.facility.name == "La Grande-1"
        and len(by_measure["Débit total"].values) == len(raw_total["Donnees"])
        and by_measure["Débit total"].info.latest_value == float(raw_total["Donnees"][last_stamp]),
        f"{len(lg1.series)} series, latest total {by_measure['Débit total'].info.latest_value} m3/s",
    )
    totals = {p.time: p.value for p in by_measure["Débit total"].values}
    parts: dict = {}
    for series in lg1.series:
        if series.info.kind in ("turbined", "spilled"):
            for p in series.values:
                parts[p.time] = parts.get(p.time, 0.0) + p.value
    worst = max(abs(totals[t] - parts[t]) for t in totals if t in parts)
    ok &= _report(
        "quebec flows total = turbined + spilled at La Grande-1",
        worst < 0.5,
        f"max gap {worst:.3f}",
    )
    spilled = await quebec_flows.list_facilities(kind="spilled", region="Côte-Nord")
    ok &= _report(
        "quebec flows filters",
        spilled.total_matches > 0,
        f"{spilled.total_matches} Côte-Nord sites with spillway series",
    )
    by_name = await quebec_flows.get_facility_flows("beauharnois", kind="turbined")
    ok &= _report(
        "quebec flows by name and kind",
        len(by_name.series) == 1 and bool(by_name.series[0].values),
        by_name.series[0].info.measure if by_name.series else "none",
    )

    for label, coro in (
        ("missing dated file", client.get_zonal_prices("day_ahead", "2020-01-01")),
    ):
        try:
            await coro
            ok &= _report(label, False, "expected NotFound")
        except NotFound as exc:
            ok &= _report(label, True, f"NotFound: {exc}")
    try:
        await client.get_hourly_demand(start_date="2024-12-31", end_date="2025-01-02")
        ok &= _report("cross-year range", False, "expected InvalidInput")
    except InvalidInput as exc:
        ok &= _report("cross-year range", True, f"InvalidInput: {exc}")

    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
