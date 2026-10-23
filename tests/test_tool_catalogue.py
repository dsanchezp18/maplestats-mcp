"""tool_catalogue.json matches the code, and the lazy server matches the eager one.

The server lists and searches tools from the catalogue and imports a module
only when one of its tools is called (see maplestats_mcp/catalogue.py), so a
stale catalogue would show clients last week's tools. Regenerate it with
`uv run python scripts/build_tool_catalogue.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from maplestats_mcp import server
from maplestats_mcp.catalogue import (
    CATALOGUE_PATH,
    TOOL_SWITCHES,
    build_catalogue,
    module_dirs,
    read_catalogue,
)

REGENERATE = "run `uv run python scripts/build_tool_catalogue.py` and commit the result"


def _listing(tools) -> dict[str, dict]:
    return {tool.name: tool.to_mcp_tool().model_dump(mode="json") for tool in tools}


def test_catalogue_is_current():
    expected = build_catalogue()
    assert CATALOGUE_PATH.read_text(encoding="utf-8") == expected, (
        f"tool_catalogue.json is stale: {REGENERATE}"
    )


async def test_lazy_listing_equals_the_eager_one():
    """Every field tools/list and search_tools show, compared tool by tool."""
    eager = []
    for root in module_dirs():
        eager.extend(await server.ModuleProvider(root=root)._list_tools())
    lazy = await server.mcp._list_tools()
    lazy_modules = [p for p in server.mcp.providers if isinstance(p, server.LazyModuleProvider)]
    assert len(lazy_modules) == len(module_dirs())
    assert _listing(lazy) == _listing(eager)


def test_every_switch_names_a_catalogued_tool():
    catalogue = read_catalogue()
    assert catalogue is not None
    names = {tool["name"] for module in catalogue.values() for tool in module["tools"]}
    assert set(TOOL_SWITCHES) <= names


def test_missing_or_other_format_catalogue_reads_as_none(tmp_path: Path):
    assert read_catalogue(tmp_path / "absent.json") is None
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"format": 0, "modules": {}}), encoding="utf-8")
    assert read_catalogue(old) is None


async def test_module_missing_from_catalogue_loads_eagerly(monkeypatch: pytest.MonkeyPatch):
    catalogue = read_catalogue()
    assert catalogue is not None
    monkeypatch.setattr(
        server, "read_catalogue", lambda: {k: v for k, v in catalogue.items() if k != "cdc"}
    )
    rebuilt = server.build_server()
    eager = [p for p in rebuilt.providers if isinstance(p, server.ModuleProvider)]
    assert [p._root.name for p in eager] == ["cdc"]
    assert _listing(await rebuilt._list_tools()) == _listing(await server.mcp._list_tools())


# A fresh interpreter: this test session has imported most modules already.
_FRESH_SERVER = textwrap.dedent(
    """
    import asyncio, json, sys

    from fastmcp import Client

    from maplestats_mcp import server

    def loaded():
        # The provider imports a module folder as its own package ("boc.tools");
        # its clients and schemas keep their full names.
        folders = {root.name for root in server.module_dirs()}
        return sorted(
            {name.split(".")[0] for name in sys.modules if name.split(".")[0] in folders}
            | {
                name.split(".")[2]
                for name in sys.modules
                if name.startswith("maplestats_mcp.modules.") and name.count(".") >= 2
            }
        )

    async def main():
        out = {"startup": loaded()}
        async with Client(server.mcp) as client:
            await client.call_tool("search_tools", {"query": "housing starts"})
            out["after_search"] = loaded()
            await client.call_tool(
                "call_tool",
                {"name": "boc_get_observations", "arguments": {}},
                raise_on_error=False,
            )
            out["after_call"] = loaded()
        lazy = {tool.name for tool in await server.mcp._list_tools()}
        eager = set()
        for root in server.module_dirs():
            eager |= {tool.name for tool in await server.ModuleProvider(root=root)._list_tools()}
        out["only_lazy"] = sorted(lazy - eager)
        out["only_eager"] = sorted(eager - lazy)
        out["tabulate"] = await server.mcp.get_tool("statcan_pumf_tabulate") is not None
        print(json.dumps(out))

    asyncio.run(main())
    """
)


def test_fresh_server_imports_a_module_only_when_called():
    """Run with MAPLE_PUMF_TABULATE=0, which also checks the switches: a tool a
    setting hides must be missing from the catalogue listing too."""
    env = {**os.environ, "MAPLE_PUMF_TABULATE": "0"}
    done = subprocess.run(
        [sys.executable, "-c", _FRESH_SERVER],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=600,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["startup"] == []
    assert out["after_search"] == []
    assert out["after_call"] == ["boc"]
    assert out["only_lazy"] == [] and out["only_eager"] == [], f"add it to TOOL_SWITCHES: {out}"
    assert out["tabulate"] is False
