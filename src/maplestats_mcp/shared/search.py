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
from collections.abc import Sequence
from typing import Any

from fastmcp.server.transforms.search import bm25
from fastmcp.server.transforms.search.base import serialize_tools_for_output_json
from fastmcp.tools.base import Tool

_WORD = re.compile(r"[^\W_]{2,}")

# French function words, without accents. Every Mots-clés line is full of
# them, so a query like "taux de chômage par province" was won by the tool
# with the most "de" and "par" (phac_infobase_query, 2026-10-03) rather than
# the one about unemployment. Question words and pronouns ("comment",
# "sont", "vous") are dropped for the same reason. Two-letter words that are
# also codes (ma, ne, se, sa: US states, countries) are kept.
# site/assets/site.js keeps the same list (tests/test_search.py checks it).
STOP_WORDS = frozenset(
    [
        "ainsi",
        "au",
        "autre",
        "autres",
        "aux",
        "avec",
        "avoir",
        "ce",
        "ces",
        "cette",
        "ceux",
        "chaque",
        "chez",
        "combien",
        "comment",
        "dans",
        "de",
        "des",
        "dont",
        "du",
        "elle",
        "elles",
        "en",
        "entre",
        "est",
        "et",
        "etre",
        "ils",
        "je",
        "la",
        "le",
        "les",
        "leur",
        "leurs",
        "lors",
        "mes",
        "mon",
        "nos",
        "notre",
        "nous",
        "ou",
        "par",
        "pas",
        "pour",
        "pourquoi",
        "qu",
        "quand",
        "que",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "qui",
        "quoi",
        "sans",
        "ses",
        "sont",
        "sur",
        "tous",
        "tout",
        "toute",
        "toutes",
        "tres",
        "un",
        "une",
        "vers",
        "vos",
        "votre",
        "vous",
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


# Every result model embeds the same Provenance schema, about 1.9 KB of field
# descriptions once inlined, and search_tools returns five tools at a time:
# 9.7 KB of a 22 KB answer on 2026-10-14 was five identical copies. The caller
# needs the tool's input schema to build a call, not the wording of a block
# that is the same everywhere, so search results carry this stub instead. The
# tools' own schemas, and so every real result, are unchanged.
PROVENANCE_STUB: dict[str, Any] = {
    "type": "object",
    "description": (
        "Where the result came from, the same in every tool: source, url, queried_at "
        "(datetime), cached (bool), schema_name and reproduce, plus as_of (datetime), "
        "freshness, coverage, limits and licence when known."
    ),
}
_PROVENANCE_REF = "#/$defs/Provenance"
# What marks the shared model: another field that happens to be called
# "provenance" keeps its own schema.
_PROVENANCE_FIELDS = {"schema_name", "queried_at"}


def _refers_to(value: Any, ref: str) -> bool:
    if isinstance(value, dict):
        return value.get("$ref") == ref or any(_refers_to(v, ref) for v in value.values())
    if isinstance(value, list):
        return any(_refers_to(v, ref) for v in value)
    return False


def _is_provenance(schema: Any, defs: dict[str, Any]) -> bool:
    """The shared Provenance schema, inlined or as a `$ref` into `$defs`."""
    if not isinstance(schema, dict):
        return False
    if schema.get("$ref") == _PROVENANCE_REF:
        schema = defs.get("Provenance", {})
    return _PROVENANCE_FIELDS <= set(schema.get("properties", {}))


def collapse_provenance(schema: Any) -> None:
    """Replace the shared Provenance schema inside one output schema, in place.

    The server's middleware inlines every `$ref` before results are built, so
    the block normally arrives inline; the `$ref` form is handled too, for a
    transform run without that middleware. Its `$defs` entry is dropped only
    when nothing else in the schema still points at it.
    """
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    defs = schema.get("$defs", {})
    if not isinstance(properties, dict) or not isinstance(defs, dict):
        return
    if not _is_provenance(properties.get("provenance"), defs):
        return
    properties["provenance"] = dict(PROVENANCE_STUB)
    rest = {key: value for key, value in schema.items() if key != "$defs"}
    other_defs = {key: value for key, value in defs.items() if key != "Provenance"}
    if "Provenance" in defs and not (
        _refers_to(rest, _PROVENANCE_REF) or _refers_to(other_defs, _PROVENANCE_REF)
    ):
        del defs["Provenance"]
        if not defs:
            del schema["$defs"]


def serialize_tools_compact(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    """Search results in list_tools format, with the Provenance schema collapsed."""
    results = serialize_tools_for_output_json(tools)
    for result in results:
        collapse_provenance(result.get("outputSchema"))
    return results
