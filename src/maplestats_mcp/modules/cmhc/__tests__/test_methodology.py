"""Tests for cmhc_get_methodology: CMHC's methodology text, kept in methodology.py.

In the Maple Test (2026-11-10) a Rental Market Survey reliability-code question and a
Market Absorption Survey definition question were answered from memory: the first
text was only a docs:// resource, which search_tools does not find, and the second
was not in the server.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from maplestats_mcp.modules.cmhc import client, methodology
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput


def test_rental_market_methodology_has_codes_and_release_rule():
    result = client.get_methodology("rental_market")
    text = " ".join(result.text.split())
    assert "d Poor (use with caution)" in text
    assert "4 or more responding entities" in text
    assert result.source_urls[0] == methodology.RMS_METHODOLOGY_URL
    assert result.resource_uri == "docs://cmhc/rms-methodology"


def test_absorption_methodology_defines_absorbed_and_sold():
    result = client.get_methodology("starts_completions_absorption")
    text = " ".join(result.text.split())
    assert "sold and completed" in text
    assert "non-refundable deposit" in text
    assert "qualified purchaser" in text
    assert "up to 10%" in text  # completion
    assert result.source_urls == [methodology.STARTS_METHODOLOGY_URL]
    assert result.provenance.source == "cmhc"
    assert result.read_on == "2026-11-10"


def test_french_text_and_resource():
    result = client.get_methodology("starts_completions_absorption", lang="fr")
    assert "dépôt non remboursable" in " ".join(result.text.split())
    assert result.resource_uri == "docs://cmhc/fr/methodologie-mises-en-chantier"
    assert result.title.startswith("Relevé des mises en chantier")


def test_unknown_survey_is_invalid_input():
    with pytest.raises(InvalidInput, match="starts_completions_absorption"):
        client.get_methodology("household_survey")


async def test_search_tools_finds_the_methodology_tool():
    async with Client(mcp) as session:
        for query in (
            "CMHC Market Absorption Survey absorbed unit definition sold",
            "CMHC Rental Market Survey reliability code D minimum responding entities",
            "SCHL définition logement écoulé",
        ):
            found = await session.call_tool("search_tools", {"query": query})
            assert found.structured_content is not None
            names = [tool["name"] for tool in found.structured_content["result"]]
            assert "cmhc_get_methodology" in names[:3], (query, names)


async def test_resources_serve_the_same_text():
    async with Client(mcp) as session:
        page = await session.read_resource("docs://cmhc/starts-absorption-methodology")
        assert page[0].text == methodology.STARTS_METHODOLOGY_DOC  # type: ignore[union-attr]
