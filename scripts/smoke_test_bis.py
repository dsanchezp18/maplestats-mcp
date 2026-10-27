"""Live smoke test for the bis module: calls the real BIS statistics API (not
mocks) for every client function and every tool, per AGENTS.md's "lesson
from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_bis.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.bis import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _expect_error(label: str, coro, exc_type: type[Exception]) -> bool:
    try:
        await coro
    except exc_type as exc:
        print(f"OK: {label} -> {type(exc).__name__}: {str(exc)[:120]}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


async def main() -> bool:
    ok = True

    # 29 dataflows (28 datasets and the release calendar) on 2026-10-26.
    datasets = await client.list_datasets()
    ids = [d.id for d in datasets.datasets]
    print(f"OK: list_datasets -> {len(ids)} datasets")
    ok &= len(ids) >= 25 and {"WS_DSR", "WS_CBPOL", "WS_TC", "WS_SPP"} <= set(ids)
    missing_notes = [i for i in ids if i not in constants.DATASET_NOTES]
    if missing_notes:
        print(f"FAIL: datasets without a note in constants.DATASET_NOTES: {missing_notes}")
        ok = False

    for dataset in ("WS_DSR", "WS_TC", "WS_LBS_D_PUB", "WS_CPMI_SYSTEMS"):
        structure = await client.describe_dataset(dataset, lang="fr")
        print(f"OK: describe {dataset} -> {structure.key_template} e.g. {structure.example_key}")
        ok &= all(d.codes for d in structure.dimensions)

    dsr = await client.get_series("WS_DSR", "Q.CA+US.H", start_period="2024-Q1")
    print("OK: DSR ->", [(s.key, s.unit, s.latest_period, s.latest_value) for s in dsr.series])
    ok &= len(dsr.series) == 2 and dsr.series[0].unit == "Per cent"

    credit = await client.get_series("WS_TC", "Q.CA.*.A.M.770.A", last_n=2)
    print("OK: total credit ->", [(s.key, s.latest_value) for s in credit.series])
    ok &= len(credit.series) >= 4

    daily = await client.get_series("WS_CBPOL", "D.CA", last_n=5)
    print(
        f"OK: daily policy rate -> {daily.series[0].latest_period} {daily.series[0].latest_value}"
    )
    ok &= len(daily.series[0].observations) == 5

    payments = await client.get_series("WS_CPMI_SYSTEMS", "A.CA.*.*.*.*.*.*", last_n=1)
    print(f"OK: CPMI systems -> {len(payments.series)} series, notes {payments.notes}")
    ok &= len(payments.series) > 20

    for indicator in constants.INDICATORS:
        result = await client.compare_countries(indicator, compare_with=["G7", "EURO_AREA"])
        canada = result.countries[0]
        print(
            f"OK: {indicator} -> CA {canada.latest_period} {canada.latest_value}, rank "
            f"{result.canada_rank}/{result.ranked_countries} in {result.rank_period}"
        )
        ok &= canada.area_code == "CA" and len(result.countries) >= 3

    french = await client.compare_countries("private_debt_service_ratio", ["AU", "NZ"], lang="fr")
    print(f"OK: compare (fr) -> {french.indicator_label} | {french.notes}")
    ok &= french.indicator_label.startswith("Ratio du service")
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("short key", client.get_series("WS_DSR", "Q.CA"), InvalidInput)
    ok &= await _expect_error("no data", client.get_series("WS_DSR", "Q.ZZ.P"), NotFound)
    ok &= await _expect_error("unknown dataset", client.describe_dataset("WS_NOPE"), NotFound)
    ok &= await _expect_error(
        "future period", client.get_series("WS_DSR", "Q.CA.P", start_period="2030"), NotFound
    )
    ok &= await _expect_error(
        "open key", client.get_series("WS_LBS_D_PUB", ".".join(["*"] * 12)), InvalidInput
    )
    ok &= await _expect_error("unknown indicator", client.compare_countries("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("bis_list_datasets", {"lang": "fr"}),
        ("bis_describe_dataset", {"dataset": "WS_SPP"}),
        ("bis_get_series", {"dataset": "WS_SPP", "key": "Q.CA.R.628", "last_n": 4}),
        (
            "bis_compare_countries",
            {"indicator": "household_debt_service_ratio", "compare_with": ["US", "AU"]},
        ),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            data = json.loads(text)
            print(f"OK: call_tool({name}) -> {sorted(data)[:5]}")
            ok &= not result.is_error
    return ok


async def run() -> int:
    ok = await main()
    ok &= await errors()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
