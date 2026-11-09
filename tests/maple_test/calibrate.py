"""Calibrate the v4 judge against the v1 and v2 hand reviews.

Every v1 and v2 answer was read by a person (README, "How it was graded"), so each one's
final outcome in `results.json` and `results_v2.json` is a human grade, and its
`auto_outcome` (when a person changed it) is what the regex grader said. This script asks
the judge about a sample of those answers, on the questions v4 keeps, and reports:

- **judge agreement**: the judge's outcome equals the person's;
- **grader agreement**: the regex grader's outcome equals the person's;
- **flagged**: the share of answers `judge.needs_review` sends to a person;
- **missed**: unflagged answers whose grade is still wrong (the judge agreed with a wrong
  regex grade), the error a v4 report keeps without a person seeing it;
- **errors caught**: of the answers the regex grader got wrong, the share flagged.

The sample takes every answer whose grade a person changed (up to `--changed`) and a
random sample of the others (`--agreed`), so the rare cases are well represented; the
population figures weight the two strata back to their true sizes. Percentages are
computed from exact counts.

    uv run python -m tests.maple_test.calibrate [--model claude-sonnet-5-5] [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tests.maple_test import grade, judge

HERE = Path(__file__).resolve().parent
OUT = HERE / "v4" / "calibration.json"


def _reviewed(version: str) -> dict[str, Any]:
    """A version's graded answers with the hand review applied.

    v1 and v2 from their results files. v3 is graded here from its run files and
    `overrides_v3.json`, which exists once v3's hand review is merged; until then it has
    no human grades and cannot be used.
    """
    suite = grade.SUITES[version]
    if version != "v3":
        return json.loads(suite.results.read_text(encoding="utf-8"))
    if not suite.overrides.exists():
        raise SystemExit("v3 has no hand review yet (overrides_v3.json is missing)")
    return grade.grade_runs(sorted(suite.runs.glob("*.jsonl")), "v3")


def human_graded(versions: tuple[str, ...] = ("v1", "v2")) -> list[dict[str, Any]]:
    """Answers on v4's questions: text, the regex grade and the person's grade."""
    v4 = {q["id"]: q for q in grade.load_key("v4")}
    texts: dict[tuple[str, str, int], str] = {}
    for version in versions:
        for path in grade.SUITES[version].runs.glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    texts[(r["arm"], r["question_id"], r.get("repeat", 0))] = r["response"]
    rows = []
    for version in versions:
        report = _reviewed(version)
        for row in report["answers"]:
            run, g = row["run"], row["grade"]
            if run["question_id"] not in v4 or run["is_error"]:
                continue
            text = texts.get((run["arm"], run["question_id"], run.get("repeat", 0)))
            if text is None:
                continue
            rows.append(
                {
                    "id": f"{run['arm']}/{run['question_id']}#{run.get('repeat', 0)}",
                    "question_id": run["question_id"],
                    "qtype": v4[run["question_id"]]["qtype"],
                    "human": g["outcome"],
                    "regex": g.get("auto_outcome") or g["outcome"],
                    "text": text,
                }
            )
    return rows


def metrics(rows: list[dict[str, Any]], weights: dict[bool, float]) -> dict[str, Any]:
    """Agreement and triage figures; `weights` maps changed (True/False) to a stratum weight."""

    def w(r: dict[str, Any]) -> float:
        return weights[r["regex"] != r["human"]]

    judged = [r for r in rows if "outcome" in r["verdict"]]
    total = sum(w(r) for r in rows)
    flagged = [r for r in rows if r["flagged"]]
    unflagged = [r for r in rows if not r["flagged"]]
    wrong = [r for r in rows if r["regex"] != r["human"]]
    return {
        "answers": len(rows),
        "judged": len(judged),
        "judge_agreement": sum(w(r) for r in judged if r["verdict"]["outcome"] == r["human"])
        / sum(w(r) for r in judged),
        "regex_agreement": sum(w(r) for r in rows if r["regex"] == r["human"]) / total,
        "flagged": sum(w(r) for r in flagged) / total,
        "missed": sum(w(r) for r in unflagged if r["regex"] != r["human"]) / total,
        "errors_caught": (sum(w(r) for r in wrong if r["flagged"]) / sum(w(r) for r in wrong))
        if wrong
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.maple_test.calibrate")
    parser.add_argument("--model", default=judge.MODEL)
    parser.add_argument("--changed", type=int, default=150)
    parser.add_argument("--agreed", type=int, default=150)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["v1", "v2"],
        choices=["v1", "v2", "v3"],
        help="hand-reviewed versions to calibrate on (v3 once overrides_v3.json is merged)",
    )
    args = parser.parse_args()

    population = human_graded(tuple(args.versions))
    changed = [r for r in population if r["regex"] != r["human"]]
    agreed = [r for r in population if r["regex"] == r["human"]]
    rng = random.Random(42)
    sample = rng.sample(changed, min(args.changed, len(changed))) + rng.sample(
        agreed, min(args.agreed, len(agreed))
    )
    questions = {q["id"]: q for q in grade.load_key("v4")}
    verdicts = judge.judge_many(
        ((questions[r["question_id"]], r["text"]) for r in sample), args.model, args.workers
    )
    for r, v in zip(sample, verdicts, strict=True):
        r["verdict"] = v
        r["flagged"] = judge.needs_review(r["regex"], v)

    n_changed = sum(r["regex"] != r["human"] for r in sample)
    n_agreed = len(sample) - n_changed
    weights = {
        True: len(changed) / n_changed if n_changed else 0.0,
        False: len(agreed) / n_agreed if n_agreed else 0.0,
    }
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sample:
        by_type[r["qtype"]].append(r)
    report = {
        "model": args.model,
        "rubric_version": judge.RUBRIC_VERSION,
        "low_confidence": judge.LOW_CONFIDENCE,
        "population": {"answers": len(population), "changed": len(changed)},
        "sample": {"changed": n_changed, "agreed": n_agreed},
        "sample_unweighted": metrics(sample, {True: 1.0, False: 1.0}),
        "population_weighted": metrics(sample, weights),
        "by_qtype_unweighted": {
            t: metrics(rs, {True: 1.0, False: 1.0}) for t, rs in by_type.items()
        },
        "confusion": Counter(
            f"{r['human']}->{r['verdict'].get('outcome', 'error')}" for r in sample
        ),
        "cost_usd": round(sum(r["verdict"].get("cost_usd") or 0 for r in sample), 2),
        "disagreements": [
            {
                "id": r["id"],
                "human": r["human"],
                "regex": r["regex"],
                "judge": r["verdict"].get("outcome"),
                "confidence": r["verdict"].get("confidence"),
                "reason": r["verdict"].get("reason") or r["verdict"].get("error"),
            }
            for r in sample
            if r["verdict"].get("outcome") != r["human"]
        ],
    }
    OUT.parent.mkdir(exist_ok=True)
    name = OUT.with_name(f"calibration_{args.model}_{''.join(args.versions)}.json")
    name.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    s, p = report["sample_unweighted"], report["population_weighted"]
    print(f"{args.model}: {len(sample)} answers ({n_changed} re-graded by a person)")
    print(f"  judge agreement  {s['judge_agreement']:.1%} (population {p['judge_agreement']:.1%})")
    print(f"  regex agreement  {s['regex_agreement']:.1%} (population {p['regex_agreement']:.1%})")
    print(f"  flagged          {s['flagged']:.1%} (population {p['flagged']:.1%})")
    print(f"  missed           {s['missed']:.1%} (population {p['missed']:.1%})")
    print(f"wrote {name.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
