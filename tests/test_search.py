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


async def test_search_tools_answers_with_compact_results():
    import json

    from fastmcp import Client

    async with Client(server.mcp) as client:
        result = await client.call_tool("search_tools", {"query": "full table download csv"})
    assert result.structured_content is not None
    tools = result.structured_content["result"]
    assert "wds_get_full_table_download" in [tool["name"] for tool in tools]
    # Not a byte cap, which a few longer docstrings would break for an unrelated
    # reason: the Provenance wording must be gone from every result.
    assert "how fresh/complete it is" not in json.dumps(tools)
    assert "Update cadence in plain language" not in json.dumps(tools)


def _provenance_schema() -> dict:
    return {
        "type": "object",
        "properties": {"source": {"type": "string"}, "queried_at": {}, "schema_name": {}},
    }


def test_collapse_inlined_provenance():
    from maplestats_mcp.shared.search import PROVENANCE_STUB, collapse_provenance

    schema = {"properties": {"rows": {"type": "array"}, "provenance": _provenance_schema()}}
    collapse_provenance(schema)
    assert schema["properties"]["provenance"] == PROVENANCE_STUB
    assert schema["properties"]["rows"] == {"type": "array"}


def test_collapse_ref_provenance_drops_its_definition():
    from maplestats_mcp.shared.search import PROVENANCE_STUB, collapse_provenance

    schema = {
        "properties": {"provenance": {"$ref": "#/$defs/Provenance"}},
        "$defs": {"Provenance": _provenance_schema()},
    }
    collapse_provenance(schema)
    assert schema["properties"]["provenance"] == PROVENANCE_STUB
    assert "$defs" not in schema


def test_collapse_keeps_a_definition_something_else_still_uses():
    from maplestats_mcp.shared.search import collapse_provenance

    schema = {
        "properties": {
            "provenance": {"$ref": "#/$defs/Provenance"},
            "items": {
                "type": "array",
                "items": {"properties": {"p": {"$ref": "#/$defs/Provenance"}}},
            },
        },
        "$defs": {"Provenance": _provenance_schema()},
    }
    collapse_provenance(schema)
    assert "Provenance" in schema["$defs"]
    # The reference left behind still resolves.
    assert schema["properties"]["items"]["items"]["properties"]["p"] == {
        "$ref": "#/$defs/Provenance"
    }


def test_collapse_leaves_a_foreign_provenance_field_alone():
    from maplestats_mcp.shared.search import collapse_provenance

    foreign = {"type": "object", "properties": {"source": {"type": "string"}}}
    schema = {"properties": {"provenance": dict(foreign)}}
    collapse_provenance(schema)
    assert schema["properties"]["provenance"] == foreign
    # A field called schema_name alone is not the shared model either.
    schema = {"properties": {"provenance": {"properties": {"schema_name": {}}}}}
    collapse_provenance(schema)
    assert schema["properties"]["provenance"] == {"properties": {"schema_name": {}}}


@pytest.mark.parametrize("schema", [None, {}, {"properties": []}, {"properties": {}}])
def test_collapse_ignores_schemas_without_provenance(schema):
    from maplestats_mcp.shared.search import collapse_provenance

    before = repr(schema)
    collapse_provenance(schema)
    assert repr(schema) == before


def test_tool_without_an_output_schema_is_serialized_unchanged():
    from fastmcp.server.transforms.search.base import serialize_tools_for_output_json
    from fastmcp.tools import Tool

    from maplestats_mcp.shared.search import serialize_tools_compact

    def ping(text: str) -> str:
        """Echo."""
        return text

    tool = Tool.from_function(ping)
    assert serialize_tools_compact([tool]) == serialize_tools_for_output_json([tool])
