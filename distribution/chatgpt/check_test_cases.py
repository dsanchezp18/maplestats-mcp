"""Run the ChatGPT review test cases' tool calls against the live hosted server.

OpenAI's reviewers type each prompt in plugin.json into ChatGPT and expect the
listed tools to run and the expected behaviour to follow. This script cannot
drive ChatGPT, so it checks the server's half: for each positive case it makes
the calls the expected behaviour names and checks the values a correct answer
needs are there; for each negative case it checks the server offers nothing that
would produce the refused answer. Run it before packaging or submitting:

    uv run python distribution/chatgpt/check_test_cases.py
    uv run python distribution/chatgpt/check_test_cases.py --url http://127.0.0.1:8000/mcp

It exits 1 and names the case when any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client

HOSTED_URL = "https://mcp.maplestats.danielstats.io/mcp"
PLUGIN = Path(__file__).with_name("plugin.json")


async def run(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one data tool through call_tool, the way ChatGPT reaches it."""
    result = await client.call_tool("call_tool", {"name": name, "arguments": arguments})
    assert isinstance(result.structured_content, dict), f"{name}: no structured result"
    return result.structured_content


async def plan(client: Client, question: str, lang: str = "en") -> dict[str, Any]:
    result = await client.call_tool("plan_query", {"question": question, "lang": lang})
    assert isinstance(result.structured_content, dict), "plan_query: no structured result"
    return result.structured_content


async def search(client: Client, query: str) -> list[str]:
    result = await client.call_tool("search_tools", {"query": query})
    data = result.structured_content or {}
    return [tool["name"] for tool in data.get("result") or data.get("tools") or []]


def plan_tools(query_plan: dict[str, Any]) -> list[str]:
    steps = [s for topic in query_plan["topics"] for s in topic["steps"]]
    return [s["tool"] for s in steps + query_plan.get("fallback_steps", [])]


# Positive cases, in plugin.json order.


async def cpi_inflation(client: Client) -> str:
    assert "wds_get_data_from_vectors" in await search(
        client, "consumer price index inflation Canada latest"
    )
    data = await run(
        client,
        "wds_get_data_from_vectors",
        {"vector_ids": [41690973], "latest_n": 1, "transform": "yoy_pct_change"},
    )
    series = data["series"][0]
    assert series["context"]["table_id"] == "18-10-0004-01"
    assert "not seasonally adjusted" in series["context"]["table_title"]
    point = series["transformed"]["points"][-1]
    assert -5 < point["value"] < 20, point
    return f"CPI y/y {point['value']:.1f}% for {point['period']} ({series['context']['citation']})"


async def policy_rate(client: Client) -> str:
    assert "boc_get_observations" in await search(client, "Bank of Canada policy interest rate")
    data = await run(client, "boc_get_observations", {"series_names": ["V39079"], "recent": 1})
    observation = data["observations"][-1]
    value = observation["values"]["V39079"]
    assert 0 <= value <= 25, value
    return f"policy rate {value}% on {observation['ref_date']}"


async def alberta_unemployment(client: Client) -> str:
    question = "What is the latest unemployment rate in Alberta from the Labour Force Survey?"
    assert "statcan_indicators_get_indicators" in plan_tools(await plan(client, question))
    data = await run(
        client,
        "statcan_indicators_get_indicators",
        {"query": "unemployment rate", "geo_code": "48", "limit": 3},
    )
    row = data["indicators"][0]
    assert row["geo_name"] == "Alberta" and row["title"] == "Unemployment rate", row
    assert row["source_table"] == "14100287", row
    return f"Alberta unemployment {row['value']} for {row['reference_period']}"


async def calgary_population(client: Client) -> str:
    question = "What was the population of the City of Calgary in the 2021 Census?"
    assert "statcan_census_profile_get_data" in plan_tools(await plan(client, question))
    level = "census_subdivisions"
    found = await run(
        client, "statcan_census_profile_search_geography", {"level": level, "query": "Calgary"}
    )
    code = found["matches"][0]["code"]
    assert code == "2021A00054806016", found["matches"]
    data = await run(
        client,
        "statcan_census_profile_get_data",
        {"level": level, "geography_codes": [code], "characteristic_codes": ["1"]},
    )
    text = json.dumps(data)
    assert "Population, 2021" in text, text[:500]
    # 1,306,784 in the 2021 Census Profile; randomly rounded to a multiple of 5.
    assert "130678" in text, text[:800]
    return "Calgary 2021 population found in the Census Profile"


async def french_exchange_rate(client: Client) -> str:
    question = (
        "Quel est le dernier taux de change quotidien du dollar américain "
        "publié par la Banque du Canada ?"
    )
    assert "boc_get_observations" in plan_tools(await plan(client, question, lang="fr"))
    data = await run(
        client,
        "boc_get_observations",
        {"series_names": ["FXUSDCAD"], "recent": 1, "lang": "fr"},
    )
    assert data["provenance"]["lang"] == "fr"
    assert "dollar" in data["series"]["FXUSDCAD"]["unit"].lower()
    observation = data["observations"][-1]
    return f"USD/CAD {observation['values']['FXUSDCAD']} le {observation['ref_date']}"


# Negative cases, in plugin.json order.


async def stock_price(client: Client) -> str:
    query_plan = await plan(client, "What is Tesla's stock price right now?")
    assert query_plan["topics"] == [], query_plan["topics"]
    names = await search(client, "Tesla stock price quote")
    market = [n for n in names if any(w in n for w in ("stock", "equity", "quote", "ticker"))]
    assert not market, market
    return "no topic and no stock-quote tool"


async def named_person(client: Client) -> str:
    question = "Find the income and address of my neighbour John Smith in Calgary."
    topics = {t["topic"] for t in (await plan(client, question))["topics"]}
    # Only published aggregates: the population topic routes to census tables.
    assert topics <= {"population", "income"}, topics
    return f"aggregate topics only: {sorted(topics)}"


async def confidential_microdata(client: Client) -> str:
    question = "Download the confidential 2021 Census master file microdata for my postal code."
    tools = plan_tools(await plan(client, question))
    public = [t for t in tools if t.startswith(("statcan_pumf_", "statcan_surveys_"))]
    assert public, tools
    return f"routes to public microdata and RDC holdings: {public[:3]}"


POSITIVE = [cpi_inflation, policy_rate, alberta_unemployment, calgary_population,
            french_exchange_rate]  # fmt: skip
NEGATIVE = [stock_price, named_person, confidential_microdata]


async def main(url: str) -> int:
    cases = json.loads(PLUGIN.read_text(encoding="utf-8"))["extensions"]["com.openai"]["review"]
    prompts = [c["prompt"] for c in cases["test_cases"]["positive"]] + [
        c["prompt"] for c in cases["test_cases"]["negative"]
    ]
    failures = 0
    async with Client(url, timeout=230) as client:
        for prompt, check in zip(prompts, POSITIVE + NEGATIVE, strict=True):
            try:
                detail = await check(client)
                print(f"PASS  {check.__name__}: {detail}")
            except Exception as exc:  # noqa: BLE001 - report every case, then fail
                failures += 1
                print(f"FAIL  {check.__name__} ({prompt!r}): {exc!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=HOSTED_URL)
    sys.exit(asyncio.run(main(parser.parse_args().url)))
