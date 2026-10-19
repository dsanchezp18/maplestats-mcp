"""The offline discovery benchmark: sound fixtures and quality above a regression floor.

tests/discovery_benchmark/queries.json holds natural-language questions in English and
French with the tools a good answer names. This file checks that every expected tool is
in the live registry, runs the questions through search_tools and plan_query in-process,
and fails if a headline metric falls below a floor. The floors sit a little below the
baseline recorded on 2026-10-19 (tests/discovery_benchmark/baseline.md), so a docstring
edit that loses a few queries fails here while ordinary churn does not. Raise a floor
when a change improves the numbers on purpose; never lower one to make a change pass
without recording why in the baseline report.

The run is deterministic and needs no network: search_tools and plan_query read the
registry and bundled maps only. Latency is reported, never asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.discovery_benchmark import runner

# Measured 2026-10-19, 129 queries. Overall floors sit about 0.04 below the baseline, language
# floors 0.05 below, and category floors 0.10 below: a category holds 5 to 25 queries, so
# one flipped query (0.04 to 0.20) is tolerated and two are not.
SEARCH_FLOORS: dict[tuple[str, str], dict[str, float]] = {
    ("overall", "all"): {
        "recall_at_1": 0.53,
        "recall_at_5": 0.83,
        "recall_at_10": 0.88,
        "mrr": 0.66,
    },
    ("by_lang", "en"): {"recall_at_5": 0.84},
    ("by_lang", "fr"): {"recall_at_5": 0.78},
    ("by_category", "statcan"): {"recall_at_5": 0.86},
    ("by_category", "boc"): {"recall_at_5": 0.73},
    ("by_category", "cmhc"): {"recall_at_5": 0.90},
    ("by_category", "ckan_federal"): {"recall_at_5": 0.65},
    ("by_category", "ckan_provincial"): {"recall_at_5": 0.65},
    ("by_category", "municipal"): {"recall_at_5": 0.90},
    ("by_category", "multi_source"): {"recall_at_5": 0.90},
    ("by_category", "ambiguity"): {"recall_at_5": 0.50},
}
PLAN_FLOORS: dict[tuple[str, str], dict[str, float]] = {
    ("overall", "all"): {
        "recall_at_5": 0.78,
        "recall_anywhere": 0.83,
        "recall_routed": 0.78,
        "mrr": 0.61,
        "expected_coverage": 0.80,
        "topic_hit": 0.83,
        "portal_hit": 0.90,
    },
    ("by_lang", "en"): {"recall_anywhere": 0.85},
    ("by_lang", "fr"): {"recall_anywhere": 0.81},
    ("by_category", "statcan"): {"recall_anywhere": 0.58},
    ("by_category", "boc"): {"recall_anywhere": 0.81},
    ("by_category", "cmhc"): {"recall_anywhere": 0.72},
    ("by_category", "ckan_federal"): {"recall_anywhere": 0.60},
    ("by_category", "ckan_provincial"): {"recall_anywhere": 0.73},
    ("by_category", "municipal"): {"recall_anywhere": 0.90},
    ("by_category", "multi_source"): {"recall_anywhere": 0.90},
    ("by_category", "ambiguity"): {"recall_anywhere": 0.90, "recall_routed": 0.70},
}


@pytest.fixture(scope="module")
def benchmark() -> runner.Benchmark:
    """The whole benchmark, run once for the module (one client session, one index build)."""
    return runner.run_benchmark(strict=False)


def test_every_expected_tool_topic_and_portal_exists(benchmark: runner.Benchmark):
    assert not benchmark.problems, "\n".join(benchmark.problems)


def test_fixtures_are_big_enough_and_balanced(benchmark: runner.Benchmark):
    queries = benchmark.queries
    assert 100 <= len(queries) <= 150
    for lang in runner.LANGUAGES:
        assert sum(q.lang == lang for q in queries) >= 40, lang
    for category in runner.CATEGORIES:
        assert sum(q.category == category for q in queries) >= 10, category
    assert all(isinstance(q.reviewed, bool) for q in queries)


def test_the_ten_deep_index_agrees_with_the_server(benchmark: runner.Benchmark):
    # Ranks 6 to 10 come from a second BM25 index; it is only trustworthy while its first
    # five equal what search_tools itself returns.
    assert benchmark.report["parity"]["mismatched_ids"] == []


def test_no_query_raises(benchmark: runner.Benchmark):
    for system in ("search", "plan"):
        assert benchmark.report[system]["overall"]["all"]["error_rate"] == 0.0, system


def test_every_query_was_scored_by_the_system_it_expects(benchmark: runner.Benchmark):
    by_id = {row["id"]: row for row in benchmark.report["queries"]}
    for q in benchmark.queries:
        row = by_id[q.id]
        assert (row["search"] is not None) == bool(q.search_expected), q.id
        assert (row["plan"] is not None) == bool(q.plan_expected), q.id


@pytest.mark.parametrize(("group", "name"), list(SEARCH_FLOORS))
def test_search_tools_stays_above_its_floor(benchmark: runner.Benchmark, group: str, name: str):
    measured = benchmark.report["search"][group][name]
    for metric, floor in SEARCH_FLOORS[(group, name)].items():
        assert measured[metric] >= floor, (
            f"search {group}/{name} {metric}: {measured[metric]:.3f} < {floor}"
        )


@pytest.mark.parametrize(("group", "name"), list(PLAN_FLOORS))
def test_plan_query_stays_above_its_floor(benchmark: runner.Benchmark, group: str, name: str):
    measured = benchmark.report["plan"][group][name]
    for metric, floor in PLAN_FLOORS[(group, name)].items():
        assert measured[metric] >= floor, (
            f"plan {group}/{name} {metric}: {measured[metric]:.3f} < {floor}"
        )


def test_two_runs_return_the_same_tools(benchmark: runner.Benchmark):
    def tools(report: dict) -> list[tuple]:
        return [
            (
                row["id"],
                row["search"] and row["search"]["top10"],
                row["plan"] and (row["plan"]["tools"], row["plan"]["topics"]),
            )
            for row in report["queries"]
        ]

    again = runner.run_benchmark(strict=False)
    assert tools(again.report) == tools(benchmark.report)


def test_outputs_are_written_as_json_and_markdown(benchmark: runner.Benchmark, tmp_path: Path):
    runner.write_outputs(benchmark.report, benchmark.queries, tmp_path)
    written = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert (
        written["search"]["overall"]["all"]["n"]
        == benchmark.report["search"]["overall"]["all"]["n"]
    )
    assert len(written["queries"]) == len(benchmark.queries)
    markdown = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert "## search_tools" in markdown and "## plan_query" in markdown
