"""Live smoke test for the boc module's client.py: calls every exported
function directly against the real Bank of Canada Valet API (not mocks),
per AGENTS.md's "lesson from auditing the StatCan module" - a clean
mocked pytest run only proves the code matches assumptions the tests
share with it, not that those assumptions are correct.

Usage:
    uv run python scripts/smoke_test_boc.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.boc import client
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

    series_list = await client.list_series()
    print(f"OK: list_series -> {series_list.total_count} series")
    ok &= series_list.total_count > 1000

    group_list = await client.list_groups()
    print(f"OK: list_groups -> {group_list.total_count} groups")
    ok &= group_list.total_count > 100

    search_result = await client.search_series("exchange rate", limit=5)
    print(f"OK: search_series -> {len(search_result.series)} matches")
    print("  sample:", search_result.series[0] if search_result.series else None)
    ok &= len(search_result.series) > 0

    group_search_result = await client.search_groups("exchange rate", limit=5)
    print(f"OK: search_groups -> {len(group_search_result.groups)} matches")
    ok &= len(group_search_result.groups) > 0

    ok &= await _check("get_series(FXUSDCAD)", client.get_series("FXUSDCAD"))
    fx_detail = await client.get_series("FXUSDCAD")
    print("  ", fx_detail.model_dump())

    ok &= await _check("get_group(FX_RATES_DAILY)", client.get_group("FX_RATES_DAILY"))
    fx_group = await client.get_group("FX_RATES_DAILY")
    print(f"  group has {len(fx_group.series)} member series")

    ok &= await _check(
        "get_observations single series recent=5",
        client.get_observations(["FXUSDCAD"], recent=5),
    )
    single_obs = await client.get_observations(["FXUSDCAD"], recent=5)
    print(f"  {len(single_obs.observations)} rows, series={list(single_obs.series)}")
    print("  sample row:", single_obs.observations[0].model_dump())

    ok &= await _check(
        "get_observations multi-series comma-joined + date range",
        client.get_observations(
            ["FXUSDCAD", "FXEURCAD"], start_date="2024-01-01", end_date="2024-01-10"
        ),
    )
    multi_obs = await client.get_observations(
        ["FXUSDCAD", "FXEURCAD"], start_date="2024-01-01", end_date="2024-01-10"
    )
    merged = [o for o in multi_obs.observations if len(o.values) == 2]
    print(f"  {len(multi_obs.observations)} rows, {len(merged)} with both series merged")
    ok &= len(merged) > 0

    ok &= await _check(
        "get_observations mixed-frequency (daily FX + monthly CPI)",
        client.get_observations(["FXUSDCAD", "V41690973"], recent=5),
    )
    mixed_obs = await client.get_observations(["FXUSDCAD", "V41690973"], recent=5)
    single_key_rows = [o for o in mixed_obs.observations if len(o.values) == 1]
    print(f"  {len(mixed_obs.observations)} rows, {len(single_key_rows)} single-series (unmerged)")
    ok &= len(single_key_rows) > 0  # confirms the unmerged-row quirk documented in client.py

    ok &= await _check(
        "get_observations recent_weeks",
        client.get_observations(["FXUSDCAD"], recent_weeks=1),
    )
    ok &= await _check(
        "get_observations recent_months",
        client.get_observations(["V39079"], recent_months=1),
    )
    ok &= await _check(
        "get_observations recent_years",
        client.get_observations(["CPI_TRIM"], recent_years=1),
    )

    ok &= await _check(
        "get_group_observations(FX_RATES_DAILY, recent=1)",
        client.get_group_observations("FX_RATES_DAILY", recent=1),
    )
    group_obs = await client.get_group_observations("FX_RATES_DAILY", recent=1)
    print(f"  group={group_obs.group.model_dump()}")
    ok &= group_obs.group.name == "FX_RATES_DAILY"

    # Error-path checks: must raise typed errors, not a raw httpx exception.
    try:
        await client.get_series("NOTAREALSERIES999")
        print("FAIL: get_series(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_series(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_series(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_group("NOTAREALGROUP999")
        print("FAIL: get_group(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_group(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_group(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_observations(["FXUSDCAD"], start_date="2024-05-01", end_date="2024-01-01")
        print("FAIL: bad date range did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: bad date range raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: bad date range raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    try:
        await client.get_observations(["FXUSDCAD"], start_date="2024-01-01", recent=5)
        print("FAIL: mixed recent+range did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: mixed recent+range raised InvalidInput (caught client-side): {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: mixed recent+range raised {type(exc).__name__} instead of InvalidInput: {exc}"
        )
        ok = False

    print()
    print("BOC SMOKE TEST PASSED" if ok else "BOC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
