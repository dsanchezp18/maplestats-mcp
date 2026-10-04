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


def test_pick_adds_a_missing_space_but_leaves_urls():
    text = pick("fr", "", "6 heures; le taux est de 12% (voir https://a.b/?q=1;x%20y).")
    assert f"heures{NBSP}; le" in text
    assert f"12{NBSP}%" in text
    assert "https://a.b/?q=1;x%20y)." in text
    assert pick("fr", "", text) == text


def test_shared_errors_have_french_twins():
    # A typed error built from a bare string in shared/ reaches a French call
    # in English; shared helpers raise through fr_typography.call_error (or
    # take lang) so each message has its French twin.
    import ast
    import pathlib

    from maplestats_mcp import shared

    typed = {"InvalidInput", "NotFound", "UpstreamError", "UpstreamUnavailable", "DataLocked"}
    english_only = []
    for path in sorted(pathlib.Path(shared.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in typed
                and node.args
                and isinstance(node.args[0], ast.Constant | ast.JoinedStr | ast.BinOp)
            ):
                english_only.append(f"{path.name}:{node.lineno}")
    assert not english_only, english_only


def test_shared_helpers_follow_the_call_language():
    from maplestats_mcp.shared.arg_checks import check_choice, check_range
    from maplestats_mcp.shared.i18n import reset_call_lang, set_call_lang

    with pytest.raises(InvalidInput) as english:
        check_range(2020, 2010, "year_from", "year_to")
    assert str(english.value) == (
        "year_from (2020) is after year_to (2010); swap them or widen the range."
    )
    token = set_call_lang("fr")
    try:
        with pytest.raises(InvalidInput) as french:
            check_range(2020, 2010, "year_from", "year_to")
        with pytest.raises(InvalidInput) as choice:
            check_choice("x", ["a", "b"], "class")
    finally:
        reset_call_lang(token)
    assert str(french.value).startswith(f"Entrée invalide{NBSP}: year_from (2020) est postérieur")
    assert f"Valeurs valides{NBSP}: a, b." in str(choice.value)


async def test_call_language_middleware_sets_french_for_the_tool_call():
    from types import SimpleNamespace

    from maplestats_mcp.shared.i18n import call_lang
    from maplestats_mcp.shared.validation import CallLanguageMiddleware

    message = SimpleNamespace(
        name="call_tool", arguments={"name": "x", "arguments": {"lang": "fr-CA"}}
    )

    async def call_next(context):
        return call_lang()

    middleware = CallLanguageMiddleware()
    assert await middleware.on_call_tool(SimpleNamespace(message=message), call_next)  # type: ignore[arg-type] == "fr"
    assert call_lang() == "en"
    plain = SimpleNamespace(name="wds_get_cube_metadata", arguments={"product_id": 1})
    assert await middleware.on_call_tool(SimpleNamespace(message=plain), call_next)  # type: ignore[arg-type] == "en"
