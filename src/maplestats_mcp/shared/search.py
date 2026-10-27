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

import math
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


class ScoredBM25Index(bm25._BM25Index):
    """fastmcp's BM25 index, with the scores exposed so they can be boosted or fused.

    `query()` returns only the ranked indices; `scores()` is the same Okapi sum
    (same k1, b and idf), so a ranking taken from it with no boost is identical.
    """

    def scores(self, text: str) -> list[float]:
        scores = [0.0] * self._n
        for token in bm25._tokenize(text):
            df = self._df.get(token)
            if not df:
                continue
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
            for i, tf_doc in enumerate(self._tf):
                tf = tf_doc.get(token, 0)
                if tf:
                    norm = 1 - self.b + self.b * self._doc_lengths[i] / self._avg_dl
                    scores[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return scores


# Exact identifiers. The tokenizer splits "14-10-0287-01" into "14", "10",
# "0287", "01", which match stray numbers in docstrings, and "14100287" or
# "v41690973" match nothing at all, so a query that is mostly an identifier
# was ranked by its other words only. An identifier says which tools can take
# it: the ones with the matching parameter. Those tools get a boost relative
# to the best score, so the query's other words still order them ("download"
# puts wds_get_full_table_download first among the table tools).
# A StatCan table number: 14-10-0287-01, 14-10-0287, 1410028701 or 14100287.
# The first digit is never 0 (an 8-digit DIN such as 02242903 starts with 0).
_TABLE_ID = re.compile(r"(?<![\w-])[1-9]\d-?\d{2}-?\d{4}(?:-?\d{2})?(?![\w-])")
# A StatCan vector (v41690973), which is also how old Bank of Canada series are named.
_VECTOR_ID = re.compile(r"(?<!\w)v\d{1,10}(?!\w)", re.IGNORECASE)
# A tool name or a family prefix: lower-case words joined by underscores.
_SNAKE = re.compile(r"(?<!\w)[a-z][a-z0-9]*(?:_[a-z0-9]+)*_?(?!\w)")
# product_id is also a bank-account or credit-card id (fcac_*): table numbers
# belong to the StatCan families only.
_STATCAN_PREFIXES = ("wds_", "sdmx_", "statcan_")
_VECTOR_PARAMS = frozenset({"vector_id", "vector_ids", "series_names"})
# boc_get_series takes a series name as `name`; its docstring shows V-numbers.
_VECTOR_EXAMPLE = re.compile(r"\bV\d{4,}\b")
EXACT_NAME_BOOST = 2.0  # the named tool first, whatever else the query says
IDENTIFIER_BOOST = 1.0  # the tools that take the identifier above the others


def _params(tool: Tool) -> frozenset[str]:
    return frozenset((tool.parameters or {}).get("properties", {}))


def identifier_boosts(query: str, tools: Sequence[Tool]) -> dict[int, tuple[float, str]]:
    """Tool positions to boost for the identifiers in `query`: weight and reason."""
    boosts: dict[int, tuple[float, str]] = {}

    def add(i: int, weight: float, reason: str) -> None:
        if weight > boosts.get(i, (0.0, ""))[0]:
            boosts[i] = (weight, reason)

    lowered = query.casefold()
    words = {w for w in _SNAKE.findall(lowered) if "_" in w}
    has_table = _TABLE_ID.search(query) is not None
    has_vector = _VECTOR_ID.search(query) is not None
    if not (words or has_table or has_vector):
        return boosts
    for i, tool in enumerate(tools):
        name = tool.name
        if name in words:
            add(i, EXACT_NAME_BOOST, "exact tool name")
        elif any(name.startswith(w if w.endswith("_") else w + "_") for w in words):
            add(i, IDENTIFIER_BOOST, "tool family prefix")
        if has_table and "product_id" in _params(tool) and name.startswith(_STATCAN_PREFIXES):
            add(i, IDENTIFIER_BOOST, "takes a StatCan table number")
        if has_vector and (
            _params(tool) & _VECTOR_PARAMS or _VECTOR_EXAMPLE.search(tool.description or "")
        ):
            add(i, IDENTIFIER_BOOST, "takes a vector or series id")
    return boosts


def apply_boosts(scores: list[float], boosts: dict[int, tuple[float, str]]) -> list[float]:
    """Add each boost as a share of the best score, so it means the same for BM25 and fused
    scores; a query that is only an identifier scores nothing, and the share is of 1."""
    if not boosts:
        return scores
    best = max(scores, default=0.0)
    top = best if best > 0 else 1.0
    boosted = list(scores)
    for i, (weight, _) in boosts.items():
        boosted[i] += weight * top
    return boosted


def top_indices(scores: Sequence[float], k: int) -> list[int]:
    """The k best positive scores, best first; ties keep catalogue order, as fastmcp's sort does."""
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [i for i in ranked[:k] if scores[i] > 0]


# Every result model embeds the same Provenance schema, about 1.9 KB of field
# descriptions once inlined, and search_tools returns five tools at a time:
# 9.7 KB of a 22 KB answer on 2026-10-14 was five identical copies. The caller
# needs the tool's input schema to build a call, not the wording of a block
# that is the same everywhere, so search results carry this stub instead. The
# tools' own schemas, and so every real result, are unchanged.
PROVENANCE_STUB: dict[str, Any] = {
    "type": "object",
    "description": (
        "Where the result came from, the same in every tool: source, url, queried_at, "
        "cached and schema_name, plus as_of, freshness, coverage, limits, licence and "
        "reproduce when known."
    ),
}


PROVENANCE_REF = "#/$defs/Provenance"


def _refers_to(node: Any, ref: str) -> bool:
    """Whether any `$ref` anywhere inside `node` points at `ref`."""
    if isinstance(node, dict):
        return node.get("$ref") == ref or any(_refers_to(value, ref) for value in node.values())
    if isinstance(node, list):
        return any(_refers_to(value, ref) for value in node)
    return False


def _is_provenance(schema: Any, defs: dict[str, Any]) -> bool:
    """The shared Provenance schema, inlined or as a `$ref` into `$defs`."""
    if not isinstance(schema, dict):
        return False
    if schema.get("$ref") == PROVENANCE_REF:
        return "schema_name" in defs.get("Provenance", {}).get("properties", {})
    # Another field that happens to be called "provenance" keeps its own schema.
    return "schema_name" in schema.get("properties", {})


def serialize_tools_compact(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    """Search results in list_tools format, with the Provenance schema collapsed.

    The server's middleware inlines every `$ref` before results are built, so the
    block normally arrives inline; the `$ref` form is handled too, for a transform
    run without that middleware, and its now unused `$defs` entry is dropped.
    """
    results = serialize_tools_for_output_json(tools)
    for result in results:
        schema = result.get("outputSchema")
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        defs = schema.get("$defs", {})
        if _is_provenance(properties.get("provenance"), defs):
            properties["provenance"] = dict(PROVENANCE_STUB)
            if isinstance(defs, dict):
                # Keep the definition while another field still points at it.
                still_used = _refers_to(
                    [
                        {key: value for key, value in schema.items() if key != "$defs"},
                        {key: value for key, value in defs.items() if key != "Provenance"},
                    ],
                    PROVENANCE_REF,
                )
                if not still_used:
                    defs.pop("Provenance", None)
                if not defs:
                    schema.pop("$defs", None)
    return results
