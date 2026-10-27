"""Live smoke test for the isc module: calls First Nation Profiles, ISC's open
dataset and ISC's drinking water advisory pages (not mocks) for every client
function and every tool, per AGENTS.md's "lesson from auditing the StatCan
module".

Usage:
    uv run python scripts/smoke_test_isc.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Literal

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.isc import client
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

    # 646 registry groups a year in 2023 and 2024 (checked 2026-10-26).
    everything = await client.search_first_nations("", limit=700)
    print(f"OK: search all -> {everything.total_matched} in {everything.year}")
    ok &= everything.total_matched > 600 and everything.year >= 2024
    musqueam = await client.search_first_nations("musqueam")
    print(
        "OK: search musqueam ->", [(f.band_number, f.province_code) for f in musqueam.first_nations]
    )
    ok &= musqueam.first_nations[0].band_number == 550
    quebec = await client.search_first_nations("cree", province="QC", lang="fr")
    print("OK: search cree QC (fr) ->", [f.name for f in quebec.first_nations])
    ok &= quebec.total_matched >= 5

    for band, lang in ((143, "en"), (550, "fr")):
        profile = await client.get_first_nation_profile(band, lang=lang)
        print(
            f"OK: profile {band} ({lang}) -> {profile.name}, council {profile.tribal_council}, "
            f"{len(profile.reserves)} reserves {profile.total_reserve_hectares} ha, "
            f"{len(profile.governance.officials)} officials, zone {profile.geography.zone}"
        )
        ok &= bool(profile.name) and bool(profile.reserves) and bool(profile.governance.officials)
    ok &= (await client.get_first_nation_profile(143)).tribal_council is not None

    for lang in ("en", "fr"):
        population = await client.get_registered_population(550, lang=lang)
        print(
            f"OK: population ({lang}) -> {population.total} as of {population.as_of_month}, "
            f"annual {[(a.year, a.total) for a in population.annual]}"
        )
        ok &= bool(population.total) and population.as_of_month is not None
        ok &= len(population.annual) >= 2
        ok &= sum(r.total or 0 for r in population.by_residence) == population.total

    statuses: tuple[tuple[Literal["current", "lifted", "all"], str], ...] = (
        ("current", "en"),
        ("lifted", "fr"),
        ("all", "en"),
    )
    for status, lang in statuses:
        advisories = await client.list_drinking_water_advisories(status, lang=lang)
        print(
            f"OK: long-term {status} ({lang}) -> {advisories.total_matched} of "
            f"{advisories.current_count} current / {advisories.lifted_count} lifted, generated "
            f"{advisories.generated}, file {advisories.data_url.rsplit('/', 1)[-1]}"
        )
        ok &= advisories.current_count > 0 and advisories.lifted_count > 100
        ok &= advisories.generated is not None
    ontario = await client.list_drinking_water_advisories(province="ON")
    print("OK: long-term current ON ->", [a.community for a in ontario.advisories][:5])
    ok &= all(a.province_code == "ON" for a in ontario.advisories) and bool(ontario.advisories)
    lifted = await client.list_drinking_water_advisories("lifted", limit=1000)
    ok &= all(a.date_lifted is not None for a in lifted.advisories)

    for lang in ("en", "fr"):
        short = await client.list_short_term_advisories(lang=lang)
        regions = sorted({a.region for a in short.advisories})
        active = sum(a.active for a in short.advisories)
        print(
            f"OK: short-term ({lang}) -> {short.total_matched} listed, {active} active, page "
            f"says {short.in_effect_count} as of {short.as_of}, regions {regions}"
        )
        ok &= short.as_of is not None and short.in_effect_count is not None
        ok &= bool(short.advisories) and "BC" not in regions
    manitoba = await client.list_short_term_advisories(province="MB", active_only=True)
    print("OK: short-term MB active ->", [(a.first_nation, a.code) for a in manitoba.advisories])
    ok &= all(a.region == "MANITOBA" and a.active for a in manitoba.advisories)
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error("unknown band", client.get_first_nation_profile(99999), NotFound)
    ok &= await _expect_error(
        "unknown band population", client.get_registered_population(99999), NotFound
    )
    ok &= await _expect_error(
        "unknown province", client.search_first_nations("", province="Atlantis"), InvalidInput
    )
    ok &= await _expect_error(
        "short-term BC", client.list_short_term_advisories(province="BC"), InvalidInput
    )
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("isc_search_first_nations", {"query": "attawapiskat"}),
        ("isc_get_first_nation_profile", {"band_number": 143, "lang": "fr"}),
        ("isc_get_registered_population", {"band_number": 143}),
        ("isc_list_drinking_water_advisories", {"status": "all", "community": "Neskantaga"}),
        ("isc_list_short_term_advisories", {"province": "ON", "lang": "fr"}),
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
