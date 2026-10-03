"""SERVER_INSTRUCTIONS must route every live tool by its name prefix.

The routing index is hand-written, so a new module whose prefix is not
added to it is invisible to a client that reads the instructions; four
live prefixes went missing that way before this check existed.
"""

from __future__ import annotations

import re

from maplestats_mcp.server import SERVER_INSTRUCTIONS, mcp

# Tools named in full in the instructions rather than by prefix.
_NAMED_IN_FULL = {"search_tools", "call_tool", "plan_query", "reproduce_code", "reproduce_workbook"}

_PREFIX_TOKEN = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)*_)(?![a-z0-9])")
_NAME_TOKEN = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")


def _listed_prefixes() -> set[str]:
    return set(_PREFIX_TOKEN.findall(SERVER_INSTRUCTIONS))


async def _tool_names() -> set[str]:
    return {tool.name for tool in await mcp._list_tools()}


async def test_every_live_tool_prefix_is_routed():
    prefixes = _listed_prefixes()
    names = await _tool_names()
    unrouted = sorted(
        name
        for name in names
        if name not in _NAMED_IN_FULL
        and name not in SERVER_INSTRUCTIONS
        and not any(name.startswith(prefix) for prefix in prefixes)
    )
    assert not unrouted, (
        "Tools whose prefix is missing from SERVER_INSTRUCTIONS in server.py "
        f"(add the module's prefix to the routing index): {unrouted}"
    )


async def test_every_listed_prefix_matches_a_live_tool():
    names = await _tool_names()
    stale = sorted(
        prefix
        for prefix in _listed_prefixes()
        if not any(name.startswith(prefix) for name in names)
    )
    assert not stale, f"SERVER_INSTRUCTIONS lists prefixes with no live tool: {stale}"


async def test_tool_names_written_in_full_exist():
    names = await _tool_names()
    full_names = {
        token
        for token in _NAME_TOKEN.findall(SERVER_INSTRUCTIONS)
        if any(token.startswith(prefix) for prefix in _listed_prefixes())
    }
    missing = sorted(full_names - names)
    assert not missing, f"SERVER_INSTRUCTIONS names tools that do not exist: {missing}"


def test_portal_counts_are_not_hard_coded():
    # Portal families grow by one constants entry at a time; a count in
    # this text goes stale on the next addition.
    assert not re.search(r"\(\d+ (provinces|portals|cities)", SERVER_INSTRUCTIONS)
