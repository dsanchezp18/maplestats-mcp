"""Accent- and plural-insensitive tokens for search_tools (BM25).

fastmcp's BM25 tokenizer matches exact word forms, so a French plural
never met its singular keyword: on 2026-09-24 "loyers" and "hôpitaux"
returned no tools at all, and "tremblements de terre" missed
earthquakes_search. Folding accents and plural endings on both the
indexed docstrings and the query fixes this for every tool at once,
and helps English too ("rates" meets "rate", "hopital" meets "hôpital").

fastmcp has no tokenizer hook, so this replaces the module-level
`_tokenize` that its index and queries both call. tests/test_search.py
fails if a fastmcp upgrade moves it.
"""

from __future__ import annotations

import re
import unicodedata

from fastmcp.server.transforms.search import bm25

_WORD = re.compile(r"[^\W_]{2,}")

# French function words, without accents. Every Mots-clés line is full of
# them, so a query like "taux de chômage par province" was won by the tool
# with the most "de" and "par" (phac_infobase_query, 2026-10-03) rather than
# the one about unemployment. site/assets/site.js keeps the same list.
STOP_WORDS = frozenset(
    [
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "cette",
        "dans",
        "de",
        "des",
        "du",
        "en",
        "est",
        "et",
        "la",
        "le",
        "les",
        "ou",
        "par",
        "pour",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "que",
        "qui",
        "sur",
        "un",
        "une",
    ]
)


def _fold(word: str) -> str:
    # hôpitaux -> hopital, journaux -> journal.
    if len(word) > 4 and word.endswith("aux"):
        return word[:-3] + "al"
    # "taux" and "prix" are the same in both numbers; only -eux/-oux drop the x.
    if len(word) > 4 and word.endswith(("eux", "oux")):
        return word[:-1]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    # NFKD leaves the ligatures whole, so "œufs" would never meet "oeufs".
    text = text.casefold().replace("œ", "oe").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return [_fold(word) for word in _WORD.findall(plain) if word not in STOP_WORDS]


def install() -> None:
    bm25._tokenize = tokenize
