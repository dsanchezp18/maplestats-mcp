"""Live smoke test: every Alberta Economic Dashboard key indicator, end to end.

For each of the dashboard's key indicators, ab_economic_get_indicator_series
must list its series, and every listed series must load through
ab_economic_get_data with the filters exactly as published. Checking only the
first indicator let four broken pages (renamed slugs, a moved page, a page
with no API links) and 21 series with spaced column names go unnoticed.
Calls go through the server's call_tool, as a client would make them.

Usage:
    uv run python scripts/smoke_test_ab_economic.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.server import mcp


async def _call(client: Client, tool: str, args: dict[str, Any]) -> tuple[bool, Any]:
    result = await client.call_tool(
        "call_tool", {"name": tool, "arguments": args}, raise_on_error=False
    )
    text = next((b.text for b in result.content if isinstance(b, TextContent)), "")
    if result.is_error:
        return False, text
    return True, json.loads(text)


async def main() -> int:
    failures: list[str] = []
    async with Client(mcp) as client:
        ok, catalogue = await _call(client, "ab_economic_list_indicators", {})
        if not ok or not catalogue["indicators"]:
            print(f"FAIL ab_economic_list_indicators: {catalogue}")
            return 1
        for indicator in catalogue["indicators"]:
            name = indicator["name"]
            ok, listed = await _call(
                client, "ab_economic_get_indicator_series", {"indicator": name}
            )
            if not ok or not listed["series"]:
                failures.append(name)
                print(f"FAIL {name}: {str(listed)[:200]}")
                continue
            bad = 0
            for series in listed["series"]:
                ok, data = await _call(
                    client,
                    "ab_economic_get_data",
                    {"table": series["table"], "filters": series["filters"], "limit": 2},
                )
                if not ok or not data["rows"]:
                    bad += 1
                    failures.append(f"{name} / {series['name']}")
                    print(f"FAIL {name} / {series['name']}: {str(data)[:200]}")
            print(f"OK   {name}: {len(listed['series']) - bad} of {len(listed['series'])} series")
    print()
    if failures:
        print(f"AB ECONOMIC SMOKE TEST FAILED ({len(failures)})")
        return 1
    print("AB ECONOMIC SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
