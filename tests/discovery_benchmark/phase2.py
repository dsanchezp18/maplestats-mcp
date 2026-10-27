# ============================================================
# Discovery benchmark, Phase 2: rankers compared offline
# Author: Daniel Sanchez
# Purpose: Score candidate search_tools rankers (BM25, BM25 with identifier
#     boosts, multilingual embeddings, reciprocal-rank fusion) on the reviewed
#     benchmark questions and on the identifier probes, with their costs.
# Inputs:  queries.json, identifiers.json, the tool registry; for embeddings the
#     semantic index folder (MAPLE_SEMANTIC_DIR) or fastembed models
# Outputs: phase2.json and phase2.md in the --out folder
# ============================================================
"""Compare search_tools rankers on the same questions, in one process.

    uv run python -m tests.discovery_benchmark.phase2
    uv run --extra semantic python -m tests.discovery_benchmark.phase2 --semantic
    uv run --extra semantic --with fastembed python -m tests.discovery_benchmark.phase2 \
        --semantic --fastembed google/embeddinggemma-300m

Every ranker sees the same catalogue snapshot and the same 129 questions, so the
rows are comparable with each other; `bm25` must equal the runner's baseline (it is
the server's index without boosts). The identifier probes (identifiers.json) were
written by the session that wrote the boosts, before it ran them, and nobody else
has reviewed them: they show what an identifier query does, not a reviewed score.
Rankers that need a model are skipped unless asked for. Memory is the process's
resident size before and after loading a model; on another machine it differs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fastmcp.server.transforms.search.base import _extract_searchable_text

from maplestats_mcp.catalogue import read_catalogue
from maplestats_mcp.server import mcp
from maplestats_mcp.shared import search, semantic
from tests.discovery_benchmark import runner

logger = logging.getLogger("discovery_benchmark.phase2")

PROBES_PATH = runner.HERE / "identifiers.json"
DEPTH = runner.SEARCH_DEPTH
# Prefixes each model was trained with (query, passage); see each model card.
FASTEMBED_PREFIXES = {
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
    "google/embeddinggemma-300m": ("task: search result | query: ", "title: none | text: "),
}

Ranker = Callable[[str], list[int]]


def rss_mb() -> float:
    """Resident memory of this process (Linux); 0 where /proc is absent."""
    try:
        status = Path("/proc/self/status").read_text()
    except OSError:
        return 0.0
    return int(status.split("VmRSS:")[1].split()[0]) / 1024


# %% 1. Rankers


class Embeddings:
    """Tool card vectors and a query encoder, from the semantic index or a fastembed model."""

    def __init__(self, label: str, embed_query: Callable[[str], Any], vectors: Any, np: Any):
        self.label = label
        self.embed_query = embed_query
        self.vectors = vectors
        self.np = np
        self.cost: dict[str, float] = {}

    def ranking(self, query: str, depth: int = semantic.FUSION_DEPTH) -> list[int]:
        similarity = self.vectors @ self.embed_query(query)
        return [int(i) for i in self.np.argsort(-similarity, kind="stable")[:depth]]


def load_semantic_index(folder: Path, tools: Sequence[Any]) -> Embeddings:
    before = rss_mb()
    started = time.perf_counter()
    index = semantic.SemanticIndex.load(folder)
    rows = index.rows([(t.name, t.description or "") for t in tools])
    missing = [t.name for t, row in zip(tools, rows, strict=True) if row is None]
    if missing:
        raise SystemExit(
            f"the semantic index lacks {len(missing)} tools; rebuild it: {missing[:5]}"
        )
    vectors = index._vectors[[row for row in rows if row is not None]]
    embeddings = Embeddings(
        "e5-small int8 (semantic extra)",
        lambda q: index.embedder.embed(semantic.QUERY_PREFIX + q),
        vectors,
        index.np,
    )
    embeddings.cost = {
        "load_s": time.perf_counter() - started,
        "rss_before_mb": before,
        "rss_after_mb": rss_mb(),
        "index_bytes": (folder / semantic.INDEX_FILE).stat().st_size,
        "model_bytes": sum((folder / name).stat().st_size for name in semantic.FILES),
    }
    return embeddings


def load_fastembed(model: str, tools: Sequence[Any]) -> Embeddings:
    """A fastembed model, for exploration only: the cards are embedded here, not prebuilt."""
    import numpy as np  # pyright: ignore[reportMissingImports]
    from fastembed import TextEmbedding  # pyright: ignore[reportMissingImports]

    query_prefix, passage_prefix = FASTEMBED_PREFIXES.get(model, ("", ""))
    if model == semantic.MODEL:
        # Not in fastembed's list: the authors' fp32 ONNX file, for comparison with int8.
        from fastembed.common.model_description import (  # pyright: ignore[reportMissingImports]
            ModelSource,
            PoolingType,
        )

        TextEmbedding.add_custom_model(
            model=model,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=model),
            dim=semantic.DIMENSION,
            model_file="onnx/model.onnx",
        )
    before = rss_mb()
    started = time.perf_counter()
    encoder = TextEmbedding(model, threads=1)
    load_s = time.perf_counter() - started
    loaded = rss_mb()
    started = time.perf_counter()
    cards = [passage_prefix + semantic.tool_card(t.name, t.description or "") for t in tools]
    vectors = np.array(list(encoder.embed(cards, batch_size=16)), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    def embed_query(q: str) -> Any:
        vector = np.array(next(iter(encoder.embed([query_prefix + q]))), dtype=np.float32)
        return vector / np.linalg.norm(vector)

    embeddings = Embeddings(f"{model} (fastembed)", embed_query, vectors, np)
    embeddings.cost = {
        "load_s": load_s,
        "build_s": time.perf_counter() - started,
        "rss_before_mb": before,
        "rss_after_mb": loaded,
        "rss_after_build_mb": rss_mb(),
    }
    return embeddings


def bm25_ranker(index: search.ScoredBM25Index, tools: Sequence[Any], boosts: bool) -> Ranker:
    def rank(query: str) -> list[int]:
        scores = index.scores(query)
        if boosts:
            scores = search.apply_boosts(scores, search.identifier_boosts(query, tools))
        return search.top_indices(scores, DEPTH)

    return rank


def semantic_ranker(embeddings: Embeddings) -> Ranker:
    return lambda query: embeddings.ranking(query, DEPTH)


def fused_ranker(
    index: search.ScoredBM25Index,
    tools: Sequence[Any],
    embeddings: Embeddings,
    boosts: bool,
    semantic_weight: float = 1.0,
) -> Ranker:
    def rank(query: str) -> list[int]:
        scores = index.scores(query)
        fused = semantic.fuse(scores, [])
        for position, i in enumerate(embeddings.ranking(query), start=1):
            fused[i] += semantic_weight / (semantic.RRF_K + position)
        if boosts:
            fused = search.apply_boosts(fused, search.identifier_boosts(query, tools))
        return search.top_indices(fused, DEPTH)

    return rank


# %% 2. Score


def score_benchmark(
    ranker: Ranker,
    tools: Sequence[Any],
    queries: Sequence[runner.Query],
    registry: runner.Registry,
) -> tuple[dict[str, Any], list[float], dict[str, list[str]]]:
    rows: list[runner.QueryResult] = []
    latencies: list[float] = []
    tops: dict[str, list[str]] = {}
    for q in queries:
        started = time.perf_counter()
        top10 = [tools[i].name for i in ranker(q.query)]
        latencies.append((time.perf_counter() - started) * 1000)
        tops[q.id] = top10
        accepted = q.search_accepted
        row = runner.QueryResult(q.id, q.category, q.lang, q.query, q.ambiguous)
        row.search = runner.SearchOutcome(
            top10=top10,
            server_top5=top10[: runner.SERVER_TOP_N],
            rank=runner.first_rank(top10, accepted),
            strict_rank=runner.first_rank(top10, q.search_expected),
            source_ok=runner._source_ok(top10[0] if top10 else None, accepted, registry.sources),
            coverage_at_5=len(accepted & set(top10[: runner.SERVER_TOP_N])) / len(accepted),
            parity_ok=True,
            abstained=not top10,
            error=None,
            latency_ms=latencies[-1],
        )
        rows.append(row)
    return runner._grouped(rows, runner.summarise_search), latencies, tops


def score_probes(
    ranker: Ranker, tools: Sequence[Any], probes: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    by_kind: dict[str, list[int | None]] = {}
    ranks: dict[str, int | None] = {}
    for probe in probes:
        top10 = [tools[i].name for i in ranker(probe["query"])]
        if "accepted_prefix" in probe:
            accepted = [name for name in top10 if name.startswith(probe["accepted_prefix"])]
        else:
            accepted = probe["accepted"]
        rank = runner.first_rank(top10, accepted)
        ranks[probe["id"]] = rank
        by_kind.setdefault(probe["kind"], []).append(rank)
        by_kind.setdefault("all", []).append(rank)
    summary = {
        kind: {
            "n": len(values),
            "recall_at_1": runner._recall(values, 1),
            "recall_at_5": runner._recall(values, 5),
            "mrr": runner._mrr(values),
        }
        for kind, values in by_kind.items()
    }
    return {"summary": summary, "ranks": ranks}


# %% 3. Report


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render(report: dict[str, Any]) -> str:
    lines = ["# Phase 2 ranker comparison", "", report["meta_line"], ""]
    groups = [("all", "overall"), ("en", "by_lang"), ("fr", "by_lang")]
    groups += [(c, "by_category") for c in runner.CATEGORIES]
    header = "| ranker | " + " | ".join(name for name, _ in groups) + " |"
    for metric, label in (
        ("recall_at_1", "R@1"),
        ("recall_at_5", "R@5"),
        ("recall_at_10", "R@10"),
        ("mrr", "MRR"),
    ):
        lines += [f"## {label}, 129 reviewed questions", "", header]
        lines.append("|---|" + "---:|" * len(groups))
        for name, result in report["rankers"].items():
            cells = [_fmt(result["benchmark"][group][key][metric]) for key, group in groups]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    kinds = sorted({k for r in report["rankers"].values() for k in r["probes"]["summary"]})
    lines += ["## Identifier probes (unreviewed), R@1 / R@5", ""]
    lines.append("| ranker | " + " | ".join(kinds) + " |")
    lines.append("|---|" + "---:|" * len(kinds))
    for name, result in report["rankers"].items():
        summary = result["probes"]["summary"]
        cells = [
            f"{_fmt(summary[k]['recall_at_1'])} / {_fmt(summary[k]['recall_at_5'])}" for k in kinds
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Cost", "", "| ranker | query p50 ms | query p95 ms |", "|---|---:|---:|"]
    for name, result in report["rankers"].items():
        lines.append(f"| {name} | {result['p50_ms']:.1f} | {result['p95_ms']:.1f} |")
    lines += ["", "| model | measurements |", "|---|---|"]
    for label, cost in report["models"].items():
        detail = ", ".join(f"{key} {value:.1f}" for key, value in cost.items())
        lines.append(f"| {label} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=runner.DEFAULT_OUT)
    parser.add_argument("--semantic", action="store_true", help="add the semantic-extra rankers")
    parser.add_argument("--semantic-dir", type=Path, default=None)
    parser.add_argument("--fastembed", action="append", default=[], help="a fastembed model id")
    parser.add_argument(
        "--all-registered",
        action="store_true",
        help="rank every registered tool, not only those in tool_catalogue.json",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def setup() -> tuple[list[Any], runner.Registry]:
        tools = [t for t in await mcp._list_tools() if t.name not in runner.ALWAYS_VISIBLE]
        if not args.all_registered:
            # A module being written in the same tree (not yet in the catalogue)
            # would otherwise move every row; the comparison is of rankers.
            listed = {
                tool["name"]
                for entry in (read_catalogue() or {}).values()
                for tool in entry["tools"]
            }
            tools = [t for t in tools if t.name in listed]
        return tools, await runner.read_registry()

    tools, registry = asyncio.run(setup())
    queries = runner.load_queries()
    probes = json.loads(PROBES_PATH.read_text(encoding="utf-8"))
    index = search.ScoredBM25Index()
    index.build([_extract_searchable_text(t) for t in tools])

    rankers: dict[str, Ranker] = {
        "bm25": bm25_ranker(index, tools, boosts=False),
        "bm25 + ids": bm25_ranker(index, tools, boosts=True),
    }
    models: dict[str, dict[str, float]] = {}
    embeddings: list[Embeddings] = []
    if args.semantic:
        embeddings.append(load_semantic_index(args.semantic_dir or semantic.index_dir(), tools))
    embeddings += [load_fastembed(model, tools) for model in args.fastembed]
    for emb in embeddings:
        models[emb.label] = emb.cost
        rankers[f"{emb.label}: semantic"] = semantic_ranker(emb)
        rankers[f"{emb.label}: rrf"] = fused_ranker(index, tools, emb, boosts=False)
        rankers[f"{emb.label}: rrf + ids"] = fused_ranker(index, tools, emb, boosts=True)
        rankers[f"{emb.label}: rrf (semantic x0.5) + ids"] = fused_ranker(
            index, tools, emb, boosts=True, semantic_weight=0.5
        )

    report: dict[str, Any] = {
        "meta_line": (
            f"{len(queries)} questions (fixtures `{runner.fixture_hash()}`), {len(probes)} "
            f"identifier probes, {len(tools)} tools."
        ),
        "rankers": {},
        "models": models,
    }
    for name, ranker in rankers.items():
        benchmark, latencies, tops = score_benchmark(ranker, tools, queries, registry)
        report["rankers"][name] = {
            "benchmark": benchmark,
            "probes": score_probes(ranker, tools, probes),
            "p50_ms": runner._percentile(latencies, 0.5) or 0.0,
            "p95_ms": runner._percentile(latencies, 0.95) or 0.0,
            "top10": tops,
        }
        overall = benchmark["overall"]["all"]
        logger.info(
            "%s: R@1 %.2f R@5 %.2f R@10 %.2f MRR %.2f",
            name,
            overall["recall_at_1"],
            overall["recall_at_5"],
            overall["recall_at_10"],
            overall["mrr"],
        )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "phase2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.out / "phase2.md").write_text(render(report), encoding="utf-8")
    logger.info("wrote %s", args.out / "phase2.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
