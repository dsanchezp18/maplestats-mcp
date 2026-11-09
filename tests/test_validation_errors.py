"""Bad arguments come back as one readable InvalidInput line, not pydantic's text."""

from __future__ import annotations

import pytest
from fastmcp import Client

from maplestats_mcp.server import mcp


async def _error_text(name: str, arguments: dict, *, via_call_tool: bool) -> str:
    async with Client(mcp) as client:
        if via_call_tool:
            result = await client.call_tool(
                "call_tool", {"name": name, "arguments": arguments}, raise_on_error=False
            )
        else:
            result = await client.call_tool(name, arguments, raise_on_error=False)
    assert result.is_error
    return getattr(result.content[0], "text", "")


@pytest.mark.parametrize("via_call_tool", [False, True])
@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("pmprb_search_patented_medicines", {"year": 2019}, "year must be one of"),
        ("fcac_search_credit_cards", {"province": "ZZ"}, "(got 'ZZ')"),
        (
            "ircc_list_express_entry_rounds",
            {"since": "2025-02-30"},
            "since must be a real date as YYYY-MM-DD (got '2025-02-30')",
        ),
        ("gazette_list_issues", {"part": 3}, "part must be one of 1 or 2 (got 3)"),
    ],
)
async def test_bad_arguments_are_one_clean_line(name, arguments, expected, via_call_tool):
    text = await _error_text(name, arguments, via_call_tool=via_call_tool)
    assert text.startswith(f"[invalid_input] Invalid input: {name}: ")
    assert expected in text
    assert "pydantic" not in text and "validation error" not in text
    assert "\n" not in text


async def test_unknown_keyword_lists_the_parameters():
    text = await _error_text(
        "boc_get_observations", {"series_names": "FXUSDCAD", "bogus": 1}, via_call_tool=True
    )
    assert "bogus is not a parameter of this tool" in text
    assert "parameters: " in text and "series_names" in text


async def test_french_call_gets_a_french_message():
    text = await _error_text(
        "fcac_search_credit_cards", {"province": "ZZ", "lang": "fr"}, via_call_tool=False
    )
    assert text.startswith(
        "[invalid_input] Entrée invalide : fcac_search_credit_cards : province doit valoir"
    )
    assert "(reçu 'ZZ')" in text


async def test_errors_raised_by_a_tool_body_are_untouched():
    text = await _error_text("no_such_tool_anywhere", {}, via_call_tool=True)
    assert "Unknown tool" in text


async def test_upstream_model_failure_is_not_reported_as_invalid_input():
    from fastmcp import FastMCP
    from pydantic import BaseModel

    from maplestats_mcp.shared.validation import ValidationErrorMiddleware

    class Row(BaseModel):
        value: int

    server = FastMCP("t")
    server.add_middleware(ValidationErrorMiddleware())

    @server.tool
    async def upstream_shaped(q: str) -> str:
        Row(value="not-a-number")  # type: ignore[arg-type]
        return q

    async with Client(server) as client:
        result = await client.call_tool("upstream_shaped", {"q": "ok"}, raise_on_error=False)
        bad_args = await client.call_tool("upstream_shaped", {"q": 1}, raise_on_error=False)
    assert result.is_error
    assert "Invalid input" not in result.content[0].text  # type: ignore[union-attr]
    assert "not-a-number" not in result.content[0].text  # type: ignore[union-attr]
    assert bad_args.is_error
    assert bad_args.content[0].text.startswith("Invalid input: upstream_shaped")  # type: ignore[union-attr]


async def test_call_tool_gives_the_full_input_schema_on_bad_arguments():
    # search_tools answers a one-line signature with long enums cut to a count, so an
    # invalid call carries the tool's whole input schema: the next call can be right.
    import json

    text = await _error_text(
        "ckan_search_datasets", {"portal": "atlantis", "query": "x"}, via_call_tool=True
    )
    assert text.startswith("[invalid_input] Invalid input: ckan_search_datasets: portal")
    marker = "Full input schema of ckan_search_datasets: "
    assert marker in text
    schema = json.loads(text.split(marker, 1)[1])
    assert "federal" in schema["properties"]["portal"]["enum"]
    assert schema["required"] == ["portal"]


async def test_full_input_schema_is_introduced_in_french():
    text = await _error_text(
        "fcac_search_credit_cards", {"province": "ZZ", "lang": "fr"}, via_call_tool=True
    )
    assert "Schéma d'entrée complet de fcac_search_credit_cards : {" in text


async def test_only_argument_errors_carry_the_schema():
    # The schema rides on call_tool's argument errors only: an unknown name has none to
    # give, and a client calling a tool by name already listed its schema.
    text = await _error_text("no_such_tool_anywhere", {}, via_call_tool=True)
    assert "input schema" not in text
    direct = await _error_text("ckan_search_datasets", {"portal": "atlantis"}, via_call_tool=False)
    assert "Full input schema" not in direct
