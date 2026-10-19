# ============================================================
# Discovery benchmark runner
# Author: Daniel Sanchez
# Purpose: Measure how well search_tools and plan_query route natural-language
#     questions (English and French) to the expected tools, offline and
#     in-process. No network, no embeddings: it only reads the live registry.
# Inputs:  tests/discovery_benchmark/queries.json; the live tool registry
# Outputs: results.json and results.md in the --out folder
# ============================================================
"""Run every benchmark query against search_tools and plan_query.

`search_tools` returns at most 5 tools (the server's `max_results`), so Recall@10
cannot be read from it. The runner therefore asks the real tool for its top 5
(the contract a client sees) and a second `BM25SearchTransform(max_results=10)`
over the same catalogue for ranks 6 to 10, and records whether the two agree on
the first five (`parity`). A parity mismatch means the second index no longer
mirrors the server, and the numbers beyond rank 5 cannot be trusted.

`plan_query` has no rank in the search sense, so its tools are flattened in the
order the plan shows them (topics best first, each topic's steps in order, then
the named places' steps, then the fallback steps) and scored with the same
Recall@k and MRR. Order-free measures (coverage of the expected tools anywhere
in the plan, topic hit, portal hit) are reported beside them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fastmcp
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.transforms.search import BM25SearchTransform
from mcp.shared.exceptions import MCPError

from maplestats_mcp.server import mcp

# %% 0. Setup

logger = logging.getLogger("discovery_benchmark")

HERE = Path(__file__).parent
QUERIES_PATH = HERE / "queries.json"
DEFAULT_OUT = HERE / "latest"

CATEGORIES = (
    "statcan",
    "boc",
    "cmhc",
    "ckan_federal",
    "ckan_provincial",
    "municipal",
    "multi_source",
    "ambiguity",
)
LANGUAGES = ("en", "fr")
# Tools server.py keeps visible, so BM25 never indexes or returns them.
ALWAYS_VISIBLE = frozenset({"search_tools", "plan_query"})
SEARCH_DEPTH = 10  # ranks scored for search_tools; the server itself returns 5
SERVER_TOP_N = 5
RANKS = (1, 5, 10)
# What Client.call_tool raises for an isError result or a protocol failure.
CALL_ERRORS = (ToolError, MCPError)

QUERY_KEYS = frozenset(
    {
        "id",
        "query",
        "lang",
        "category",
        "search_expected",
        "search_alternatives",
        "plan_topics",
        "plan_expected",
        "plan_alternatives",
        "plan_portals",
        "geography",
        "period",
        "ambiguous",
        "ambiguity_kind",
        "flag_terms",
        "live_expected",
        "reviewed",
        "notes",
    }
)


# %% 1. Read inputs


@dataclass(frozen=True)
class Query:
    """One benchmark question and what a correct answer looks like."""

    id: str
    query: str
    lang: str
    category: str
    search_expected: tuple[str, ...] = ()
    search_alternatives: tuple[str, ...] = ()
    plan_topics: tuple[str, ...] = ()
    plan_expected: tuple[str, ...] = ()
    plan_alternatives: tuple[str, ...] = ()
    plan_portals: tuple[str, ...] = ()
    geography: str = ""
    period: str = ""
    ambiguous: bool = False
    ambiguity_kind: str = ""
    flag_terms: tuple[str, ...] = ()
    live_expected: tuple[str, ...] = ()
    reviewed: bool = False
    notes: str = ""

    @property
    def search_accepted(self) -> frozenset[str]:
        return frozenset(self.search_expected) | frozenset(self.search_alternatives)

    @property
    def plan_accepted(self) -> frozenset[str]:
        return frozenset(self.plan_expected) | frozenset(self.plan_alternatives)


_TUPLE_FIELDS = (
    "search_expected",
    "search_alternatives",
    "plan_topics",
    "plan_expected",
    "plan_alternatives",
    "plan_portals",
    "flag_terms",
    "live_expected",
)


def load_queries(path: Path = QUERIES_PATH) -> list[Query]:
    """Read the fixtures; unknown keys raise so a typo cannot silently drop an expectation."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = []
    for row in raw:
        unknown = set(row) - QUERY_KEYS
        if unknown:
            raise ValueError(f"{row.get('id', '?')}: unknown fixture keys {sorted(unknown)}")
        values: dict[str, Any] = {
            key: (tuple(value) if key in _TUPLE_FIELDS else value) for key, value in row.items()
        }
        queries.append(Query(**values))
    return queries


