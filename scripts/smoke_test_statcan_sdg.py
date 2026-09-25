"""Live smoke test for the statcan.sdg module's client.py: calls the
real Open SDG GitHub Pages data hosts (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_sdg.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.sdg import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    canada = await client.search_indicators("canada")
    print(f"OK: search_indicators('canada') -> {canada.total_matched} indicators")
    ok &= canada.total_matched > 50  # confirmed live: 86
    sample = canada.indicators[0]
    print("  sample:", sample.model_dump())
    ok &= bool(sample.indicator_name)

    glob = await client.search_indicators("global")
    print(f"OK: search_indicators('global') -> {glob.total_matched} indicators")
    ok &= glob.total_matched > 200  # confirmed live: 251

    vehicles = await client.search_indicators("canada", "zero-emission")
    print(f"OK: search_indicators('canada', 'zero-emission') -> {vehicles.total_matched}")
    ok &= vehicles.total_matched > 0
    code = vehicles.indicators[0].code

    metadata = await client.get_indicator_metadata("canada", code)
    print(f"OK: get_indicator_metadata('canada', {code!r}) -> {metadata.indicator_name}")
    ok &= bool(metadata.description)
    ok &= len(metadata.sources) > 0
    print("  sample:", metadata.model_dump())

    fr_metadata = await client.get_indicator_metadata("canada", code, lang="fr")
    print(f"OK: get_indicator_metadata(..., lang=fr) -> {fr_metadata.indicator_name}")
    ok &= bool(fr_metadata.indicator_name)

    data = await client.get_indicator_data("canada", code)
    print(f"OK: get_indicator_data('canada', {code!r}) -> {data.returned_count} observation(s)")
    ok &= data.returned_count > 0
    ok &= data.observations[0].year > 2000

    try:
        await client.get_indicator_metadata("canada", "99-9-9")
        print("FAIL: expected NotFound for a bogus indicator code")
        ok = False
    except NotFound:
        print("OK: bogus indicator code raises NotFound as expected")

    try:
        await client.search_indicators("bogus-framework")
        print("FAIL: expected InvalidInput for a bogus framework")
        ok = False
    except InvalidInput:
        print("OK: bogus framework raises InvalidInput as expected")

    print("\nSTATCAN SDG SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
