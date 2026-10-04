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
        (
            "elections_provincial_get_results",
            {"province": "QC"},
            "province must be one of 'qc', 'ab', 'bc', 'sk' or 'mb' (got 'QC')",
        ),
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
    assert text.startswith(f"Invalid input: {name}: ")
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
    assert text.startswith("Entrée invalide\u00a0: fcac_search_credit_cards\u00a0: province doit valoir")
    assert "(reçu 'ZZ')" in text


async def test_errors_raised_by_a_tool_body_are_untouched():
    text = await _error_text("no_such_tool_anywhere", {}, via_call_tool=True)
    assert "Unknown tool" in text
