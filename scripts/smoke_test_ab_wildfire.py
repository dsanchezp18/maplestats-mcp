"""Live smoke test for the Alberta Wildfire module: every tool's client function."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maplestats_mcp.modules.ab_wildfire import client
from maplestats_mcp.modules.ab_wildfire.client import FireFilters
from maplestats_mcp.shared.errors import InvalidInput


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
    # Fire points: the year-to-date layer is never empty after January.
    fires = await _check("get_fires(current)", client.list_fires(limit=5))
    _require(fires.total_matches > 100, f"low fire count {fires.total_matches}")
    _require(len(fires.fires) == 5, "limit not honoured")
    _require(fires.provenance.as_of is not None, "as_of missing from layer metadata")
    first = fires.fires[0]
    _require(first.latitude is not None and first.fire_number is not None, "fire row incomplete")

    largest = await _check(
        "get_fires(largest, D+E)",
        client.list_fires("current", FireFilters(size_class="D,E"), sort_by="largest", limit=3),
    )
    areas = [f.area_ha or 0 for f in largest.fires]
    _require(areas == sorted(areas, reverse=True), "largest sort is not descending")
    _require(all(f.size_class in ("D", "E") for f in largest.fires), "size_class filter failed")

    lightning = await _check(
        "get_fires(lightning, Wildfire, dated)",
        client.list_fires(
            "current",
            FireFilters(
                cause="lightning",
                fire_type="wildfire",
                start_date="2026-06-01",
                end_date="2026-08-31",
            ),
            limit=5,
        ),
    )
    _require(all(f.cause == "Lightning" for f in lightning.fires), "cause filter failed")

    by_status = await _check(
        "get_fires(status changed in July)",
        client.list_fires(
            "current",
            FireFilters(
                start_date="2026-07-01", end_date="2026-07-31", date_basis="status_changed"
            ),
            limit=3,
        ),
    )
    _require(
        all(f.status_changed and f.status_changed.month == 7 for f in by_status.fires),
        "status_changed date filter failed",
    )

    near = await _check(
        "get_fires(near Fort McMurray 150 km)",
        client.list_fires(
            "current", FireFilters(), latitude=56.7267, longitude=-111.38, radius_km=150, limit=5
        ),
    )
    distances = [f.distance_km for f in near.fires]
    _require(
        all(d is not None and d <= 150 for d in distances) and distances == sorted(distances),  # type: ignore[type-var]
        "radius search not nearest first within radius",
    )

    active = await _check(
        "get_fires(active_only)", client.list_fires("current", FireFilters(active_only=True))
    )
    print(f"   active fires right now: {active.total_matches}")

    history = await _check(
        "get_fires(previous_5_years 2024)",
        client.list_fires("previous_5_years", FireFilters(fire_year=2024), limit=3),
    )
    _require(history.total_matches > 500, "low 2024 same-date count")
    ended = await _check(
        "get_fires(previous_5_years Assistance Ended)",
        client.list_fires("previous_5_years", FireFilters(status="assistance ended"), limit=3),
    )
    _require(ended.total_matches >= 250, "misspelled 'Assisstance Ended' rows not matched")
    _require(
        all(f.status == "Assistance Ended" for f in ended.fires), "status spelling not normalised"
    )

    for group_by in ("status", "cause", "size_class", "forest_area", "fire_type", "fire_year"):
        summary = await _check(
            f"summarize_fires({group_by})",
            client.summarize_fires("current", group_by),  # type: ignore[arg-type]
        )
        _require(summary.total_fires == fires.total_matches, f"{group_by} total differs from list")
    years = await _check(
        "summarize_fires(previous_5_years by year)",
        client.summarize_fires("previous_5_years", "fire_year"),
    )
    _require(len(years.groups) >= 5, "fewer than five years in the comparison set")
    statuses = await _check(
        "summarize_fires(previous_5_years by status)",
        client.summarize_fires("previous_5_years", "status"),
    )
    _require(all(g.key != "Assisstance Ended" for g in statuses.groups), "typo status not merged")

    stats = await _check("get_season_statistics", client.get_season_statistics())
    _require(stats.headline.year_to_date_wildfires is not None, "no year-to-date wildfire count")
    _require(len(stats.same_day_comparison) >= 5, "same-day comparison has fewer than 5 years")
    wildfires_2026 = await client.summarize_fires(
        "current",
        "fire_type",
        FireFilters(fire_type="Wildfire", fire_year=stats.same_day_comparison[-1].year),
    )
    print(
        f"   headline {stats.headline.year_to_date_wildfires} vs layer {wildfires_2026.total_fires} wildfires"
    )

    perimeters = await _check(
        "get_perimeters(extinguished)", client.get_perimeters("extinguished", limit=3)
    )
    _require(perimeters.total_matches > 0, "no extinguished perimeters")
    geometry = await _check(
        "get_perimeters(extinguished, geometry)",
        client.get_perimeters("extinguished", include_geometry=True, limit=1),
    )
    _require(
        geometry.perimeters[0].geometry is not None
        and geometry.perimeters[0].geometry.get("type") in ("Polygon", "MultiPolygon"),
        "perimeter geometry missing",
    )
    await _check(
        "get_perimeters(filtered)",
        client.get_perimeters("extinguished", size_class="D,E", forest_area="whitecourt", limit=3),
    )
    active_perimeters = await _check("get_perimeters(active)", client.get_perimeters("active"))
    print(f"   active perimeters right now: {active_perimeters.total_matches}")

    danger = await _check("get_fire_danger(Edmonton)", client.get_fire_danger(53.5461, -113.4938))
    _require(danger.danger_class is not None, "no danger class for Edmonton")
    outside = await _check("get_fire_danger(Vancouver)", client.get_fire_danger(49.28, -123.12))
    _require(outside.danger_class is None and outside.note, "Vancouver should be unrated")
    overview = await _check("summarize_fire_danger()", client.summarize_fire_danger())
    _require(overview.total_polygons > 700, "low rating polygon count")
    region = await _check(
        "summarize_fire_danger(bbox)", client.summarize_fire_danger([-118.0, 54.0, -116.0, 55.0])
    )
    _require(0 < region.total_polygons < overview.total_polygons, "bbox did not narrow the count")

    orders = await _check("get_fire_control_orders()", client.get_fire_control_orders())
    _require(orders.returned_count > 0, "no fire advisories or restrictions listed")
    print(f"   orders by type: {orders.counts_by_type}")
    banff = await _check(
        "get_fire_control_orders(Banff point)", client.get_fire_control_orders(51.18, -115.57)
    )
    _require(all(o.alert_type != "" for o in banff.orders), "empty alert type")
    await _check(
        "get_fire_control_orders(Fire Restriction, Park)",
        client.get_fire_control_orders(alert_type="fire restriction", name_contains="park"),
    )

    for label, bad in (
        ("bad date", client.list_fires("current", FireFilters(start_date="2026/06/01"))),
        ("bad size class", client.list_fires("current", FireFilters(size_class="Z"))),
        ("half a point", client.list_fires("current", FireFilters(), latitude=53.0)),
        ("bad alert type", client.get_fire_control_orders(alert_type="fire party")),
    ):
        try:
            await bad
        except InvalidInput:
            print(f"OK: {label} raises InvalidInput")
        else:
            print(f"FAIL: {label} did not raise")
            return 1

    print("AB WILDFIRE SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
