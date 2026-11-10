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

from maplestats_mcp.modules.cmhc import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def _check_edmonton() -> bool:
    """Annual and year-to-date starts, the default dwelling type, and one column label
    across Average Rent ($) and % Change of Average Rent (issues from 2026-11-09)."""
    ok = True
    annual = await client.get_table_data(
        "New Housing Construction",
        "Starts (Actual)",
        "Dwelling Types",
        "Historical Time Periods",
        aggregate="annual",
        geography_type="CMA",
        geography_id="Edmonton",
    )
    ytd = await client.get_table_data(
        "New Housing Construction",
        "Starts (Actual)",
        "1",
        "TIMESERIES",
        aggregate="ytd",
        geography_type="CMA",
        geography_id="Edmonton",
    )
    print(
        f"OK: Edmonton starts, annual -> {annual.rows[-1].period}: {annual.rows[-1].values['All']}"
    )
    print(f"OK: Edmonton starts, ytd -> {ytd.rows[-1].period}: {ytd.rows[-1].values['All']}")
    ok &= bool(annual.aggregation_note and "MapleStats" in annual.aggregation_note)
    ok &= len(annual.rows) > 30 and all(len(r.period) == 4 for r in annual.rows)
    try:
        await client.get_table_data(
            "New Housing Construction",
            "Under Construction Inventory",
            "1",
            "TIMESERIES",
            aggregate="annual",
            geography_type="CMA",
            geography_id="Edmonton",
        )
        print("FAIL: an inventory (stock) was summed")
        ok = False
    except InvalidInput:
        print("OK: aggregate refuses a stock (Under Construction Inventory)")

    rent = await client.get_table_data(
        "Primary Rental Market",
        "Average Rent ($)",
        "Bedroom Type",
        "Survey Zones",
        geography_type="CMA",
        geography_id="Edmonton",
    )
    print(f"OK: Edmonton average rent -> applied {rent.applied_filters}: {rent.filter_notes}")
    ok &= rent.default_filters.get("dwelling_type_desc_en") == "Row / Apartment"
    change = await client.get_table_data(
        "Primary Rental Market",
        "% Change of Average Rent",
        "Bedroom Type",
        "TIMESERIES",
        geography_type="CMA",
        geography_id="Edmonton",
    )
    print(f"OK: % Change of Average Rent with 'Bedroom Type' -> column_field={change.column_field}")
    ok &= change.column_field == "2" and bool(change.rows)
    return ok


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
        # present in every pull (data change over time).
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

    # City level (2026-11-03): HMIP's metropolitan major areas, a CMA alias, a name for
    # the id and a field label, as the chat demo's model passed them for Toronto.
    metros = await client.list_metropolitan_areas()
    print(f"OK: list_metropolitan_areas -> {metros.total_count} areas")
    ok &= metros.total_count > 100
    toronto = await client.list_metropolitan_areas(name="Toronto", province_id="Ontario")
    print(f"  Toronto -> {[(a.id, a.name) for a in toronto.areas]}")
    ok &= any(a.id == "2270" for a in toronto.areas)
    rents = await client.get_table_data(
        "Primary Rental Market",
        "Average Rent ($)",
        "Bedroom Type",
        "TIMESERIES",
        geography_type="CMA",
        geography_id="Toronto",
    )
    latest = rents.rows[-1] if rents.rows else None
    two_bed = latest.values.get("2 Bedroom") if latest else None
    print(f"  {rents.geography_name} two-bedroom rent, {latest and latest.period}: {two_bed}")
    ok &= rents.geography_name == "Toronto" and two_bed is not None and two_bed.value is not None
    try:
        await client.list_categories(geography_type="CMA", geography_id="99999")
        print("FAIL: list_categories(unknown CMA id) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: list_categories(unknown CMA id) raised InvalidInput: {exc}")

    ok &= await _check_edmonton()

    print()
    print("CMHC SMOKE TEST PASSED" if ok else "CMHC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
