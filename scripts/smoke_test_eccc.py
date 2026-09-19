"""Live smoke test for the eccc module's client.py: calls every exported
function directly against the real MSC GeoMet-OGC-API (not mocks), per
AGENTS.md's "lesson from auditing the StatCan module" - a clean mocked
pytest run only proves the code matches assumptions the tests share
with it, not that those assumptions are correct.

Usage:
    uv run python scripts/smoke_test_eccc.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.eccc import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ok = True

    collections = await client.list_collections()
    print(f"OK: list_collections -> {collections.total_count} collections")
    ok &= collections.total_count > 50

    search = await client.search_collections("hydrometric", limit=10)
    print(f"OK: search_collections('hydrometric') -> {len(search.collections)} matches")
    ok &= any(c.id == "hydrometric-realtime" for c in search.collections)

    ok &= await _check("get_collection(weather-alerts)", client.get_collection("weather-alerts"))
    alerts_detail = await client.get_collection("weather-alerts")
    print(f"  bbox={alerts_detail.bbox}, {len(alerts_detail.queryables)} queryables")
    ok &= any(q.name == "province" for q in alerts_detail.queryables)

    ok &= await _check(
        "get_collection(hydrometric-realtime)", client.get_collection("hydrometric-realtime")
    )

    ok &= await _check(
        "query_items(weather-alerts, no filters)",
        client.query_items("weather-alerts", limit=5),
    )
    alerts_items = await client.query_items("weather-alerts", limit=5)
    print(f"  {alerts_items.number_returned} of {alerts_items.number_matched} alerts")
    if alerts_items.items:
        print("  sample properties keys:", sorted(alerts_items.items[0].properties)[:8])

    ok &= await _check(
        "query_items(weather-alerts, filters={province: ON})",
        client.query_items("weather-alerts", filters={"province": "ON"}, limit=5),
    )

    ok &= await _check(
        "query_items(hydrometric-realtime, filters={STATION_NUMBER}, datetime_filter)",
        client.query_items(
            "hydrometric-realtime",
            filters={"STATION_NUMBER": "05BL023"},
            datetime_filter="2026-08-01T00:00:00Z/..",
            limit=5,
        ),
    )
    hydro_items = await client.query_items(
        "hydrometric-realtime", filters={"STATION_NUMBER": "05BL023"}, limit=5
    )
    print(f"  hydrometric: {hydro_items.number_matched} rows matched for station 05BL023")
    ok &= hydro_items.number_matched > 0

    ok &= await _check(
        "query_items(climate-stations, bbox around Ottawa)",
        client.query_items("climate-stations", bbox=[-76.5, 45.0, -75.0, 45.7], limit=5),
    )

    ok &= await _check(
        "query_items(aqhi-observations-realtime, fields subset)",
        client.query_items(
            "aqhi-observations-realtime", fields=["location_name_en", "aqhi"], limit=3
        ),
    )
    aqhi_items = await client.query_items(
        "aqhi-observations-realtime", fields=["location_name_en", "aqhi"], limit=3
    )
    if aqhi_items.items:
        print("  aqhi sample properties:", aqhi_items.items[0].properties)

    # Error-path checks: must raise typed errors, not a raw httpx exception.
    try:
        await client.get_collection("not-a-real-collection-xyz")
        print("FAIL: get_collection(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_collection(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_collection(unknown) raised {type(exc).__name__} instead of NotFound: {exc}"
        )
        ok = False

    try:
        await client.query_items("weather-alerts", filters={"not_a_real_property": "xyz"})
        print("FAIL: query_items(unknown filter key) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: query_items(unknown filter key) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: query_items(unknown filter key) raised {type(exc).__name__} "
            f"instead of InvalidInput: {exc}"
        )
        ok = False

    try:
        await client.query_items("weather-alerts", datetime_filter="2026-09-19")
        print("FAIL: query_items(weather-alerts, datetime_filter) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: query_items(weather-alerts, datetime_filter) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: query_items(weather-alerts, datetime_filter) raised "
            f"{type(exc).__name__} instead of InvalidInput: {exc}"
        )
        ok = False

    try:
        await client.query_items("weather-alerts", limit=5000)
        print("FAIL: query_items(limit over cap) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: query_items(limit over cap) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: query_items(limit over cap) raised {type(exc).__name__} "
            f"instead of InvalidInput: {exc}"
        )
        ok = False

    print()
    print("ECCC SMOKE TEST PASSED" if ok else "ECCC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
