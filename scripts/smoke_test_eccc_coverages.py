"""Live smoke test for modules/eccc/coverages against api.weather.gc.ca.

Calls every client function with realistic arguments across several
collection families and places (north, coasts, prairies), plus the error
cases, and prints what came back.

Usage:
    uv run python scripts/smoke_test_eccc_coverages.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from maplestats_mcp.modules.eccc.coverages import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound

CANDCS = "climate:candcsu6:projected:annual:absolute"


async def _ok(label: str, coro: Any) -> Any:
    try:
        result = await coro
    except Exception as exc:  # noqa: BLE001 - the smoke test reports every failure
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return None
    print(f"OK: {label}")
    return result


async def _fails(
    label: str, coro: Any, expected: type[Exception] | tuple[type[Exception], ...]
) -> bool:
    try:
        await coro
    except expected as exc:
        print(f"OK (refused): {label} -> {str(exc)[:140]}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {label} -> wrong error {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


def _summary(result: Any) -> str:
    first = result.rows[0]
    return (
        f"{result.total_rows} rows, {result.requests_made} req, "
        f"dist={result.point_distance_km} km; first: {first.time} {first.value:.2f} "
        f"{first.unit} {first.variable} {first.scenario} p{first.percentile} "
        f"{first.season or ''} {first.averaging_period or ''} @({first.lat}, {first.lon})"
    )


async def main() -> int:
    ok = True

    found = await _ok("search all", client.search_coverages())
    ok &= found is not None and found.total_count >= 45
    if found:
        print(f"  {found.total_count} climate coverage collections")
    ssp = await _ok("search scenario=SSP585", client.search_coverages(scenario="SSP585"))
    ok &= ssp is not None and all(c.family == "candcsu6" for c in ssp.collections)
    hdd = await _ok("search 'heating degree'", client.search_coverages("heating degree"))
    ok &= hdd is not None and any(c.family == "indices" for c in hdd.collections)
    yr = await _ok(
        "search year=2085 timeframe=projected frequency=monthly",
        client.search_coverages(year=2085, timeframe="projected", frequency="monthly"),
    )
    ok &= yr is not None and yr.total_count > 0

    desc = await _ok("describe CanDCS-U6", client.describe_coverage(CANDCS))
    ok &= desc is not None and desc.scenarios == ["SSP126", "SSP245", "SSP585"]
    if desc:
        print(f"  {[v.name for v in desc.variables]} {desc.time_range} {desc.percentiles}")
    ok &= (
        await _ok(
            "describe CanGRD trend",
            client.describe_coverage("climate:cangrd:historical:seasonal:trend"),
        )
        is not None
    )

    cases: list[tuple[str, str, dict[str, Any]]] = [
        ("Edmonton CanDCS-U6 2015-2100 all scenarios", CANDCS, {"lat": 53.55, "lon": -113.49}),
        (
            "Iqaluit CanDCS-U6 Precip SSP585 p90 2050-2060",
            CANDCS,
            {
                "lat": 63.75,
                "lon": -68.52,
                "variables": ["Precip"],
                "scenarios": ["SSP585"],
                "percentiles": [90],
                "start": "2050",
                "end": "2060",
            },
        ),
        (
            "Vancouver coast CanDCS-U6 seasonal JJA",
            "climate:candcsu6:projected:seasonal:absolute",
            {
                "lat": 49.28,
                "lon": -123.12,
                "seasons": ["JJA"],
                "scenarios": ["SSP245"],
                "start": "2040",
                "end": "2045",
            },
        ),
        (
            "Halifax CanDCS-U6 P30Y-Avg 2071-2100",
            "climate:candcsu6:projected:annual:P30Y-Avg",
            {"lat": 44.65, "lon": -63.57, "averaging_periods": ["2071-2100"]},
        ),
        (
            "Regina CMIP5 anomaly tas RCP8.5 p95",
            "climate:cmip5:projected:annual:anomaly",
            {
                "lat": 50.45,
                "lon": -104.61,
                "scenarios": ["RCP8.5"],
                "percentiles": [95],
                "start": "2080",
                "end": "2085",
            },
        ),
        (
            "Saskatoon indices hdd",
            "climate:indices:projected",
            {
                "lat": 52.13,
                "lon": -106.67,
                "variables": ["hdd", "tx30"],
                "scenarios": ["RCP4.5"],
                "start": "2050",
                "end": "2052",
            },
        ),
        (
            "Winnipeg SPEI-3 2050",
            "climate:spei-3:projected",
            {"lat": 49.9, "lon": -97.14, "scenarios": ["RCP8.5"], "start": "2050", "end": "2050"},
        ),
        (
            "Whitehorse DCS monthly tm",
            "climate:dcs:projected:monthly:absolute",
            {
                "lat": 60.72,
                "lon": -135.06,
                "variables": ["tm"],
                "scenarios": ["RCP2.6"],
                "start": "2030-01",
                "end": "2030-06",
            },
        ),
        (
            "Edmonton CanGRD annual anomaly 2010-2018",
            "climate:cangrd:historical:annual:anomaly",
            {"lat": 53.55, "lon": -113.49, "start": "2010", "end": "2018"},
        ),
        (
            "Calgary CanGRD seasonal trend",
            "climate:cangrd:historical:seasonal:trend",
            {"lat": 51.05, "lon": -114.07, "seasons": ["DJF"]},
        ),
        (
            "Prairie bbox CanDCS-U6 2050",
            CANDCS,
            {
                "bbox": [-106, 50, -104, 51],
                "scenarios": ["SSP245"],
                "start": "2050",
                "end": "2050",
                "max_rows": 50,
            },
        ),
    ]
    for label, cid, kwargs in cases:
        result = await _ok(label, client.get_coverage_data(cid, **kwargs))
        ok &= result is not None
        if result:
            print(f"  {_summary(result)}")
            for note in result.notes:
                print(f"  note: {note}")

    # The value layout inside a response differs by family (see client.py's
    # _ROWS_REVERSED). A point request reads a several-cell window, so its
    # value must equal a one-cell bbox request around the chosen cell centre,
    # which has no layout to get wrong.
    layout_checks: list[tuple[str, float, float, dict[str, Any]]] = [
        (CANDCS, 1 / 12, 0.0, {"scenarios": ["SSP585"], "start": "2060", "end": "2062"}),
        (
            "climate:dcs:projected:annual:absolute",
            1 / 12,
            0.0,
            {"scenarios": ["RCP8.5"], "start": "2060", "end": "2062"},
        ),
        (
            "climate:cmip5:projected:annual:absolute",
            1.0,
            0.0,
            {"scenarios": ["RCP8.5"], "start": "2060", "end": "2062"},
        ),
        (
            "climate:indices:projected",
            1 / 12,
            0.0,
            {"scenarios": ["RCP8.5"], "start": "2060", "end": "2062"},
        ),
        (
            "climate:spei-3:projected",
            1.0,
            0.0,
            {"scenarios": ["RCP8.5"], "start": "2060", "end": "2060"},
        ),
    ]
    for cid, res, _, kwargs in layout_checks:
        for lat, lon in ((58.77, -94.17), (46.81, -71.21)):
            point = await _ok(
                f"layout point {cid} ({lat}, {lon})",
                client.get_coverage_data(cid, lat=lat, lon=lon, **kwargs),
            )
            if point is None:
                ok = False
                continue
            cell = point.rows[0]
            pad = res * 0.4
            single = await _ok(
                "layout one-cell bbox",
                client.get_coverage_data(
                    cid,
                    bbox=[cell.lon - pad, cell.lat - pad, cell.lon + pad, cell.lat + pad],
                    **kwargs,
                ),
            )
            if single is None:
                ok = False
                continue
            same = [(r.time, round(r.value, 6)) for r in point.rows] == [
                (r.time, round(r.value, 6)) for r in single.rows
            ]
            print(f"  point vs one-cell: {'match' if same else 'MISMATCH'}")
            ok &= same
    # CanGRD's grid is projected, so a one-cell bbox is not reliable (its edge
    # cells come back null); its point value is checked against a value read
    # by hand from a single-cell request at (55, -105) for 1950: -2.39.
    cangrd = await _ok(
        "layout CanGRD point",
        client.get_coverage_data(
            "climate:cangrd:historical:annual:anomaly",
            lat=55.0,
            lon=-105.0,
            start="1950",
            end="1950",
        ),
    )
    ok &= cangrd is not None and abs(cangrd.rows[0].value - (-2.39)) < 1e-6
    if cangrd:
        print(f"  CanGRD (55, -105) 1950 = {cangrd.rows[0].value}")

    ok &= await _fails(
        "whole Canada 86 years",
        client.get_coverage_data(CANDCS, bbox=[-141, 41, -52, 83.5]),
        InvalidInput,
    )
    ok &= await _fails(
        "year outside extent",
        client.get_coverage_data(CANDCS, lat=53.5, lon=-113.5, start="1990", end="2000"),
        InvalidInput,
    )
    ok &= await _fails(
        "unknown scenario",
        client.get_coverage_data(CANDCS, lat=53.5, lon=-113.5, scenarios=["SSP999"]),
        InvalidInput,
    )
    ok &= await _fails(
        "unknown variable",
        client.get_coverage_data(CANDCS, lat=53.5, lon=-113.5, variables=["tas"]),
        InvalidInput,
    )
    ok &= await _fails(
        "point in the Pacific",
        client.get_coverage_data(CANDCS, lat=50.0, lon=-135.0, start="2050", end="2050"),
        (NotFound, InvalidInput),
    )
    ok &= await _fails(
        "unknown collection", client.describe_coverage("climate:nothing:here"), NotFound
    )
    ok &= await _fails(
        "feature collection id", client.describe_coverage("climate-daily"), InvalidInput
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
