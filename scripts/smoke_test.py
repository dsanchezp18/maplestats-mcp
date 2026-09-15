"""Live smoke test: calls real StatCan endpoints through the actual
MCP server (in-process, via fastmcp.Client), not mocks. Run this on a
machine where outbound HTTPS to statcan.gc.ca actually works — it
timed out inside the sandbox this project was built in (TLS handshake
issue specific to that environment, documented in the session that
built this).

Usage:
    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent

from maple_data_mcp.server import mcp


def _text_of(result: CallToolResult) -> str:
    for block in result.content:
        if isinstance(block, TextContent):
            return block.text
    return "<no text content>"


async def _call_tool(client: Client, name: str, arguments: dict) -> CallToolResult:
    """Call `name` via the call_tool meta-tool, capturing failures in
    the result instead of raising — raise_on_error=False so one failing
    check doesn't abort the rest of the smoke test."""
    return await client.call_tool(
        "call_tool", {"name": name, "arguments": arguments}, raise_on_error=False
    )


async def main() -> int:
    ok = True
    async with Client(mcp) as client:
        # search_tools/call_tool are the only tools directly exposed
        # (BM25SearchTransform hides the rest behind them by design).
        search = await client.call_tool("search_tools", {"query": "search statcan cubes"})
        tools = json.loads(_text_of(search))
        print("Discovered via search_tools:", [t["name"] for t in tools])
        if not tools:
            print("FAIL: search_tools returned nothing - tool registration is broken.")
            ok = False

        print()
        result = await _call_tool(client, "wds_search_cubes", {"query": "consumer price index"})
        if result.is_error:
            print("FAIL: wds_search_cubes ->", _text_of(result))
            ok = False
        else:
            print("OK: wds_search_cubes returned data.")
            print(_text_of(result)[:500])

        print()
        result = await _call_tool(client, "rdaas_search_classifications", {"query": "NAICS"})
        if result.is_error:
            print("FAIL: rdaas_search_classifications ->", _text_of(result))
            ok = False
        else:
            print("OK: rdaas_search_classifications returned data.")
            print(_text_of(result)[:500])

    print()
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
