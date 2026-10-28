"""search_tools ranking: exact-identifier boosts, and the optional hybrid mode's guards.

The semantic model itself is not run here (it is an optional extra and a 120 MB
download); tests/discovery_benchmark/phase2.py measures it. These tests cover what
runs without it: the boosts, the fusion arithmetic, the card text, the index guard
and the fallback to BM25 when hybrid is asked for and cannot load.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client

from maplestats_mcp import server
from maplestats_mcp.shared import search, semantic


@pytest.fixture(scope="module")
async def tools():
    listed = await server.mcp._list_tools()
    return [t for t in listed if t.name not in server.SEARCH_ALWAYS_VISIBLE]


async def _search(query: str) -> list[str]:
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_tools", {"query": query})
    assert result.structured_content is not None
    return [tool["name"] for tool in result.structured_content["result"]]


async def test_scored_index_ranks_like_fastmcps(tools, monkeypatch):
    # The index is ours since 2026-10, but with no boost it must still give the
    # order fastmcp's own BM25 gives with our tokenizer, which search_tools used
    # before, or the default search would change behind the benchmark's back.
    # fastmcp's index is private: once it moves, there is nothing to compare with.
    from fastmcp.server.transforms.search import base, bm25

    reference = getattr(bm25, "_BM25Index", None)
    text = getattr(base, "_extract_searchable_text", None)
    if reference is None or text is None or not hasattr(bm25, "_tokenize"):
        pytest.skip("fastmcp's private BM25 index moved; search_tools does not use it")
    monkeypatch.setattr(bm25, "_tokenize", search.tokenize)
    # scripts/build_site.py indexes fastmcp's searchable text; it must be ours too.
    assert [search.searchable_text(t) for t in tools] == [text(t) for t in tools]
    documents = [search.searchable_text(t) for t in tools]
    ours, theirs = search.ScoredBM25Index(), reference()
    ours.build(documents)
    theirs.build(documents)
    for query in ("taux de chômage Québec", "Calgary rent index", "wildfires", "zzz"):
        assert search.top_indices(ours.scores(query), 10) == theirs.query(query, 10)


@pytest.mark.parametrize(
    "query", ["14-10-0287-01", "Download table 14100287", "tableau 1410028701", "14-10-0287"]
)
async def test_a_table_number_lifts_the_statcan_table_tools(tools, query: str):
    boosts = search.identifier_boosts(query, tools)
    boosted = {tools[i].name for i in boosts}
    assert "wds_get_cube_metadata" in boosted
    assert "wds_get_full_table_download" in boosted
    # product_id is also a bank-account id; a table number is not one.
    assert not any(name.startswith("fcac_") for name in boosted)


async def test_a_din_is_not_a_table_number(tools):
    assert not search.identifier_boosts("DIN 02242903", tools)
    assert not search.identifier_boosts("prices in 2024 and 2025", tools)


async def test_a_vector_lifts_the_vector_and_series_tools(tools):
    boosted = {tools[i].name for i in search.identifier_boosts("v41690973", tools)}
    assert {"wds_get_data_from_vectors", "sdmx_get_vector_data"} <= boosted
    # Old Bank of Canada series are named like vectors (V39079).
    assert {"boc_get_series", "boc_get_observations"} <= boosted


async def test_a_tool_name_and_a_family_prefix(tools):
    boosts = search.identifier_boosts("boc_get_observations", tools)
    by_name = {tools[i].name: weight for i, (weight, _) in boosts.items()}
    assert by_name == {"boc_get_observations": search.EXACT_NAME_BOOST}
    family = {tools[i].name for i in search.identifier_boosts("cmhc_dt", tools)}
    assert family and all(name.startswith("cmhc_dt_") for name in family)


def test_a_boost_scales_with_the_best_score():
    assert search.apply_boosts([2.0, 4.0, 0.0], {2: (1.0, "x")}) == [2.0, 4.0, 4.0]
    # A query that is only an identifier scores nothing; the boost still surfaces it.
    assert search.apply_boosts([0.0, 0.0], {1: (1.0, "x")}) == [0.0, 1.0]
    assert search.top_indices([0.0, 1.0, 0.5], 5) == [1, 2]


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("14-10-0287-01 metadata", "wds_get_cube_metadata"),
        ("boc_get_observations", "boc_get_observations"),
        ("wds_get_cube_metadata", "wds_get_cube_metadata"),
        ("Download table 14100287 as a CSV", "wds_get_full_table_download"),
    ],
)
async def test_search_tools_puts_the_identified_tool_first(query: str, first: str):
    assert (await _search(query))[0] == first


def test_fusion_adds_reciprocal_ranks():
    fused = semantic.fuse([3.0, 0.0, 1.0], [1, 0])
    k = semantic.RRF_K
    assert fused == pytest.approx([1 / (k + 1) + 1 / (k + 2), 1 / (k + 1), 1 / (k + 2)])


def test_tool_card_keeps_summary_and_both_keyword_lines():
    description = (
        "Get the thing.\n\nUse for: details nobody embeds.\n"
        "Keywords: alpha, beta,\ngamma.\nMots-clés : un, deux.\n\nArgs: ignored"
    )
    assert semantic.tool_card("boc_get_thing", description) == (
        "boc get thing Get the thing. alpha, beta, gamma. un, deux."
    )


@pytest.mark.parametrize(("raw", "mode"), [("", "bm25"), ("HYBRID", "hybrid"), ("x", "bm25")])
def test_search_mode(monkeypatch, raw: str, mode: str):
    monkeypatch.setenv("MAPLE_SEARCH", raw)
    assert semantic.search_mode() == mode


def test_an_index_built_with_another_model_is_refused(tmp_path: Path):
    meta = semantic._meta() | {"model": "someone/else", "dimension": 768}
    (tmp_path / semantic.INDEX_FILE).write_text(json.dumps({"meta": meta, "tools": []}))
    with pytest.raises(semantic.SemanticUnavailable, match="dimension, model|model, dimension"):
        semantic.SemanticIndex.load(tmp_path)


async def test_hybrid_without_an_index_searches_by_bm25(monkeypatch, tmp_path: Path, tools):
    monkeypatch.setenv("MAPLE_SEMANTIC_DIR", str(tmp_path))
    hybrid = server.AnnotatedBM25SearchTransform(max_results=5, mode="hybrid")
    plain = server.AnnotatedBM25SearchTransform(max_results=5, mode="bm25")
    for query in ("taux de chômage Québec", "14-10-0287-01"):
        assert [t.name for t in await hybrid._search(tools, query)] == [
            t.name for t in await plain._search(tools, query)
        ]
    assert hybrid._semantic is None and hybrid._semantic_tried


def test_a_changed_or_new_tool_has_no_vector_until_the_rebuild():
    np = pytest.importorskip("numpy")

    class FakeEmbedder:
        def __init__(self) -> None:
            self.np = np

        def embed(self, text: str):
            return np.array([1.0, 0.0], dtype=np.float32)

    card = semantic.tool_card("a_tool", "Does a.")
    index = semantic.SemanticIndex(
        FakeEmbedder(),  # type: ignore[arg-type]
        ["a_tool", "b_tool"],
        [semantic.card_hash(card), "stale"],
        np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32),
    )
    rows = index.rows([("b_tool", "Does b."), ("new_tool", "New."), ("a_tool", "Does a.")])
    assert rows == [None, None, 0]
    # Only tools with a fresh vector are ranked semantically.
    assert index.ranking("anything", rows, depth=5) == [2]
