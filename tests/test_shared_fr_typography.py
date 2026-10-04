"""Tests for shared/fr_typography.py and the French licences it relies on."""

from __future__ import annotations

from maplestats_mcp.shared import licences
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.fr_typography import NBSP, fr_or_en, lang_error, truncation_note_lang


def test_fr_or_en():
    assert fr_or_en("en", "a: b", "a : b") == "a: b"
    assert fr_or_en("fr", "a: b", "a : b") == f"a{NBSP}: b"


def test_lang_error_keeps_english_and_templates_french():
    assert str(lang_error(InvalidInput, "en", "bad: x", "mauvais : x")) == "bad: x"
    fr = lang_error(NotFound, "fr", "none", "aucun résultat")
    assert isinstance(fr, NotFound)
    assert str(fr) == f"Aucune correspondance trouvée{NBSP}: aucun résultat"


def test_truncation_note_lang():
    english = truncation_note_lang("en", returned=2, total=5, unit="points", order="latest")
    assert english == "Returned the most recent 2 of 5 points."
    french = truncation_note_lang(
        "fr", returned=2, total=1500, unit_fr="points", how_to_get_more_fr="raccourcissez"
    )
    assert (
        french
        == f"Résultat limité à 2 points sur 1{NBSP}500 (en début de liste){NBSP}; raccourcissez."
    )
    assert truncation_note_lang("fr", returned=5, total=5) is None


def test_added_french_licences_reach_make_provenance():
    for source, start in [
        ("dfo-iwls", "Conditions non précisées"),
        ("senate", "Propriété intellectuelle du Sénat"),
        ("ourcommons", "Autorisation du Président"),
        ("elections-results", "Avis d'Élections Canada"),
        ("ab_wildfire", "Licence du gouvernement ouvert – Alberta"),
        ("cihi", "Conditions d'utilisation de l'ICIS"),
    ]:
        prov = make_provenance(
            source=source, url="https://x.ca", cached=False, schema_name="s", lang="fr"
        )
        assert (prov.licence or "").startswith(start), source
        english = make_provenance(source=source, url="https://x.ca", cached=False, schema_name="s")
        assert english.licence == licences.licence_for(source, "https://x.ca")