def fixture_hash(path: Path = QUERIES_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass(frozen=True)
class Registry:
    """The live tool names, the module each belongs to, and the planner's vocabularies."""

    names: frozenset[str]
    sources: dict[str, str]
    topic_keys: frozenset[str]
    portal_keys: frozenset[str]


async def read_registry() -> Registry:
    from maplestats_mcp.modules.arcgis_hub.constants import PORTALS as ARCGIS_PORTALS
    from maplestats_mcp.modules.ckan.constants import PORTALS as CKAN_PORTALS
    from maplestats_mcp.modules.planner.topics import TOPICS
    from maplestats_mcp.modules.socrata.constants import PORTALS as SOCRATA_PORTALS

    tools = await mcp._list_tools()
    sources = {}
    for tool in tools:
        function = getattr(tool, "fn", None)
        module = getattr(function, "__module__", "") or ""
        # "maplestats_mcp.modules.statcan.cimt.tools" -> "statcan": a source is the agency.
        sources[tool.name] = module.removeprefix("maplestats_mcp.modules.").split(".")[0]
    return Registry(
        names=frozenset(sources),
        sources=sources,
        topic_keys=frozenset(topic.key for topic in TOPICS),
        portal_keys=frozenset(
            (*CKAN_PORTALS, *ARCGIS_PORTALS, *SOCRATA_PORTALS),
        ),
    )


# %% 2. Check inputs


def validate_queries(queries: Sequence[Query], registry: Registry) -> list[str]:
    """Every problem found in the fixtures, as readable lines (empty when sound)."""
    problems: list[str] = []
    seen: set[str] = set()
    for q in queries:
        where = q.id
        if q.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(q.id)
        if not re.fullmatch(rf"{re.escape(q.category)}-{q.lang}-\d{{2}}", q.id):
            problems.append(f"{where}: id must be <category>-<lang>-NN")
        if q.lang not in LANGUAGES:
            problems.append(f"{where}: lang {q.lang!r} is not one of {LANGUAGES}")
        if q.category not in CATEGORIES:
            problems.append(f"{where}: category {q.category!r} is not one of {CATEGORIES}")
        if not q.query.strip():
            problems.append(f"{where}: empty query")
        if not (q.search_expected or q.plan_expected):
            problems.append(f"{where}: needs search_expected or plan_expected")
        if q.search_alternatives and not q.search_expected:
            problems.append(f"{where}: search_alternatives without search_expected")
        if q.plan_alternatives and not q.plan_expected:
            problems.append(f"{where}: plan_alternatives without plan_expected")
        for name in (*q.search_expected, *q.search_alternatives):
            if name in ALWAYS_VISIBLE:
                problems.append(f"{where}: {name} is never returned by search_tools")
        for name in (
            *q.search_expected,
            *q.search_alternatives,
            *q.plan_expected,
            *q.plan_alternatives,
        ):
            if name not in registry.names:
                problems.append(f"{where}: tool {name!r} is not in the registry")
        for topic in q.plan_topics:
            if topic not in registry.topic_keys:
                problems.append(f"{where}: planner topic {topic!r} does not exist")
        for portal in q.plan_portals:
            if portal not in registry.portal_keys:
                problems.append(f"{where}: portal {portal!r} is not a CKAN/ArcGIS/Socrata key")
        if q.ambiguous and not q.ambiguity_kind:
            problems.append(f"{where}: ambiguous without ambiguity_kind")
        if (q.ambiguity_kind or q.flag_terms) and not q.ambiguous:
            problems.append(f"{where}: ambiguity_kind/flag_terms on a query not marked ambiguous")
        if q.category == "ambiguity" and not q.ambiguous:
            problems.append(f"{where}: ambiguity category must be marked ambiguous")
    return problems


# %% 3. Run the queries


@dataclass
class SearchOutcome:
    top10: list[str]
    server_top5: list[str]
    rank: int | None  # first accepted tool, 1-based, within the top 10
    strict_rank: int | None  # first expected tool (alternatives excluded)
    source_ok: bool  # top-1 tool belongs to the source of an accepted tool
    coverage_at_5: float  # share of the accepted tools found in the top 5
    parity_ok: bool
    abstained: bool  # search_tools returned nothing
    error: str | None
    latency_ms: float


@dataclass
class PlanOutcome:
    tools: list[str]  # flattened, in plan order, without repeats
    topics: list[str]
    out_of_scope: bool
    rank: int | None
    strict_rank: int | None
    routed_rank: int | None  # first accepted tool among the topic and place steps only
    coverage: float  # share of plan_expected found anywhere in the plan
    topic_hit: bool | None  # any expected topic returned; None when none expected
    topic_top1: bool | None
    portal_hit: bool | None  # every expected portal named in a step; None when none expected
    flag_surfaced: bool | None  # a flag term appears in caveats/purposes; None when none expected
    source_ok: bool
    abstained: bool  # out of scope, or only the generic fallback steps
    error: str | None
    latency_ms: float


@dataclass
class QueryResult:
    id: str
    category: str
    lang: str
    query: str
    ambiguous: bool
    search: SearchOutcome | None = None
    plan: PlanOutcome | None = None


def first_rank(names: Sequence[str], wanted: Iterable[str]) -> int | None:
    wanted = frozenset(wanted)
    for position, name in enumerate(names, start=1):
        if name in wanted:
            return position
    return None


def fold(text: str) -> str:
    """Lower-case and strip accents, so "préférentiel" meets "preferentiel"."""
    text = text.casefold().replace("œ", "oe").replace("’", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def mentions(term: str, text: str) -> bool:
    """Whole-word match of a term in folded text; a trailing * lets the last word run on.

    A bare substring test would take "lim" in "limits" for the Low Income Measure.
    """
    body = re.escape(fold(term.rstrip("*")))
    tail = "" if term.endswith("*") else "(?![a-z0-9])"
    return re.search(rf"(?<![a-z0-9]){body}{tail}", text) is not None


def flatten_plan(plan: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Tool names in plan order, the portal keys the steps name, and the tools routed by a match.

    "Routed" leaves out the generic fallback steps, which every unmatched question gets: a
    StatCan or CKAN search tool found only there was not chosen for the question.
    """
    routed_steps: list[dict[str, Any]] = []
    for topic in plan.get("topics", []):
        routed_steps.extend(topic.get("steps", []))
    for place in plan.get("places", []):
        routed_steps.extend(place.get("steps", []))
    steps = [*routed_steps, *plan.get("fallback_steps", [])]
    tools = list(dict.fromkeys(step["tool"] for step in steps))
    routed = list(dict.fromkeys(step["tool"] for step in routed_steps))
    portals = [
        key for step in steps for key in re.findall(r"portal='([a-z_]+)'", step.get("purpose", ""))
    ]
    return tools, portals, routed


def plan_text(plan: dict[str, Any]) -> str:
    """Caveats, purposes and guidance: what a reader sees of the planner's reasoning."""
    parts = [*plan.get("guidance", [])]
    for topic in plan.get("topics", []):
        parts.extend(topic.get("caveats", []))
        parts.extend(step.get("purpose", "") for step in topic.get("steps", []))
    for place in plan.get("places", []):
        parts.extend(step.get("purpose", "") for step in place.get("steps", []))
    return fold(" ".join(parts))


def _source_ok(top1: str | None, accepted: frozenset[str], sources: dict[str, str]) -> bool:
    if top1 is None:
        return False
    return sources.get(top1) in {sources.get(name) for name in accepted}


async def run_search(
    client: Client, ranker: BM25SearchTransform, tools: list[Any], q: Query, registry: Registry
) -> SearchOutcome:
    accepted = q.search_accepted
    started = time.perf_counter()
    server_top: list[str] = []
    error: str | None = None
    try:
        result = await client.call_tool("search_tools", {"query": q.query})
        found = (result.structured_content or {}).get("result", [])
        server_top = [item["name"] for item in found]
    except CALL_ERRORS as exc:  # a failed tool call is a measured outcome, not a crash
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000

    # Ranks 6 to 10 come from the second index; ranks 1 to 5 must agree with the server's.
    top10 = [tool.name for tool in await ranker._search(tools, q.query)]
    parity_ok = error is not None or top10[:SERVER_TOP_N] == server_top
    covered = len(accepted & set(top10[:SERVER_TOP_N]))
    return SearchOutcome(
        top10=top10,
        server_top5=server_top,
        rank=first_rank(top10, accepted),
        strict_rank=first_rank(top10, q.search_expected),
        source_ok=_source_ok(top10[0] if top10 else None, accepted, registry.sources),
        coverage_at_5=covered / len(accepted) if accepted else 0.0,
        parity_ok=parity_ok,
        abstained=error is None and not server_top,
        error=error,
        latency_ms=latency_ms,
    )


async def run_plan(client: Client, q: Query, registry: Registry) -> PlanOutcome:
    accepted = q.plan_accepted
    started = time.perf_counter()
    plan: dict[str, Any] = {}
    error: str | None = None
    try:
        result = await client.call_tool("plan_query", {"question": q.query, "lang": q.lang})
        plan = result.structured_content or {}
    except CALL_ERRORS as exc:  # a failed tool call is a measured outcome, not a crash
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1000

    tools, portals, routed = flatten_plan(plan)
    topics = [topic["topic"] for topic in plan.get("topics", [])]
    out_of_scope = plan.get("out_of_scope") is not None
    expected = q.plan_expected
    text = plan_text(plan)
    return PlanOutcome(
        tools=tools,
        topics=topics,
        out_of_scope=out_of_scope,
        rank=first_rank(tools, accepted),
        strict_rank=first_rank(tools, expected),
        routed_rank=first_rank(routed, accepted),
        coverage=(sum(name in tools for name in expected) / len(expected)) if expected else 0.0,
        topic_hit=any(t in topics for t in q.plan_topics) if q.plan_topics else None,
        topic_top1=(bool(topics) and topics[0] in q.plan_topics) if q.plan_topics else None,
        portal_hit=all(p in portals for p in q.plan_portals) if q.plan_portals else None,
        flag_surfaced=any(mentions(t, text) for t in q.flag_terms) if q.flag_terms else None,
        source_ok=_source_ok(tools[0] if tools else None, accepted, registry.sources),
        abstained=error is None and (out_of_scope or not (topics or plan.get("places"))),
        error=error,
        latency_ms=latency_ms,
    )


async def run_all(queries: Sequence[Query], registry: Registry) -> tuple[list[QueryResult], dict]:
    """Ask every query of both systems over one client session."""
    tools = [tool for tool in await mcp._list_tools() if tool.name not in ALWAYS_VISIBLE]
    ranker = BM25SearchTransform(max_results=SEARCH_DEPTH)
    results: list[QueryResult] = []
    async with Client(mcp) as client:
        # The first search builds the BM25 index of the whole catalogue; time it apart.
        started = time.perf_counter()
        await client.call_tool("search_tools", {"query": "warm up"})
        await ranker._search(tools, "warm up")
        await client.call_tool("plan_query", {"question": "warm up", "lang": "en"})
        warmup_ms = (time.perf_counter() - started) * 1000
        for q in queries:
            row = QueryResult(q.id, q.category, q.lang, q.query, q.ambiguous)
            if q.search_expected:
                row.search = await run_search(client, ranker, tools, q, registry)
            if q.plan_expected:
                row.plan = await run_plan(client, q, registry)
            results.append(row)
    meta = {"tools_indexed": len(tools), "warmup_ms": round(warmup_ms, 1)}
    return results, meta


# %% 4. Calculate estimates


def _rate(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: Sequence[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1)]


def _recall(ranks: Sequence[int | None], depth: int) -> float | None:
    return _rate([rank is not None and rank <= depth for rank in ranks])


def _mrr(ranks: Sequence[int | None]) -> float | None:
    return _mean([1 / rank if rank else 0.0 for rank in ranks])


def summarise_search(rows: Sequence[QueryResult]) -> dict[str, Any]:
    outcomes = [(r, r.search) for r in rows if r.search is not None]
    searches = [s for _, s in outcomes]
    ranks = [s.rank for s in searches]
    strict = [s.strict_rank for s in searches]
    ambiguous = [s for r, s in outcomes if r.ambiguous]
    return {
        "n": len(searches),
        **{f"recall_at_{k}": _recall(ranks, k) for k in RANKS},
        "mrr": _mrr(ranks),
        "strict_recall_at_5": _recall(strict, 5),
        "strict_mrr": _mrr(strict),
        "source_correct_at_1": _rate([s.source_ok for s in searches]),
        "error_rate": _rate([s.error is not None for s in searches]),
        "abstention_rate": _rate([s.abstained for s in searches]),
        "ambiguous_n": len(ambiguous),
        "accepted_coverage_at_5": _mean([s.coverage_at_5 for s in ambiguous]),
        "latency_ms_p50": _percentile([s.latency_ms for s in searches], 0.5),
        "latency_ms_p95": _percentile([s.latency_ms for s in searches], 0.95),
    }


def summarise_plan(rows: Sequence[QueryResult]) -> dict[str, Any]:
    outcomes = [(r, r.plan) for r in rows if r.plan is not None]
    plans = [p for _, p in outcomes]
    ranks = [p.rank for p in plans]
    strict = [p.strict_rank for p in plans]
    return {
        "n": len(plans),
        **{f"recall_at_{k}": _recall(ranks, k) for k in RANKS},
        "mrr": _mrr(ranks),
        "strict_recall_at_5": _recall(strict, 5),
        "strict_mrr": _mrr(strict),
        "recall_anywhere": _rate([rank is not None for rank in ranks]),
        "recall_routed": _rate([p.routed_rank is not None for p in plans]),
        "expected_coverage": _mean([p.coverage for p in plans]),
        "topic_hit": _rate([p.topic_hit for p in plans if p.topic_hit is not None]),
        "topic_top1": _rate([p.topic_top1 for p in plans if p.topic_top1 is not None]),
        "portal_hit": _rate([p.portal_hit for p in plans if p.portal_hit is not None]),
        "flag_surfaced": _rate([p.flag_surfaced for p in plans if p.flag_surfaced is not None]),
        "source_correct_at_1": _rate([p.source_ok for p in plans]),
        "error_rate": _rate([p.error is not None for p in plans]),
        "abstention_rate": _rate([p.abstained for p in plans]),
        "latency_ms_p50": _percentile([p.latency_ms for p in plans], 0.5),
        "latency_ms_p95": _percentile([p.latency_ms for p in plans], 0.95),
    }


def _grouped(
    rows: Sequence[QueryResult],
    summarise: Callable[[Sequence[QueryResult]], dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    def by(key: Callable[[QueryResult], str], order: Sequence[str]) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[QueryResult]] = defaultdict(list)
        for row in rows:
            groups[key(row)].append(row)
        return {name: summarise(groups[name]) for name in order if name in groups}

    combined = [f"{c}/{lang}" for c in CATEGORIES for lang in LANGUAGES]
    return {
        "overall": {"all": summarise(rows)},
        "by_category": by(lambda r: r.category, CATEGORIES),
        "by_lang": by(lambda r: r.lang, LANGUAGES),
        "by_category_lang": by(lambda r: f"{r.category}/{r.lang}", combined),
    }


def build_report(
    rows: list[QueryResult], queries: Sequence[Query], registry: Registry, meta: dict
) -> dict[str, Any]:
    mismatches = [r.id for r in rows if r.search is not None and not r.search.parity_ok]
    return {
        "meta": {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "fastmcp": fastmcp.__version__,
            "fixture_hash": fixture_hash(),
            "queries": len(queries),
            "reviewed": sum(q.reviewed for q in queries),
            "registry_tools": len(registry.names),
            **meta,
        },
        "parity": {"mismatched_ids": mismatches},
        "search": _grouped(rows, summarise_search),
        "plan": _grouped(rows, summarise_plan),
        "queries": [asdict(row) for row in rows],
    }


# %% 5. Write outputs


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _table(
    title: str, groups: dict[str, dict[str, Any]], columns: Sequence[tuple[str, str, int]]
) -> list[str]:
    lines = [
        f"| {title} | " + " | ".join(label for label, _, _ in columns) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    for name, metrics in groups.items():
        cells = [_fmt(metrics.get(key), digits) for _, key, digits in columns]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


SEARCH_COLUMNS = (
    ("n", "n", 0),
    ("R@1", "recall_at_1", 2),
    ("R@5", "recall_at_5", 2),
    ("R@10", "recall_at_10", 2),
    ("MRR", "mrr", 2),
    ("strict R@5", "strict_recall_at_5", 2),
    ("source@1", "source_correct_at_1", 2),
    ("error", "error_rate", 2),
    ("abstain", "abstention_rate", 2),
    ("p50 ms", "latency_ms_p50", 1),
    ("p95 ms", "latency_ms_p95", 1),
)
PLAN_COLUMNS = (
    ("n", "n", 0),
    ("R@1", "recall_at_1", 2),
    ("R@5", "recall_at_5", 2),
    ("R@10", "recall_at_10", 2),
    ("MRR", "mrr", 2),
    ("anywhere", "recall_anywhere", 2),
    ("routed", "recall_routed", 2),
    ("coverage", "expected_coverage", 2),
    ("topic", "topic_hit", 2),
    ("portal", "portal_hit", 2),
    ("source@1", "source_correct_at_1", 2),
    ("error", "error_rate", 2),
    ("abstain", "abstention_rate", 2),
    ("p50 ms", "latency_ms_p50", 1),
    ("p95 ms", "latency_ms_p95", 1),
)


def _section(
    report: dict[str, Any], system: str, columns: Sequence[tuple[str, str, int]]
) -> list[str]:
    data = report[system]
    lines = []
    for title, key in (
        ("Overall", "overall"),
        ("Category", "by_category"),
        ("Language", "by_lang"),
    ):
        lines += _table(title, data[key], columns) + [""]
    return lines


def render_markdown(report: dict[str, Any], queries: Sequence[Query]) -> str:
    by_id = {q.id: q for q in queries}
    meta = report["meta"]
    mismatched = report["parity"]["mismatched_ids"]
    search_ambiguity = report["search"]["by_category"].get("ambiguity", {})
    plan_ambiguity = report["plan"]["by_category"].get("ambiguity", {})
    summary = (
        f"{meta['queries']} queries ({meta['reviewed']} reviewed), fixture hash "
        f"`{meta['fixture_hash']}`, fastmcp {meta['fastmcp']}, {meta['tools_indexed']} tools "
        f"indexed, index warm-up {meta['warmup_ms']} ms. Generated {meta['generated']}."
    )
    parity = "Parity of the 10-deep index with the server's top 5: " + (
        "all queries agree." if not mismatched else f"MISMATCH on {mismatched}."
    )
    search_note = (
        "Ambiguity queries: share of the accepted tools found in the top 5 = "
        f"{_fmt(search_ambiguity.get('accepted_coverage_at_5'))}."
    )
    plan_note = (
        "Ambiguity queries: share whose plan text names one of the alternatives (flag terms) = "
        f"{_fmt(plan_ambiguity.get('flag_surfaced'))}."
    )
    lines = [
        "# Discovery benchmark results",
        "",
        summary,
        "",
        parity,
        "",
        "## search_tools",
        "",
        *_section(report, "search", SEARCH_COLUMNS),
        search_note,
        "",
        "## plan_query",
        "",
        *_section(report, "plan", PLAN_COLUMNS),
        plan_note,
        "",
        "## search_tools misses (no accepted tool in the top 5)",
        "",
        "| id | query | expected | top 5 returned |",
        "|---|---|---|---|",
    ]
    for row in report["queries"]:
        search = row["search"]
        if search is None or (search["rank"] is not None and search["rank"] <= SERVER_TOP_N):
            continue
        q = by_id[row["id"]]
        rank = "absent" if search["rank"] is None else f"rank {search['rank']}"
        lines.append(
            f"| {q.id} | {q.query} | {', '.join(q.search_expected)} ({rank}) "
            f"| {', '.join(search['top10'][:SERVER_TOP_N]) or '(none)'} |"
        )
    lines += [
        "",
        "## plan_query misses (no accepted tool anywhere in the plan)",
        "",
        "| id | query | expected | topics returned | first tools in plan |",
        "|---|---|---|---|---|",
    ]
    for row in report["queries"]:
        plan = row["plan"]
        if plan is None or plan["rank"] is not None:
            continue
        q = by_id[row["id"]]
        scope = " (out of scope)" if plan["out_of_scope"] else ""
        lines.append(
            f"| {q.id} | {q.query} | {', '.join(q.plan_expected)} "
            f"| {', '.join(plan['topics']) or '(none)'}{scope} "
            f"| {', '.join(plan['tools'][:5]) or '(none)'} |"
        )
    return "\n".join(lines) + "\n"


def dump_report(report: dict[str, Any]) -> str:
    """JSON with the summaries indented and one line per query, so a baseline diff stays readable."""
    head = {key: value for key, value in report.items() if key != "queries"}
    rows = [json.dumps(row, ensure_ascii=False) for row in report["queries"]]
    summary = json.dumps(head, indent=2, ensure_ascii=False)
    # Re-open the summary's closing brace to append the queries, one per line.
    return summary[:-2] + ',\n  "queries": [\n    ' + ",\n    ".join(rows) + "\n  ]\n}\n"


def write_outputs(report: dict[str, Any], queries: Sequence[Query], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(dump_report(report), encoding="utf-8")
    (out_dir / "results.md").write_text(render_markdown(report, queries), encoding="utf-8")


@dataclass
class Benchmark:
    """A finished run: the report, the fixtures it used, and any fixture problems found."""

    report: dict[str, Any]
    queries: list[Query]
    registry: Registry
    problems: list[str]


def run_benchmark(strict: bool = True) -> Benchmark:
    """Load, validate and run the fixtures.

    Strict (the command line) raises when a fixture names a tool that does not exist; the
    tests ask for the problems instead, so one bad fixture is one clear failure.
    """

    async def go() -> Benchmark:
        queries = load_queries()
        registry = await read_registry()
        problems = validate_queries(queries, registry)
        if problems and strict:
            raise ValueError("invalid fixtures:\n" + "\n".join(problems))
        rows, meta = await run_all(queries, registry)
        return Benchmark(build_report(rows, queries, registry, meta), queries, registry, problems)

    return asyncio.run(go())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for results.*")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    benchmark = run_benchmark()
    write_outputs(benchmark.report, benchmark.queries, args.out)
    logger.info("wrote %s and %s", args.out / "results.json", args.out / "results.md")
    return 0
