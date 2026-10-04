"""The accent- and plural-folding search tokenizer is installed and works."""

from __future__ import annotations

from fastmcp.server.transforms.search import bm25

from maplestats_mcp import server  # noqa: F401 - installs the tokenizer
from maplestats_mcp.shared.search import tokenize


def test_tokenizer_is_installed_in_fastmcp_bm25():
    assert bm25._tokenize is tokenize


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
