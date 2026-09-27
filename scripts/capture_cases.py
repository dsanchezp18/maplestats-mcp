"""Record the case-study calls the website shows (site/_data/cases/*.json).

Each case is one real call made through the server's own call_tool, with
the response and the R, Python, Stata and Julia scripts reproduce_code
writes for it. The website build reads these files and never calls an
upstream itself, so a capture is dated and stays as recorded until this
script is run again.

Usage:
    uv run python scripts/capture_cases.py            # every case
    uv run python scripts/capture_cases.py ircc       # one case
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

from maplestats_mcp.modules.reproduce import client as reproduce
from maplestats_mcp.server import mcp

OUT = Path(__file__).resolve().parent.parent / "site" / "_data" / "cases"

CASES: dict[str, dict[str, Any]] = {
    "ircc": {
        "discover": {
            "name": "ircc_monthly_list_tables",
            "arguments": {"query": "permanent residents CMA"},
        },
        "name": "ircc_monthly_query",
        "arguments": {
            "table_id": "ODP-PR-PT_CMA",
            "filters": {"census_metropolitan_area": "Edmonton"},
            "period": "year",
            "year_from": 2015,
        },
    },
    "labour": {
        "name": "statcan_indicators_get_indicators",
        "arguments": {"query": "unemployment rate"},
    },
    "city": {
        "discover": {
            "name": "socrata_search_datasets",
            "arguments": {"portal": "edmonton", "query": "building permits", "limit": 3},
        },
        "name": "socrata_query_dataset_rows",
        "arguments": {
            "portal": "edmonton",
            "dataset_id": "24uj-dj8v",
            "select": "issue_date, job_description, neighbourhood, construction_value",
            "where": "year = 2026 AND construction_value IS NOT NULL",
            "order": "construction_value DESC",
            "limit": 5,
        },
    },
}


async def _call(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    result = await client.call_tool("call_tool", {"name": name, "arguments": arguments})
    data = result.structured_content or {}
    return data.get("result", data)


async def capture(key: str) -> Path:
    case = CASES[key]
    async with Client(mcp) as client:
        discover = case.get("discover")
        found = await _call(client, discover["name"], discover["arguments"]) if discover else None
        response = await _call(client, case["name"], case["arguments"])
    code = await reproduce.reproduce(case["name"], case["arguments"], "all")
    record = {
        "captured": datetime.now(UTC).date().isoformat(),
        "discover": {**discover, "response": found} if discover else None,
        "request": {"name": case["name"], "arguments": case["arguments"]},
        "response": response,
        "scripts": {s.language: s.code for s in code.scripts},
        "script_notes": list(code.notes),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{key}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


async def main(keys: list[str]) -> None:
    for key in keys:
        print(f"captured {await capture(key)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("cases", nargs="*", choices=list(CASES), help="default: every case")
    args = parser.parse_args()
    asyncio.run(main(args.cases or list(CASES)))
