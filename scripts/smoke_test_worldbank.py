"""Live smoke test for the worldbank module: calls the real World Bank
Indicators API (not mocks) for every client function and every tool, per
AGENTS.md's "lesson from auditing the StatCan module".

The API is slow (up to ~40 s for the French catalogue) and its edge answers
HTTP 502 for a while after bursts, so the script runs one call at a time.

Usage:
    uv run python scripts/smoke_test_worldbank.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.worldbank import client
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

    # Catalogue: 1,498 WDI indicators and 21 topics on 2026-10-03.
    topics = await client.list_topics()
    print(f"OK: list_topics -> {len(topics.topics)} topics, e.g. {topics.topics[2].name}")
    ok &= len(topics.topics) >= 15
    topics_fr = await client.list_topics(lang="fr")
    print(f"OK: list_topics(fr) -> {topics_fr.topics[2].name}")
    ok &= topics_fr.topics[2].name != topics.topics[2].name

    growth = await client.search_indicators("GDP growth")
    print("OK: search 'GDP growth' ->", [(i.id, i.name) for i in growth.indicators[:3]])
    ok &= "NY.GDP.MKTP.KD.ZG" in [i.id for i in growth.indicators[:5]]
    unemployment = await client.search_indicators("unemployment", topic="Social Protection")
    print(f"OK: search 'unemployment' in topic -> {unemployment.total_matches} matches")
    ok &= "SL.UEM.TOTL.ZS" in [i.id for i in unemployment.indicators]
    by_topic = await client.search_indicators(topic="21")
    print(f"OK: topic 21 ({by_topic.topic}) -> {by_topic.total_matches} indicators")
    ok &= by_topic.total_matches > 20
    french = await client.search_indicators("chômage", lang="fr")
    print("OK: search 'chômage' (fr) ->", [(i.id, i.name) for i in french.indicators[:2]])
    ok &= any(i.id == "SL.UEM.TOTL.ZS" for i in french.indicators)
    by_code = await client.search_indicators("ny.gdp.pcap.pp.kd")
    ok &= by_code.indicators[0].id == "NY.GDP.PCAP.PP.KD"

    detail = await client.get_indicator("SL.UEM.TOTL.ZS")
    print(f"OK: get_indicator -> {detail.name} | {detail.source_organization[:60]}")
    ok &= "ILO" in detail.source_organization and detail.definition != ""
    detail_fr = await client.get_indicator("NY.GDP.PCAP.CD", lang="fr")
    print(f"OK: get_indicator(fr) -> {detail_fr.name}")
    ok &= detail_fr.name.startswith("PIB")

    # Data: Canada alone (66 years of GDP from 1960), then with peers.
    gdp = await client.get_canada_series("NY.GDP.MKTP.CD")
    canada = gdp.countries[0]
    print(
        f"OK: GDP Canada -> {len(canada.observations)} years "
        f"{canada.observations[0].year}-{canada.latest_year}, latest {canada.latest_value:,.0f}"
    )
    ok &= canada.observations[0].year == 1960 and len(canada.observations) >= 65
    ok &= gdp.canada_rank is None and gdp.provenance.licence is not None

    g7 = await client.get_canada_series("NY.GDP.MKTP.KD.ZG", compare_with=["G7"], most_recent=5)
    print(
        f"OK: growth vs G7 -> {[c.country_code for c in g7.countries]}, Canada rank "
        f"{g7.canada_rank}/{g7.ranked_countries} in {g7.rank_year}"
    )
    ok &= len(g7.countries) == 7 and g7.countries[0].country_code == "CAN"
    ok &= all(len(c.observations) <= 5 for c in g7.countries) and g7.canada_rank is not None

    oecd = await client.get_canada_series(
        "SL.UEM.TOTL.ZS", compare_with=["OECD", "usa", "AUS"], start_year=2015, end_year=2020
    )
    print(
        "OK: unemployment vs OECD aggregate ->",
        [(c.country_code, c.country_name, len(c.observations)) for c in oecd.countries],
        oecd.notes,
    )
    ok &= [c.country_code for c in oecd.countries] == ["CAN", "OED", "USA", "AUS"]
    ok &= all(2015 <= o.year <= 2020 for c in oecd.countries for o in c.observations)

    members = await client.get_canada_series(
        "NY.GDP.PCAP.PP.KD", compare_with=["OECD_MEMBERS"], most_recent=1
    )
    print(
        f"OK: GDP per capita PPP vs OECD members -> {len(members.countries)} countries, "
        f"Canada rank {members.canada_rank}/{members.ranked_countries} in {members.rank_year}"
    )
    ok &= len(members.countries) >= 35 and (members.ranked_countries or 0) >= 30

    inflation_fr = await client.get_canada_series(
        "FP.CPI.TOTL.ZG", compare_with=["DEU", "FRA"], most_recent=3, lang="fr"
    )
    print("OK: inflation (fr) ->", [c.country_name for c in inflation_fr.countries])
    ok &= "Allemagne" in [c.country_name for c in inflation_fr.countries]

    gini = await client.get_canada_series("SI.POV.GINI")
    print(f"OK: Gini (sparse) -> {[o.year for o in gini.countries[0].observations][-5:]}")
    ok &= len(gini.countries[0].observations) < 66
    return ok


async def errors() -> bool:
    ok = True
    ok &= await _expect_error(
        "future years", client.get_canada_series("NY.GDP.MKTP.CD", start_year=2030), NotFound
    )
    ok &= await _expect_error("unknown indicator", client.get_canada_series("NOPE.X"), NotFound)
    ok &= await _expect_error(
        "non-OECD comparison",
        client.get_canada_series("NY.GDP.MKTP.CD", compare_with=["CHN"]),
        InvalidInput,
    )
    ok &= await _expect_error(
        "mixed year arguments",
        client.get_canada_series("NY.GDP.MKTP.CD", start_year=2000, most_recent=3),
        InvalidInput,
    )
    ok &= await _expect_error("unknown topic", client.search_indicators(topic="zzz"), InvalidInput)
    ok &= await _expect_error("empty search", client.search_indicators(), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it."""
    ok = True
    calls = [
        ("worldbank_list_topics", {}),
        ("worldbank_search_indicators", {"query": "life expectancy"}),
        ("worldbank_get_indicator", {"indicator": "SP.DYN.LE00.IN", "lang": "fr"}),
        (
            "worldbank_get_canada_series",
            {"indicator": "SP.DYN.LE00.IN", "compare_with": ["G7", "OECD"], "most_recent": 2},
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
