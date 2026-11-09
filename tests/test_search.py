"""The accent- and plural-folding search tokenizer is the one search_tools uses, and works."""

from __future__ import annotations

import pytest

from maplestats_mcp import server
from maplestats_mcp.shared.search import tokenize


async def test_search_tools_folds_accents_and_plurals():
    # The server's own index tokenizes with tokenize(), so a French plural with
    # accents finds the tool its singular, accent-free keyword names.
    transform = server.AnnotatedBM25SearchTransform(max_results=5, mode="bm25")
    tools = await server.searchable_tools(server.mcp)
    assert [t.name for t in await transform._search(tools, "hôpitaux")] == [
        t.name for t in await transform._search(tools, "hopital")
    ]


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


async def test_search_results_carry_what_a_call_needs():
    # A search result is read to build a call: name, description, input schema.
    # The output schema and the Keywords / Mots-clés lines (for ranking only) were
    # most of a 15.7 KB answer on 2026-11-03 and are left out.
    from fastmcp.server.transforms.search.base import serialize_tools_for_output_json

    from maplestats_mcp.shared.search import RESULT_FIELDS, serialize_tools_compact

    tools = [
        tool
        for tool in await server.mcp._list_tools()
        if tool.name in {"wds_get_full_table_download", "wds_get_data_from_vectors"}
    ]
    assert len(tools) == 2
    full = serialize_tools_for_output_json(tools)
    compact = serialize_tools_compact(tools)
    for before, after in zip(full, compact, strict=True):
        assert set(after) <= set(RESULT_FIELDS)
        assert "outputSchema" not in after
        assert after["name"] == before["name"]
        assert after["inputSchema"] == before["inputSchema"]
        # Re-read on every later turn, so the title and a read-only tool's
        # annotations are left out (2026-11-04, cost).
        assert "title" not in after and "annotations" not in after
        assert "Use for:" in after["description"]
        assert "Keywords" not in after["description"]
        assert "Mots-clés" not in after["description"]
        assert before["description"].startswith(after["description"])
    # The tools' own schemas, which real results are checked against, are unchanged.
    live = {tool.name: tool for tool in await server.mcp._list_tools()}
    schema = live["wds_get_full_table_download"].output_schema
    assert schema is not None
    assert "schema_name" in schema["$defs"]["Provenance"]["properties"]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Get X.\n\nUse for: y.\nKeywords: a, b.\nMots-clés : c, d.", "Get X.\n\nUse for: y."),
        # A label that runs on from the last sentence, as a few docstrings have it.
        ("Get X.\n\nUse for: y. Keywords: a, b.\nMots-clés : c.", "Get X.\n\nUse for: y."),
        ("Get X.\n\nUse for: y.\nMots-clés : c.", "Get X.\n\nUse for: y."),
        ("Get X.", "Get X."),
        ("", ""),
        (None, None),
    ],
)
def test_caller_description_drops_the_ranking_lines(description, expected):
    from maplestats_mcp.shared.search import caller_description

    assert caller_description(description) == expected


async def test_search_ranks_on_the_keywords_it_no_longer_returns():
    # "loyers" (rents) is only in Mots-clés lines; the ranking still reads them.
    from fastmcp import Client

    async with Client(server.mcp) as client:
        result = await client.call_tool("search_tools", {"query": "loyers"})
    assert result.structured_content is not None
    found = result.structured_content["result"]
    assert found
    assert all("Mots-clés" not in (tool.get("description") or "") for tool in found)


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
    # A ratio against the same tools' full definitions, not an absolute size, so
    # the check holds when a docstring grows and fails if the output schemas return.
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
    assert len(json.dumps(found)) < 0.5 * len(json.dumps(full))
    if query == "full table download csv":
        assert "wds_get_full_table_download" in [tool["name"] for tool in found]


