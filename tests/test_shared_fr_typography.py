"""Tests for shared/fr_typography.py and shared/licences_fr.py."""

from __future__ import annotations

from maplestats_mcp.shared import licences
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.fr_typography import NBSP, NNBSP, fr_or_en, french_spacing, lang_error
from maplestats_mcp.shared.licences_fr import licence_for_lang, to_french


def test_french_spacing_marks_and_quotes():
    out = french_spacing("Note : 12 % ; voir « x » ? fin ! https://a.ca 12:30")
    assert out == (
        f"Note{NBSP}: 12{NNBSP}%{NNBSP}; voir «{NBSP}x{NBSP}»{NNBSP}? fin{NNBSP}! "
        "https://a.ca 12:30"
    )
    # Already spaced text is unchanged.
    assert french_spacing(out) == out


def test_fr_or_en():
    assert fr_or_en("en", "a: b", "a : b") == "a: b"
    assert fr_or_en("fr", "a: b", "a : b") == f"a{NBSP}: b"


def test_lang_error_keeps_english_and_templates_french():
    assert str(lang_error(InvalidInput, "en", "bad: x", "mauvais : x")) == "bad: x"
    fr = lang_error(NotFound, "fr", "none", "aucun résultat")
    assert isinstance(fr, NotFound)
    assert str(fr) == f"Aucune correspondance trouvée{NBSP}: aucun résultat"


def test_licence_for_lang():
    assert licence_for_lang("cgc", "", "en") == licences.OGL_CANADA
    fr = licence_for_lang("cgc", "", "fr") or ""
    assert fr.startswith("Licence du gouvernement ouvert – Canada")
    assert f"«{NBSP}Contient" in fr
    assert "Avis du gouvernement du Canada" in (licence_for_lang("gazette", "", "fr") or "")
    assert to_french(licences.SENATE_TERMS, "fr") != licences.SENATE_TERMS
    assert to_french("unknown text", "fr") == "unknown text"
