from __future__ import annotations

import pytest

from maplestats_mcp.modules._example.tools import example_echo
from maplestats_mcp.shared.errors import InvalidInput


async def test_example_echo_returns_typed_model_with_provenance():
    result = await example_echo("hello")
    assert result.message == "hello"
    assert result.provenance.source == "example"
    assert result.provenance.cached is False


async def test_example_echo_rejects_empty_message():
    with pytest.raises(InvalidInput):
        await example_echo("   ")


async def test_example_echo_passes_lang_through_to_the_client():
    # The template's `lang` must reach the client: errors and provenance follow it.
    with pytest.raises(InvalidInput) as french:
        await example_echo("   ", lang="fr")
    assert "message ne doit pas être vide" in str(french.value)
    assert str(french.value).startswith("Entrée invalide")
    with pytest.raises(InvalidInput) as english:
        await example_echo("   ", lang="en")
    assert str(english.value) == "message must not be empty."
    result = await example_echo("bonjour", lang="fr")
    assert result.provenance.reproduce is not None
    english_result = await example_echo("hello")
    assert result.provenance.reproduce != english_result.provenance.reproduce


def test_docstring_has_use_for_and_keywords():
    doc = example_echo.__doc__ or ""
    assert "Use for:" in doc
    assert "Keywords:" in doc
    assert "Mots-clés :" in doc, "missing a French 'Mots-clés :' line for bilingual tool discovery"
    keywords_line = doc.split("Keywords:")[1].split("Mots-clés :")[0]
    keywords = [k.strip() for k in keywords_line.replace(".", "").split(",") if k.strip()]
    assert len(keywords) >= 8
    mots_cles_line = doc.split("Mots-clés :")[1]
    mots_cles = [k.strip() for k in mots_cles_line.replace(".", "").split(",") if k.strip()]
    assert len(mots_cles) >= 8
