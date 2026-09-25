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