def test_search_results_keep_annotations_of_a_tool_that_writes():
    # A tool that writes (reproduce_workbook with local exports on) keeps its hints:
    # the one case where they tell the caller something.
    from fastmcp.tools import Tool
    from mcp.types import ToolAnnotations

    from maplestats_mcp.shared.search import serialize_tools_compact

    def save_file(path: str) -> str:
        """Save a file."""
        return path

    writes = Tool.from_function(
        save_file,
        annotations=ToolAnnotations(title="Save", read_only_hint=False, destructive_hint=True),
    )
    reads = Tool.from_function(
        save_file, name="read", annotations=ToolAnnotations(read_only_hint=True)
    )
    kept, dropped = serialize_tools_compact([writes, reads])
    assert kept["annotations"] == {"readOnlyHint": False, "destructiveHint": True}
    assert "annotations" not in dropped


async def test_search_tools_answers_one_line_per_tool_by_default():
    # 2026-11-09, for cost: name, one-line description, one-line argument signature,
    # about a quarter of the compact definition; detail="full" returns that definition.
    import json

    from fastmcp import Client

    from maplestats_mcp.shared.search import BRIEF_FIELDS, serialize_tools_compact

    query = "consumer price index monthly"
    async with Client(server.mcp) as client:
        brief = await client.call_tool("search_tools", {"query": query})
        full = await client.call_tool("search_tools", {"query": query, "detail": "full"})
    assert brief.structured_content is not None and full.structured_content is not None
    short, whole = brief.structured_content["result"], full.structured_content["result"]
    assert [t["name"] for t in short] == [t["name"] for t in whole]
    live = {tool.name: tool for tool in await server.mcp._list_tools()}
    assert whole == serialize_tools_compact([live[t["name"]] for t in whole])
    for tool in short:
        assert set(tool) <= set(BRIEF_FIELDS)
        assert "inputSchema" not in tool
        assert "\n" not in tool["description"] and "Use for:" not in tool["description"]
        assert tool["arguments"].startswith("{") and tool["arguments"].endswith("}")
    assert len(json.dumps(short)) < 0.35 * len(json.dumps(whole))


def test_signature_names_types_and_what_is_optional():
    from maplestats_mcp.shared.search import signature

    schema = {
        "properties": {
            "product_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            "vector_ids": {"type": "array", "items": {"type": "integer"}},
            "since": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]},
            "lang": {"enum": ["en", "fr"], "type": "string", "default": "en"},
            "year": {"enum": [2016, 2021], "type": "integer"},
            "filters": {"$ref": "#/$defs/Filters"},
        },
        "required": ["product_id", "vector_ids"],
    }
    assert signature(schema) == (
        '{product_id: int|str, vector_ids: int[], since?: date, lang?: "en"|"fr", '
        "year?: 2016|2021, filters?: object}"
    )
    assert signature({"properties": {}}) == "{}"
    assert signature(None) == "{}"


def test_signature_cuts_a_long_enum_to_a_count():
    from maplestats_mcp.shared.search import schema_type

    portals = [f"portal_number_{i}" for i in range(40)]
    text = schema_type({"enum": portals, "type": "string"})
    assert text.startswith('"portal_number_0"|')
    assert text.endswith("|... (40 values)")
    assert len(text) < 120
    # A short one stays whole.
    assert schema_type({"enum": ["a", "b"]}) == '"a"|"b"'


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Get X for Y.\n\nUse for: z.\nKeywords: a.", "Get X for Y."),
        ("Get X\nfor Y.\n\nUse for: z.", "Get X for Y."),
        ("Get A. " + "Then b " * 50 + "\n\nUse for: z.", "Get A."),
        (None, ""),
    ],
)
def test_brief_description_is_the_first_paragraph(description, expected):
    from maplestats_mcp.shared.search import brief_description

    assert brief_description(description) == expected


def test_brief_search_results_keep_annotations_of_a_tool_that_writes():
    from fastmcp.tools import Tool
    from mcp.types import ToolAnnotations

    from maplestats_mcp.shared.search import serialize_tools_brief

    def save_file(path: str) -> str:
        """Save a file."""
        return path

    writes = Tool.from_function(
        save_file, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True)
    )
    [result] = serialize_tools_brief([writes])
    assert result == {
        "name": "save_file",
        "description": "Save a file.",
        "arguments": "{path: str}",
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    }
