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

from maplestats_mcp.modules.electricity import client
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
        len(fuel.rows) == 24 and any(t.fuel == "nuclear" for t in fuel.totals),
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
