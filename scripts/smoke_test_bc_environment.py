"""Live smoke test for the BC Ministry of Environment monitoring tools.

Calls every bc_env_ tool against www.env.gov.bc.ca and the BC Geographic
Warehouse, including two archive reads by range request.

    uv run python scripts/smoke_test_bc_environment.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from maplestats_mcp.modules.bc_environment import tools


async def main() -> int:
    failures = 0

    async def step(label: str, call, check) -> None:
        nonlocal failures
        started = time.monotonic()
        try:
            result = await call
            message = check(result)
            print(f"ok   {label} ({time.monotonic() - started:.1f}s): {message}")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            failures += 1
            print(f"FAIL {label}: {type(exc).__name__}: {exc}")

    await step(
        "bc_env_list_air_stations",
        tools.bc_env_list_air_stations(parameter="PM25", limit=5),
        lambda r: (
            f"{r.total_matched} PM25 stations; first {r.stations[0].name} "
            f"{r.stations[0].units.get('PM25')}"
        ),
    )
    await step(
        "bc_env_get_air_station_data",
        tools.bc_env_get_air_station_data("Kamloops Federal Building", ["PM25", "O3"], limit=4),
        lambda r: (
            f"{r.total_matched} rows; {[(x.time_pst, x.parameter, x.value, x.unit) for x in r.readings[:2]]}"
        ),
    )
    await step(
        "bc_env_get_air_parameter_data",
        tools.bc_env_get_air_parameter_data("PM25", latest_only=True, limit=200),
        lambda r: (
            f"{r.total_matched} stations latest; {r.readings[0].station} "
            f"{r.readings[0].raw_value}/{r.readings[0].value} {r.readings[0].unit}"
        ),
    )
    await step(
        "bc_env_get_aqhi",
        tools.bc_env_get_aqhi("Kamloops", history_hours=3),
        lambda r: (
            f"{r.areas[0].area} {r.areas[0].aqhi} {r.areas[0].risk}; history "
            f"{[(h.time_pst, h.aqhi) for h in r.history]}"
        ),
    )
    await step(
        "bc_env_list_snow_stations",
        tools.bc_env_list_snow_stations(status="Active", limit=3),
        lambda r: f"{r.total_matched} active; {[s.station_id for s in r.stations]}",
    )
    await step(
        "bc_env_get_snow_station_data",
        tools.bc_env_get_snow_station_data("1C44P", limit=5),
        lambda r: (
            f"{r.total_matched} rows; {[(x.time_utc, x.variable, x.value, x.unit, x.grade) for x in r.readings[:2]]}"
        ),
    )
    await step(
        "bc_env_get_snow_readings current",
        tools.bc_env_get_snow_readings("SW", limit=3),
        lambda r: (
            f"{r.total_matched} rows; {[(x.time_utc, x.station_id, x.value) for x in r.readings]}"
        ),
    )
    await step(
        "bc_env_get_snow_readings archive",
        tools.bc_env_get_snow_readings(
            "SW", ["2F01AP"], start="2023-04-01", end="2023-04-01 06:00"
        ),
        lambda r: (
            f"{r.total_matched} rows from {r.file}; {[(x.time_utc, x.value) for x in r.readings[:3]]}"
        ),
    )
    await step(
        "bc_env_get_snow_readings daily archive",
        tools.bc_env_get_snow_readings("SW_DAILY", ["1A01P"], start="2010-04-01", end="2010-04-03"),
        lambda r: f"{r.total_matched} rows; {[(x.time_utc, x.value) for x in r.readings]}",
    )
    await step(
        "bc_env_get_snow_surveys",
        tools.bc_env_get_snow_surveys("1A01", season="archive", limit=3),
        lambda r: (
            f"{r.total_matched} surveys; oldest-in-page {r.surveys[-1].survey_date} "
            f"{r.surveys[0].course} {r.surveys[0].water_equivalent_mm}"
        ),
    )
    await step(
        "bc_env_list_wells",
        tools.bc_env_list_wells(status="Active", limit=3),
        lambda r: (
            f"{r.total_matched} active wells with data; "
            f"{[(w.well_id, w.city, w.region) for w in r.wells]}"
        ),
    )
    await step(
        "bc_env_get_well_levels",
        tools.bc_env_get_well_levels("OW002", series="hourly", limit=3),
        lambda r: (
            f"{r.total_matched} levels; {[(x.time, x.depth_to_water_m, x.approval) for x in r.levels]}"
        ),
    )
    await step(
        "bc_env_list_streamflow_gauges",
        tools.bc_env_list_streamflow_gauges(limit=3),
        lambda r: (
            f"{r.total_matched} stations; {[(s.station_id, s.parameters) for s in r.stations]}"
        ),
    )
    await step(
        "bc_env_get_streamflow current",
        tools.bc_env_get_streamflow("08HA0022", limit=3),
        lambda r: f"{r.total_matched} rows; {[(x.time_utc, x.value, x.grade) for x in r.readings]}",
    )
    await step(
        "bc_env_get_streamflow archive",
        tools.bc_env_get_streamflow(
            "08HA0022", start="2024-08-01", end="2024-08-01 05:00", limit=10
        ),
        lambda r: (
            f"{r.total_matched} rows from {r.files}; "
            f"{[(x.time_utc, x.value) for x in r.readings[:3]]} notes={r.notes}"
        ),
    )
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
