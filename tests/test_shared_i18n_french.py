"""French helpers: typography, pick(), raise_localized() and French licences."""

from __future__ import annotations

import pytest

from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import NBSP, french_spacing, pick
from maplestats_mcp.shared.licences import licence_for


def test_french_spacing_spaces_marks_and_leaves_urls():
    text = french_spacing("Note : voir https://a.b/c?x=1%20y, 50 % « oui » fin!")
    assert f"Note{NBSP}:" in text
    assert "https://a.b/c?x=1%20y" in text
    assert f"50{NBSP}%" in text
    assert f"«{NBSP}oui{NBSP}»" in text
    assert text.endswith(f"fin{NBSP}!")


def test_french_spacing_is_idempotent():
    once = french_spacing("Source : Statistique Canada; voir « ceci » ?")
    assert french_spacing(once) == once


def test_pick_keeps_english_as_written():
    assert pick("en", "Note: x", "Note : x") == "Note: x"
    assert pick("fr-CA", "Note: x", "Note : x") == f"Note{NBSP}: x"


def test_raise_localized_english_is_the_module_message():
    with pytest.raises(InvalidInput) as exc:
        raise_localized(InvalidInput, "plant must be one of ['els'].", "x", "en")
    assert str(exc.value) == "plant must be one of ['els']."


def test_raise_localized_french_uses_the_typed_template():
    with pytest.raises(NotFound) as exc:
        raise_localized(NotFound, "x", "aucune usine « abc ».", "fr")
    assert str(exc.value).startswith(f"Aucune correspondance trouvée{NBSP}:")
    assert f"«{NBSP}abc{NBSP}»" in str(exc.value)


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ("yukon-stats", "Licence du gouvernement ouvert – Yukon"),
        ("ab-opendata", "Licence du gouvernement ouvert – Alberta"),
        ("bcgw", "Licence du gouvernement ouvert – Colombie-Britannique"),
        ("nwt-bureau-of-statistics", "Licence du gouvernement ouvert – Territoires du Nord-Ouest"),
        ("oeb", "Licence du gouvernement ouvert – Ontario"),
    ],
)
def test_french_licence_names_take_an_en_dash(source: str, name: str):
    assert name in (licence_for(source, "", "fr") or "")


def test_french_licence_for_portal_families_and_feeds():
    assert "Les licences varient" in (licence_for("ckan-on", "", "fr") or "")
    assert "Chaque flux" in (licence_for("transit:stm", "", "fr") or "")
    assert "Statistique Canada" in (licence_for("transit:statcan", "", "fr") or "")


def test_english_licence_unchanged_and_french_falls_back():
    assert (licence_for("yukon-stats", "", "en") or "").startswith(
        "Open Government Licence - Yukon"
    )
    # A source with no French text keeps its English text.
    assert (licence_for("crea", "", "fr") or "").startswith("Source: The Canadian Real Estate")


def test_make_provenance_french_licence():
    prov = make_provenance(
        source="epcor", url="https://apps.epcor.ca", cached=False, schema_name="x", lang="fr"
    )
    assert "Conditions non précisées" in (prov.licence or "")
