"""French helpers: pick(), raise_localized() and the provincial, municipal and portal licences."""

from __future__ import annotations

import pytest

from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import NBSP, pick


def _licence(source: str, lang: str) -> str:
    prov = make_provenance(source=source, url="", cached=False, schema_name="x", lang=lang)
    return prov.licence or ""


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
        ("nl-opendata", "Licence du gouvernement ouvert – Terre-Neuve-et-Labrador"),
    ],
)
def test_french_licence_names_take_an_en_dash(source: str, name: str):
    assert name in _licence(source, "fr")


def test_french_licence_for_portal_families_and_feeds():
    assert "Les licences diffèrent" in _licence("ckan-on", "fr")
    assert "Chaque flux" in _licence("transit:stm", "fr")
    assert "Statistique Canada" in _licence("transit:statcan", "fr")
    assert "Conditions non précisées" in _licence("epcor", "fr")


def test_english_licence_unchanged():
    assert _licence("yukon-stats", "en").startswith("Open Government Licence - Yukon")
    assert _licence("epcor", "en").startswith("Terms not stated by the publisher (EPCOR)")
