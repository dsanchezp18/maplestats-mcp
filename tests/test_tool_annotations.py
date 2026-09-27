"""Every tool declares the MCP read-only behaviour hints.

Clients and MCP directories use these hints to decide whether a tool
needs confirmation; a tool registered without them looks potentially
destructive. The server sets them in ModuleProvider, so a new module is
covered automatically.
"""

from __future__ import annotations

from maplestats_mcp.server import mcp


async def test_every_module_tool_is_annotated_read_only():
    tools = await mcp._list_tools()
    unannotated = sorted(
        tool.name
        for tool in tools
        if tool.annotations is None
        or tool.annotations.read_only_hint is not True
        or tool.annotations.destructive_hint is not False
        or tool.annotations.idempotent_hint is not True
        or tool.annotations.open_world_hint is None
    )
    assert not unannotated, f"tools missing read-only annotations: {unannotated}"


async def test_visible_search_tools_are_annotated():
    visible = {tool.name: tool for tool in await mcp.list_tools()}
    for name in ("search_tools", "call_tool", "plan_query"):
        assert visible[name].annotations is not None, name
        assert visible[name].annotations.read_only_hint is True, name
    assert visible["plan_query"].annotations.open_world_hint is False
    assert visible["search_tools"].annotations.open_world_hint is False
