"""Server stability guards: tool timeouts and what gets imported at startup."""

from __future__ import annotations

import asyncio
import subprocess
import sys

from fastmcp import Client, FastMCP

from maple_data_mcp.shared.timeouts import ToolTimeoutMiddleware


async def test_slow_tool_fails_with_named_error_instead_of_hanging():
    server = FastMCP("t")
    server.add_middleware(ToolTimeoutMiddleware(0.2))

    @server.tool
    async def slow_tool() -> str:
        await asyncio.sleep(5)
        return "late"

    async with Client(server) as client:
        result = await client.call_tool("slow_tool", {}, raise_on_error=False)
    assert result.is_error
    assert "slow_tool did not finish within 0 s" in result.content[0].text  # type: ignore[union-attr]


def test_startup_does_not_import_module_tests():
    # A fresh interpreter: pytest itself has already imported the test modules here.
    probe = (
        "import sys, maple_data_mcp.server; "
        "print(sorted(n for n in sys.modules if '__tests__' in n or n == 'pytest'))"
    )
    output = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()
    assert output == "[]", f"server startup imported test code: {output[:300]}"
