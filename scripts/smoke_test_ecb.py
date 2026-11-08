"""Live smoke test for the ecb module: calls the real ECB Data Portal API (not
mocks) for every client function and every tool, per AGENTS.md's "lesson from
auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_ecb.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.ecb import client, constants
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

    # 105 dataflows on 2026-11-07; every described one must still exist.
    datasets = await client.list_datasets()
    ids = {d.id for d in datasets.datasets}
    print(f"OK: list_datasets -> {datasets.total} datasets")
    missing = set(constants.DATASET_NOTES) - ids
    if missing:
        print(f"FAIL: described datasets missing upstream: {sorted(missing)}")
        ok = False

    for dataset in ("EXR", "FM", "HICP", "BSI", "MIR", "EST"):
        structure = await client.describe_dataset(dataset)
        sizes = [len(d.codes) for d in structure.dimensions]
        print(f"OK: describe {dataset} -> {structure.key_template} {sizes}")
        ok &= all(sizes)

    for name, spec in constants.INDICATORS.items():
        result = await client.get_indicator(name)
        row = result.rows[-1]
        print(f"OK: {name} -> {row.date} {row.value} {row.unit} ({len(result.rows)} rows)")
        ok &= row.series_id == f"{spec.dataset}.{spec.key}" and row.date >= "2025"

    rates = await client.search_series("EXR", "D..EUR.SP00.A")
    print(f"OK: euro reference rates -> {rates.total_matches} series")
    ok &= rates.total_matches > 20
    services = await client.search_series("HICP", "M.U2.N..4D0.ANR", query="services")
    print(f"OK: HICP services -> {[s.key for s in services.series][:3]}")
    ok &= services.total_matches > 0

    both = await client.get_series("EXR", "M.CAD+USD.EUR.SP00.A", start_period="2025-01", lang="fr")
    print(f"OK: EXR monthly CAD+USD -> {len(both.series)} series, {len(both.rows)} rows")
    ok &= len(both.series) == 2
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("short key", client.get_series("EXR", "D.CAD.EUR"), InvalidInput)
    ok &= await _expect_error(
        "unknown code", client.get_series("EXR", "D.ZZZ.EUR.SP00.A", last_n=1), NotFound
    )
    ok &= await _expect_error("unknown dataset", client.describe_dataset("NOPE"), NotFound)
    ok &= await _expect_error(
        "future period",
        client.get_series("EXR", "M.CAD.EUR.SP00.A", start_period="2031-01"),
        NotFound,
    )
    ok &= await _expect_error("unknown indicator", client.get_indicator("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("ecb_list_datasets", {"query": "interest", "lang": "fr"}),
        ("ecb_describe_dataset", {"dataset": "EXR", "code_query": "Canadian"}),
        ("ecb_search_series", {"dataset": "EXR", "key": "M..EUR.SP00.A", "query": "yen"}),
        ("ecb_get_series", {"dataset": "EXR", "key": "M.JPY.EUR.SP00.A", "last_n": 3}),
        ("ecb_get_indicator", {"indicator": "deposit_facility_rate"}),
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
