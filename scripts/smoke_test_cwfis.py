"""Live smoke test for the CWFIS module: every tool's client function."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maplestats_mcp.modules.cwfis import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise
    print(f"OK: {label} -> {type(result).__name__}")
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}")
        raise SystemExit(1)


async def main() -> int:
    hot = await _check("get_hotspots(current)", client.get_hotspots(limit=5))
    _require(hot.layer.endswith("hotspots_last24hrs"), "wrong layer for no-date query")
    _require(
        all(h.agency in client.c.CANADIAN_AGENCIES for h in hot.hotspots),
        "canada_only returned a non-Canadian agency",
    )

    arc = await _check(
        "get_hotspots(archive BC 2023-08-01)",
        client.get_hotspots(agency="BC", start_date="2023-08-01", end_date="2023-08-01", limit=5),
    )
    _require(arc.total_matched > 100, f"low BC archive count {arc.total_matched}")
    arc_two_days = await _check(
        "get_hotspots(archive BC 2023-08-01..02)",
        client.get_hotspots(agency="BC", start_date="2023-08-01", end_date="2023-08-02", limit=1),
    )
    top = await _check(
        "get_hotspots(sort frp)",
        client.get_hotspots(
            agency="BC", start_date="2023-08-01", end_date="2023-08-02", sort_by="frp", limit=3
        ),
    )
    # 2023 archive rows have no FRP: the sort keeps them (after any ranked
    # rows) instead of dropping them, so the totals agree.
    _require(top.total_matched == arc_two_days.total_matched, "frp sort changed the total")
    ranked = [h.frp_mw for h in top.hotspots if h.frp_mw is not None]
    _require(ranked == sorted(ranked, reverse=True), "frp ranking not descending")
    _require(
        all(h.frp_mw is None for h in top.hotspots[len(ranked) :]),
        "null-FRP rows came before ranked rows",
    )

    per = await _check("get_perimeters", client.get_perimeters(limit=3))
    _require(per.total_matched > 0, "no current perimeters")
    geo = await _check(
        "get_perimeters(geometry)", client.get_perimeters(include_geometry=True, limit=1)
    )
    _require(geo.perimeters[0].geometry is not None, "geometry missing")

    # The current-station layer was empty for a stretch of 2026-09-29 (2,112
    # stations that morning, numberMatched=0 that afternoon), so an empty
    # layer skips the station checks instead of failing the run.
    all_stations = await _check("get_stations(SK)", client.get_stations(province="SK", limit=3))
    if not all_stations.stations:
        print("OK (skip): the current-station layer is empty right now")
    else:
        _require(all(s.province == "SK" for s in all_stations.stations), "SK filter failed")
        first = all_stations.stations[0]
        near = await _check(
            "get_stations(near first SK station)",
            client.get_stations(
                latitude=first.latitude, longitude=first.longitude, radius_km=30, limit=5
            ),
        )
        _require(any(s.name == first.name for s in near.stations), "station not found nearby")
        _require(near.stations[0].distance_km is not None, "distance missing")
        await _check("get_stations(name)", client.get_stations(name=first.name.strip()[:5]))

    fc = await _check("get_forecast(KELOWNA)", client.get_forecast(station_name="kelowna"))
    _require(len(fc.forecasts) >= 2, "forecast has fewer than 2 days")

    danger = await _check(
        "get_fire_danger(Kelowna)", client.get_fire_danger(latitude=49.9, longitude=-119.4)
    )
    _require(danger.danger_class in client.c.DANGER_CLASSES.values(), "bad danger class")

    fires = await _check(
        "search_large_fires(BC 2023 >=50000)",
        client.search_large_fires(
            year_from=2023, year_to=2023, agency="BC", min_size_ha=50000, limit=3
        ),
    )
    _require(bool(fires.fires) and fires.fires[0].size_ha is not None, "no large BC 2023 fires")
    _require(fires.fires[0].cause is not None, "cause label missing")

    lst = await _check("list_situation_reports", client.list_situation_reports(limit=3))
    _require(lst.total_matched > 500, "situation report total too low")
    eos = await _check(
        "list_situation_reports(end_of_season)",
        client.list_situation_reports(report_type="end_of_season", limit=30),
    )
    _require(any(r.stats.area_to_date_ha for r in eos.reports), "no EOS numeric stats")

    latest = await _check("get_situation_report(latest)", client.get_situation_report())
    _require(bool(latest.sections), "latest report has no narrative")
    old = await _check(
        "get_situation_report(2010-07-14)",
        client.get_situation_report(date_on_or_before="2010-07-14", lang="fr"),
    )
    _require(old.stats.area_to_date_ha == 1637682, "2010-07-14 area total changed")
    await _check(
        "get_situation_report(end_of_season)",
        client.get_situation_report(report_type="end_of_season"),
    )

    for label, coro, exc_type in (
        ("bad bbox", client.get_hotspots(bbox=[1, 2, 3]), InvalidInput),
        ("half-open archive", client.get_hotspots(start_date="2023-01-01"), InvalidInput),
        ("pre-1998 report", client.get_situation_report(date_on_or_before="1990-01-01"), NotFound),
        ("ocean danger point", client.get_fire_danger(latitude=0.0, longitude=-30.0), NotFound),
    ):
        try:
            await coro
        except exc_type:
            print(f"OK: {label} raises {exc_type.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {label} raised {type(exc).__name__}: {exc}")
            return 1
        else:
            print(f"FAIL: {label} did not raise")
            return 1

    print("CWFIS SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
