"""Item analysis of every graded Maple Test answer: which questions separate servers.

v4 (README, "Version 4") keeps a question only if the arms that compete on it do not all
get it right, or all get it wrong. This script reads the graded, hand-reviewed results of
v1 and v2 (`results.json`, `results_v2.json`, overrides applied) and grades v3's run files
with `overrides_v3.json` applied, then writes, per question:

- each comparable arm's share of correct answers;
- `spread`, the best arm's share minus the worst arm's (0 = the question separates no one);
- `ceiling` (every comparable arm always right) and `floor` (every one always wrong);
- `volatile`: the share of arms whose outcome changed between passes of the same question;
- `grader_error`: the share of answers whose hand-reviewed outcome differs from the regex
  grader's (where the grader most needs the structured answer and the judge).

Comparable arms leave out the model alone (`no_tools*`) and MapleStats runs that are
in-sample (`grade.IN_SAMPLE`, and v3's `maplestats-postfix`): a question that only the
model alone fails still separates no servers. `maplestats-release` counts on the release
questions, which it was the first to answer.

v3 has only two servers' runs (MapleStats and OpenMCP), so its ceiling and floor flags rest
on two servers; its grades are hand-reviewed (`overrides_v3.json`) like v1's and v2's.

    uv run python -m tests.maple_test.item_analysis [--v3-runs PATH ...]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import pstdev
from typing import Any

from tests.maple_test import grade

HERE = Path(__file__).resolve().parent
OUT = HERE / "v4" / "item_analysis.json"
# v3's MapleStats run after the fixes made with v3's answers in view.
V3_IN_SAMPLE = ("maplestats-postfix",)
# In-sample runs that were out of sample for one group: the release questions were written
# and keyed before `maplestats-release` asked them (README, "Release questions").
OUT_OF_SAMPLE_FOR = {"maplestats-release": "release"}


def comparable(arm: str, group: str) -> bool:
    if OUT_OF_SAMPLE_FOR.get(arm) == group:
        return True
    return not (arm.startswith("no_tools") or arm in grade.IN_SAMPLE or arm in V3_IN_SAMPLE)


def rows_for(version: str, v3_runs: list[Path]) -> list[dict[str, Any]]:
    """Graded rows: the results file for v1 and v2, the regex grader for v3's run files."""
    if version == "v3":
        if not v3_runs:
            return []
        return grade.grade_runs(v3_runs, "v3")["answers"]
    path = grade.SUITES[version].results
    return json.loads(path.read_text(encoding="utf-8"))["answers"]


def analyse(v3_runs: list[Path]) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    for version in ("v1", "v2", "v3"):
        questions = {q["id"]: q for q in grade.load_key(version)}
        cells: dict[tuple[str, str], list[str]] = defaultdict(list)
        changed: dict[str, list[bool]] = defaultdict(list)
        for row in rows_for(version, v3_runs):
            arm, qid = row["run"]["arm"], row["run"]["question_id"]
            if not comparable(arm, questions[qid].get("group", "core")):
                continue
            g = row["grade"]
            cells[(qid, arm)].append(g["outcome"])
            changed[qid].append(bool(g.get("auto_outcome")) and g["auto_outcome"] != g["outcome"])
        for qid, q in questions.items():
            arms = sorted({a for (i, a) in cells if i == qid})
            share = {
                a: round(cells[(qid, a)].count("correct") / len(cells[(qid, a)]), 3) for a in arms
            }
            multi = [a for a in arms if len(cells[(qid, a)]) > 1]
            values = list(share.values())
            items[qid] = {
                "version": version,
                "eval_type": q["eval_type"],
                "group": q.get("group", "core"),
                "category": q["category"],
                "arms": len(arms),
                "answers": sum(len(cells[(qid, a)]) for a in arms),
                "correct_share": share,
                "mean": round(sum(values) / len(values), 3) if values else None,
                "spread": round(max(values) - min(values), 3) if values else None,
                "sd": round(pstdev(values), 3) if len(values) > 1 else None,
                "ceiling": bool(values) and all(v == 1 for v in values),
                "floor": bool(values) and all(v == 0 for v in values),
                "volatile": round(sum(len(set(cells[(qid, a)])) > 1 for a in multi) / len(multi), 3)
                if multi
                else None,
                "grader_error": round(sum(changed[qid]) / len(changed[qid]), 3)
                if changed[qid]
                else None,
            }
    return {
        "sources": {
            "v1": "results.json (hand-reviewed)",
            "v2": "results_v2.json (hand-reviewed)",
            "v3": [f"{p.name} (hand-reviewed)" for p in v3_runs] or "none",
        },
        "questions": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.maple_test.item_analysis")
    parser.add_argument("--v3-runs", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    runs = args.v3_runs or sorted(grade.SUITES["v3"].runs.glob("*.jsonl"))
    report = analyse(runs)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
