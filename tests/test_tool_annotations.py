"""Every tool declares accurate MCP behaviour hints.

Clients and MCP directories use these hints to decide whether a tool
needs confirmation; a tool registered without them looks potentially
destructive. The server sets them in ModuleProvider, so a new module is
covered automatically.
"""

from __future__ import annotations

from maplestats_mcp import config
from maplestats_mcp.server import AnnotatedBM25SearchTransform, _export_annotations, mcp


async def test_every_module_tool_has_accurate_annotations():
    for tool in await mcp._list_tools():
        annotations = tool.annotations
        assert annotations is not None, tool.name
        writes_file = tool.name == "reproduce_workbook" and config.get_transport() == "stdio"
        assert annotations.read_only_hint is not writes_file, tool.name
        assert annotations.destructive_hint is writes_file, tool.name
        assert annotations.idempotent_hint is not writes_file, tool.name
        assert annotations.open_world_hint is not None, tool.name


async def test_visible_search_tools_are_annotated():
    visible = {tool.name: tool.annotations for tool in await mcp.list_tools()}
    for name in ("search_tools", "call_tool", "plan_query"):
        annotations = visible[name]
        assert annotations is not None, name
        assert annotations.read_only_hint is (
            name != "call_tool" or config.get_transport() != "stdio"
        ), name
        if name != "call_tool":
            assert annotations.open_world_hint is False, name


async def test_every_tool_has_a_title():
    """Claude's connector directory rejects tools without a title."""
    untitled = sorted(tool.name for tool in await mcp._list_tools() if not tool.title)
    untitled += sorted(tool.name for tool in await mcp.list_tools() if not tool.title)
    assert not untitled, f"tools missing a title: {untitled}"


async def test_hosted_exports_and_wrapper_declare_no_file_writes(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")
    expected = _export_annotations()
    assert expected.read_only_hint is True
    assert expected.destructive_hint is False
    assert expected.idempotent_hint is True
    transform = AnnotatedBM25SearchTransform()
    assert transform._make_call_tool().annotations == expected
