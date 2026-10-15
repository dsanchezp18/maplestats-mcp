"""The accent- and plural-folding search tokenizer is installed and works."""

from __future__ import annotations

import pytest
from fastmcp.server.transforms.search import bm25

from maplestats_mcp import server  # importing it installs the tokenizer
from maplestats_mcp.shared.search import tokenize


def test_tokenizer_is_installed_in_fastmcp_bm25():
    assert bm25._tokenize is tokenize


def test_folds_accents_and_plurals():
    assert tokenize("Hôpitaux loyers séismes rates") == ["hopital", "loyer", "seisme", "rate"]
    assert tokenize("taux census status") == ["taux", "census", "status"]


def test_folds_ligatures():
    assert tokenize("Producteurs d'œufs, Œuvre") == ["producteur", "oeuf", "oeuvre"]
    assert tokenize("oeufs") == ["oeuf"]


def test_drops_french_stop_words():
    assert tokenize("Taux de chômage par province") == ["taux", "chomage", "province"]
    assert tokenize("Quel est le PIB des provinces, à l'été ou à Noël?") == [
        "pib",
        "province",
        "ete",
        "noel",
    ]


def test_site_js_keeps_the_same_stop_words():
    import pathlib
    import re

    from maplestats_mcp.shared.search import STOP_WORDS

    js = pathlib.Path(__file__).parents[1] / "site" / "assets" / "site.js"
    block = re.search(
        r"const STOP_WORDS = new Set\(\s*\((.*?)\)\.split", js.read_text("utf-8"), re.DOTALL
    )
    assert block is not None
    words = set("".join(re.findall(r'"([^"]*)"', block.group(1))).split())
    assert words == set(STOP_WORDS)


async def test_search_results_collapse_the_provenance_schema():
    # Five identical 1.9 KB copies were 43% of a search_tools answer; the stub keeps
    # what a caller needs (input schemas, result fields) and drops the repeat.
    import json

    from fastmcp.server.transforms.search.base import serialize_tools_for_output_json

    from maplestats_mcp.shared.search import PROVENANCE_STUB, serialize_tools_compact

    tools = [
        tool
        for tool in await server.mcp._list_tools()
        if tool.name in {"wds_get_full_table_download", "wds_get_data_from_vectors"}
    ]
    assert len(tools) == 2
    full = serialize_tools_for_output_json(tools)
    compact = serialize_tools_compact(tools)
    for before, after in zip(full, compact, strict=True):
        assert after["inputSchema"] == before["inputSchema"]
        assert after["description"] == before["description"]
        assert after["outputSchema"]["properties"]["provenance"] == PROVENANCE_STUB
        assert set(after["outputSchema"]["properties"]) == set(before["outputSchema"]["properties"])
        assert after["outputSchema"]["required"] == before["outputSchema"]["required"]
    assert len(json.dumps(compact)) < 0.7 * len(json.dumps(full))
    # The tools' own schemas, which real results are checked against, keep the full block.
    live = {tool.name: tool for tool in await server.mcp._list_tools()}
    schema = live["wds_get_full_table_download"].output_schema
    assert schema is not None
    assert "schema_name" in schema["$defs"]["Provenance"]["properties"]


def _ref_result(extra_properties: dict) -> dict:
    """A serialized tool whose output schema points at Provenance through `$ref`."""
    provenance_def = {"type": "object", "properties": {"schema_name": {"type": "string"}}}
    return {
        "name": "fake_tool",
        "outputSchema": {
            "type": "object",
            "properties": {"provenance": {"$ref": "#/$defs/Provenance"}, **extra_properties},
            "$defs": {"Provenance": provenance_def},
        },
    }


def test_compact_serializer_drops_an_unused_provenance_def(monkeypatch):
    from maplestats_mcp.shared import search

    result = _ref_result({})
    monkeypatch.setattr(search, "serialize_tools_for_output_json", lambda tools: [result])
    compact = search.serialize_tools_compact([])
    assert compact[0]["outputSchema"]["properties"]["provenance"] == search.PROVENANCE_STUB
    assert "$defs" not in compact[0]["outputSchema"]


def test_compact_serializer_keeps_a_provenance_def_that_another_field_uses(monkeypatch):
    from maplestats_mcp.shared import search

    result = _ref_result({"previous": {"$ref": "#/$defs/Provenance"}})
    monkeypatch.setattr(search, "serialize_tools_for_output_json", lambda tools: [result])
    schema = search.serialize_tools_compact([])[0]["outputSchema"]
    assert schema["properties"]["provenance"] == search.PROVENANCE_STUB
    assert schema["properties"]["previous"] == {"$ref": "#/$defs/Provenance"}
    assert "schema_name" in schema["$defs"]["Provenance"]["properties"]


@pytest.mark.parametrize(
    "query",
    [
        "full table download csv",
        "population estimates by province",
        "consumer price index monthly",
        "wildfires British Columbia",
        "mortgage rates five-year fixed",
        "Express Entry CRS cutoff latest draw",
    ],
)
async def test_search_tools_answers_with_compact_results(query: str):
    # A ratio against the same tools' uncollapsed schemas, not an absolute size, so
    # the check holds when a docstring grows and fails if the Provenance block returns.
    import json

    from fastmcp import Client
    from fastmcp.server.transforms.search.base import serialize_tools_for_output_json

    async with Client(server.mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    assert result.structured_content is not None
    found = result.structured_content["result"]
    assert found
    live = {tool.name: tool for tool in await server.mcp._list_tools()}
    full = serialize_tools_for_output_json([live[tool["name"]] for tool in found])
    assert len(json.dumps(found)) < 0.8 * len(json.dumps(full))
    if query == "full table download csv":
        assert "wds_get_full_table_download" in [tool["name"] for tool in found]
