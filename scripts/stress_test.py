"""Stress the server as a separate process, the way an MCP client does.

Starts `python -m maplestats_mcp` over stdio (and, with --http, over
streamable HTTP on a local port), then sends bursts of concurrent calls:
quick local ones, slow live ones, and calls that fail on purpose. It
reports every transport-level failure (a dropped connection, a closed
stream, a timeout) separately from ordinary tool errors, which are
expected and fine.

Usage:
    uv run python scripts/stress_test.py            # stdio
    uv run python scripts/stress_test.py --http     # streamable HTTP too
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

CALLS: list[tuple[str, dict[str, Any]]] = [
    ("plan_query", {"question": "rents and interest rates in Calgary"}),
    ("boc_search_series", {"query": "exchange rate"}),
    ("parliament_search_votes", {"limit": 5}),
    ("earthquakes_search", {"min_magnitude": 3}),
    ("cihi_search_indicators", {"query": "wait"}),
    ("canadabuys_search_tenders", {"query": "snow"}),
    ("gazette_list_issues", {}),
    ("wds_search_cubes", {"query": "consumer price index"}),
    ("parliament_get_bill", {"session": "45-1", "number": "C-99999"}),  # fails: bad number
    ("no_such_tool", {}),  # fails: unknown tool
]


async def _burst(client: Client, rounds: int) -> tuple[int, int, list[str]]:
    ok = tool_errors = 0
    transport_errors: list[str] = []

    async def one(name: str, args: dict[str, Any]) -> None:
        nonlocal ok, tool_errors
        try:
            result = await asyncio.wait_for(
                client.call_tool(
                    "call_tool", {"name": name, "arguments": args}, raise_on_error=False
                ),
                timeout=180,
            )
            if result.is_error:
                tool_errors += 1
            else:
                ok += 1
        except Exception as exc:  # noqa: BLE001 - the point is to catch every transport failure
            transport_errors.append(f"{name}: {type(exc).__name__}: {exc}"[:300])

    for _ in range(rounds):
        await asyncio.gather(*(one(name, args) for name, args in CALLS))
        await client.list_tools()
    return ok, tool_errors, transport_errors


async def _run(label: str, client: Client, rounds: int) -> bool:
    started = time.monotonic()
    async with client:
        ok, tool_errors, transport_errors = await _burst(client, rounds)
        # An idle gap, then more calls: catches sessions that expire while idle.
        await asyncio.sleep(20)
        more_ok, more_tool_errors, more_transport = await _burst(client, 1)
    print(
        f"{label}: {ok + more_ok} ok, {tool_errors + more_tool_errors} tool errors (expected), "
        f"{len(transport_errors) + len(more_transport)} transport failures, "
        f"{time.monotonic() - started:.0f}s"
    )
    for line in transport_errors + more_transport:
        print("  TRANSPORT FAILURE", line)
    return not (transport_errors or more_transport)


async def main() -> int:
    rounds = 3
    env = {**os.environ, "MAPLE_TRANSPORT": "stdio"}
    stdio = Client(StdioTransport(sys.executable, ["-m", "maplestats_mcp"], env=env))
    passed = await _run("stdio", stdio, rounds)

    if "--http" in sys.argv:
        port = "8765"
        env = {
            **os.environ,
            "MAPLE_TRANSPORT": "http",
            "MAPLE_HOST": "127.0.0.1",
            "MAPLE_PORT": port,
        }
        server = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "maplestats_mcp", env=env
        )
        try:
            await asyncio.sleep(30)
            passed &= await _run("http", Client(f"http://127.0.0.1:{port}/mcp"), rounds)
        finally:
            server.terminate()

    print("STRESS TEST " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
