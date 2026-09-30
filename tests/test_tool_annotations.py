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
    visible = {tool.name: tool.annotations for tool in await mcp.list_tools()}
    for name in ("search_tools", "call_tool", "plan_query"):
        annotations = visible[name]
        assert annotations is not None, name
        assert annotations.read_only_hint is True, name
        if name != "call_tool":
            assert annotations.open_world_hint is False, name


async def test_every_tool_has_a_title():
    """Claude's connector directory rejects tools without a title."""
    untitled = sorted(tool.name for tool in await mcp._list_tools() if not tool.title)
    untitled += sorted(tool.name for tool in await mcp.list_tools() if not tool.title)
    assert not untitled, f"tools missing a title: {untitled}"
