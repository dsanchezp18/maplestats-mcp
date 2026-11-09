"""docs_list_resources and docs_read_resource serve the docs:// pages through call_tool.

Hosted clients often show the model only search_tools, call_tool and
plan_query, so a description saying "read docs://cmhc/gotchas" was a dead
end there. These tools must return exactly what resources/read returns.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Client
from mcp.types import TextContent, TextResourceContents

from maplestats_mcp.server import mcp


async def _call(client: Client, name: str, arguments: dict[str, object]) -> dict:
    result = await client.call_tool(
        "call_tool", {"name": name, "arguments": arguments, "detail": "full"}
    )
    return json.loads(_text(result.content))


def _text(content: list[Any]) -> str:
    return "".join(c.text for c in content if isinstance(c, TextContent))


async def _resource_text(client: Client, uri: str) -> str:
    contents = await client.read_resource(uri)
    return "".join(c.text for c in contents if isinstance(c, TextResourceContents))


async def test_read_returns_the_resource_text():
    async with Client(mcp) as client:
        for uri in ("docs://cmhc/gotchas", "docs://catalogue", "docs://cmhc/rms-methodology"):
            data = await _call(client, "docs_read_resource", {"uri": uri})
            assert data["uri"] == uri
            assert data["text"] == await _resource_text(client, uri)


async def test_read_in_french_returns_the_french_twin():
    async with Client(mcp) as client:
        data = await _call(
            client, "docs_read_resource", {"uri": "docs://cmhc/rms-methodology", "lang": "fr"}
        )
        assert data["uri"] == "docs://cmhc/fr/methodologie-ell"
        assert "Enquête sur les logements locatifs" in data["text"]


async def test_list_covers_every_docs_resource_once_per_language():
    async with Client(mcp) as client:
        served = {str(r.uri) for r in await client.list_resources()}
        docs = {uri for uri in served if uri.startswith("docs://")}
        english = {p["uri"] for p in (await _call(client, "docs_list_resources", {}))["pages"]}
        french = {
            p["uri"] for p in (await _call(client, "docs_list_resources", {"lang": "fr"}))["pages"]
        }
    assert english <= docs and french <= docs
    assert "docs://cmhc/rms-methodology" in english
    assert "docs://cmhc/fr/methodologie-ell" not in english
    assert "docs://cmhc/fr/methodologie-ell" in french
    assert "docs://cmhc/rms-methodology" not in french
    # every page is listed in at least one language
    assert english | french == docs


async def test_unknown_or_foreign_uri_is_a_clear_error():
    async with Client(mcp) as client:
        missing = await client.call_tool(
            "call_tool",
            {"name": "docs_read_resource", "arguments": {"uri": "docs://cmhc/nope"}},
            raise_on_error=False,
        )
        assert missing.is_error
        assert "docs://cmhc/gotchas" in _text(missing.content)  # nearby pages offered
        foreign = await client.call_tool(
            "call_tool",
            {"name": "docs_read_resource", "arguments": {"uri": "file:///etc/passwd"}},
            raise_on_error=False,
        )
        assert foreign.is_error
        assert "docs://" in _text(foreign.content)


async def test_search_tools_finds_the_reader():
    async with Client(mcp) as client:
        for query in ("read a docs:// resource", "lire la documentation du serveur"):
            result = await client.call_tool("search_tools", {"query": query})
            names = [tool["name"] for tool in json.loads(_text(result.content))]
            assert "docs_read_resource" in names[:3], (query, names)
