"""Live smoke test for the cmhc module's client.py: calls every exported
function directly against the real CMHC Housing Market Information
Portal (HMIP, not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" - a clean mocked pytest run only proves the code
matches assumptions the tests share with it, not that those assumptions
are correct.

Usage:
    uv run python scripts/smoke_test_cmhc.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.cmhc import client
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

    categories = await client.list_categories()
    print(f"OK: list_categories -> {categories.total_count} categories")
    ok &= categories.total_count > 10
    ok &= any(c.category_level_1 == "Primary Rental Market" for c in categories.categories)

    provinces = await client.list_provinces()
    print(f"OK: list_provinces -> {len(provinces.provinces)} provinces/territories")
    ok &= len(provinces.provinces) >= 10

    ok &= await _check(
        "get_table_options(Primary Rental Market, Vacancy Rate (%))",
        client.get_table_options("Primary Rental Market", "Vacancy Rate (%)"),
    )
    options = await client.get_table_options("Primary Rental Market", "Vacancy Rate (%)")
    print(f"  {len(options.field_options)} field options")
    timeseries = next((o for o in options.field_options if o.row_field == "TIMESERIES"), None)
    province_breakdown = next((o for o in options.field_options if o.row_field == "21"), None)
    ok &= timeseries is not None

    ok &= await _check(
        "get_table_data(national historical vacancy rates)",
        client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            timeseries.column_field,
            timeseries.row_field,
        )
        if timeseries
        else asyncio.sleep(0),
    )
    if timeseries:
        national = await client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            timeseries.column_field,
            timeseries.row_field,
        )
        print(
            f"  table_id={national.table_id}, {len(national.rows)} rows, columns={national.columns}"
        )
        ok &= len(national.rows) > 10
        ok &= national.rows[0].period != ""
        print(f"  available_filters: {[(f.key, f.values) for f in national.available_filters]}")
        if national.available_filters:
            filt = national.available_filters[0]
            ok &= await _check(
                f"get_table_data(filters={{{filt.key!r}: {filt.values[0]!r}}})",
                client.get_table_data(
                    "Primary Rental Market",
                    "Vacancy Rate (%)",
                    timeseries.column_field,
                    timeseries.row_field,
                    filters={filt.key: filt.values[0]},
                ),
            )

    if province_breakdown:
        ok &= await _check(
            "get_table_data(current vacancy rates by province)",
            client.get_table_data(
                "Primary Rental Market",
                "Vacancy Rate (%)",
                province_breakdown.column_field,
                province_breakdown.row_field,
            ),
        )
        by_province = await client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            province_breakdown.column_field,
            province_breakdown.row_field,
        )
        print(f"  {len(by_province.rows)} province rows")
        # Confirms the suppressed-value quirk is handled, not necessarily
        # present in every pull (data changes over time).
        suppressed = [
            (row.period, col)
            for row in by_province.rows
            for col, cell in row.values.items()
            if cell.value is None and cell.flag
        ]
        print(f"  {len(suppressed)} suppressed/flagged-empty cells found")

    ok &= await _check(
        "get_table_data(French category names)",
        client.get_table_data(
            "Marché locatif primaire", "Taux d'inoccupation (%)", "2", "TIMESERIES", lang="fr"
        ),
    )

    # Error-path checks: must raise typed errors, not a raw httpx exception.
    try:
        await client.get_table_data("Not A Real Category", "Nonsense", "2", "TIMESERIES")
        print("FAIL: get_table_data(unknown category) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_table_data(unknown category) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_table_data(unknown category) raised {type(exc).__name__} "
            f"instead of NotFound: {exc}"
        )
        ok = False

    try:
        await client.list_categories(lang="de")
        print("FAIL: list_categories(bad lang) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: list_categories(bad lang) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: list_categories(bad lang) raised {type(exc).__name__} instead of InvalidInput: {exc}"
        )
        ok = False

    try:
        await client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            "2",
            "TIMESERIES",
            filters={"not_a_real_filter": "x"},
        )
        print("FAIL: get_table_data(unknown filter key) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: get_table_data(unknown filter key) raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_table_data(unknown filter key) raised {type(exc).__name__} "
            f"instead of InvalidInput: {exc}"
        )
        ok = False

    print()
    print("CMHC SMOKE TEST PASSED" if ok else "CMHC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
