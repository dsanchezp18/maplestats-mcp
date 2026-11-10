"""v4 grading report: the judge beside each grade, the review queue, and the summary.

`grade --version v4 --judge` grades every answer (JSON block, then regex), asks the judge
(`judge.py`) about each, and writes:

- `results_v4.json` and `results_v4.md`: per arm, the share of questions answered
  correctly (each question weighted once, however many passes it had), for the dev and
  test sets apart and by source, with USD and seconds per answer and the share of answers
  flagged for a person;
- `v4/review_queue.md`: the flagged answers, grouped by question, shuffled, with the arm
  hidden behind a reference. A person settles each in `overrides_v4.json` under
  `"ref:<reference>"` (or `"<arm>/<id>#<pass>"`), with `outcome` and `reason` as before;
  a settled answer leaves the queue.

Every share is computed from exact counts and shown as a percentage.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from tests.maple_test import judge

HERE = Path(__file__).resolve().parent
QUEUE = HERE / "v4" / "review_queue.md"
SPLITS = ("dev", "test")


def ref(row: dict[str, Any]) -> str:
    run = row["run"]
    raw = f"{run['arm']}/{run['question_id']}#{run.get('repeat', 0)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def attach(
    report: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    texts: dict[str, str],
    overrides: dict[str, Any],
    model: str = judge.MODEL,
    workers: int = 6,
) -> None:
    """Ask the judge about every answer that ran; mark the ones a person must read."""
    rows = report["answers"]
    for row in rows:
        row["ref"] = ref(row)
        o = overrides.get(f"ref:{row['ref']}", {})
        if "outcome" in o and not row["grade"]["overridden"]:
            g = row["grade"]
            g["auto_outcome"], g["outcome"], g["reason"] = g["outcome"], o["outcome"], o["reason"]
            g["overridden"] = True
            row["false_claim"] = o.get("false_claim")
            row["referral"] = bool(o.get("referral"))
    todo = [r for r in rows if not r["run"]["is_error"]]
    verdicts = judge.judge_many(
        ((questions[r["run"]["question_id"]], texts[r["ref"]]) for r in todo), model, workers
    )
    for row, verdict in zip(todo, verdicts, strict=True):
        row["judge"] = verdict
        deterministic = row["grade"].get("auto_outcome") or row["grade"]["outcome"]
        # Flagged: sent to a person by the judge. Open: flagged and not yet settled in the
        # overrides file. The report counts the first; the queue lists the second.
        row["flagged"] = judge.needs_review(deterministic, verdict)
        row["needs_review"] = row["flagged"] and not row["grade"]["overridden"]
    for row in rows:
        row.setdefault("flagged", False)
        row.setdefault("needs_review", False)


def _pct(num: float, den: float) -> str:
    return f"{100 * num / den:.1f}%" if den else "–"


def question_share(rows: list[dict[str, Any]]) -> tuple[float, int]:
    """Sum over questions of each one's share of correct passes, and the question count."""
    by_q: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_q[r["run"]["question_id"]].append(r["grade"]["outcome"] == "correct")
    return sum(sum(v) / len(v) for v in by_q.values()), len(by_q)


def summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    arms: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in report["answers"]:
        arms[r["run"]["arm"]].append(r)
    out = []
    for arm, rows in sorted(arms.items()):
        correct, n_q = question_share(rows)
        costs = [r["run"]["cost_usd"] for r in rows if r["run"].get("cost_usd") is not None]
        item = {
            "arm": arm,
            "questions": n_q,
            "answers": len(rows),
            "correct_questions": round(correct, 3),
            "correct_pct": round(100 * correct / n_q, 1),
            "splits": {},
            "sources": {},
            "usd_per_answer": round(sum(costs) / len(costs), 4) if costs else None,
            "usd_total": round(sum(costs), 2) if costs else None,
            "seconds_per_answer": round(sum(r["run"]["duration_s"] for r in rows) / len(rows), 1),
            "errors": sum(r["run"]["is_error"] for r in rows),
            "json_block": sum(r["grade"].get("basis") == "json" for r in rows),
            "flagged": sum(r.get("flagged", False) for r in rows),
            "open": sum(r["needs_review"] for r in rows),
            "judged": sum("outcome" in r.get("judge", {}) for r in rows),
            "judge_agrees": sum(
                r.get("judge", {}).get("outcome")
                == (r["grade"].get("auto_outcome") or r["grade"]["outcome"])
                for r in rows
            ),
            "outcomes": {
                k: sum(r["grade"]["outcome"] == k for r in rows)
                for k in ("correct", "partial", "abstained", "hallucinated")
            },
        }
        for split in SPLITS:
            part = [r for r in rows if r.get("split") == split]
            c, n = question_share(part)
            item["splits"][split] = {
                "questions": n,
                "correct_pct": round(100 * c / n, 1) if n else None,
            }
        for source in sorted({r["group"] for r in rows}):
            c, n = question_share([r for r in rows if r["group"] == source])
            item["sources"][source] = {"questions": n, "correct_pct": round(100 * c / n, 1)}
        out.append(item)
    return out


def render(report: dict[str, Any]) -> str:
    s = report["summary_v4"]
    sources = sorted({k for a in s for k in a["sources"]})
    lines = [
        "# Maple Test v4 results",
        "",
        "> Written by `python -m tests.maple_test grade --version v4`. Do not edit by hand.",
        "",
        (
            "**Correct** is the share of questions answered correctly, each question weighted "
            "once (a question asked three times counts its share of correct passes). Dev is the "
            "public set, test the held-out one (README, 'Version 4')."
        ),
        "",
        (
            "| Arm | Correct | Dev | Test | Answers | USD per answer | Seconds per answer | "
            "Flagged for review | JSON decided | Run errors |"
        ),
        "| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for a in s:
        dev, test = (
            "–"
            if a["splits"][x]["correct_pct"] is None
            else f"{a['splits'][x]['correct_pct']:.1f}%"
            for x in SPLITS
        )
        usd = "–" if a["usd_per_answer"] is None else f"{a['usd_per_answer']:.3f}"
        lines.append(
            f"| {a['arm']} | {a['correct_pct']:.1f}% | {dev} | {test} | "
            f"{a['answers']} | {usd} | {a['seconds_per_answer']} | "
            f"{_pct(a['flagged'], a['answers'])} | {_pct(a['json_block'], a['answers'])} | "
            f"{a['errors']} |"
        )
    lines += [
        "",
        "## By source",
        "",
        "| Arm | " + " | ".join(sources) + " |",
        "| :-- |" + " --: |" * len(sources),
    ]
    for a in s:
        cells = [
            f"{a['sources'][x]['correct_pct']:.1f}% ({a['sources'][x]['questions']})"
            if x in a["sources"]
            else "–"
            for x in sources
        ]
        lines.append(f"| {a['arm']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Judge",
        "",
        "| Arm | Judged | Agrees with the grader | Flagged |",
        "| :-- | --: | --: | --: |",
    ]
    for a in s:
        lines.append(
            f"| {a['arm']} | {a['judged']} | {_pct(a['judge_agrees'], a['judged'])} | "
            f"{a['flagged']} of {a['answers']} ({_pct(a['flagged'], a['answers'])}) |"
        )
    lines += [
        "",
        "## Per answer",
        "",
        "| Question | Split | Arm | Pass | Grade | Basis | Judge | Review |",
    ]
    lines += ["| :-- | :-- | :-- | --: | :-- | :-- | :-- | :-- |"]
    for r in sorted(
        report["answers"],
        key=lambda r: (r["run"]["question_id"], r["run"]["arm"], r["run"]["repeat"]),
    ):
        j = r.get("judge", {})
        verdict = f"{j['outcome']} ({j['confidence']:.2f})" if "outcome" in j else "–"
        mark = "*" if r["grade"]["overridden"] else ""
        lines.append(
            f"| {r['run']['question_id']} | {r.get('split')} | {r['run']['arm']} | "
            f"{r['run']['repeat']} | {r['grade']['outcome']}{mark} | {r['grade'].get('basis')} | "
            f"{verdict} | {'open' if r['needs_review'] else 'settled' if r.get('flagged') else ''} |"
        )
    lines += ["", "`*` settled by a person (overrides_v4.json)."]
    return "\n".join(lines) + "\n"


def queue(report: dict[str, Any], texts: dict[str, str], questions: dict[str, Any]) -> str:
    """The flagged answers, by question, shuffled, arm hidden."""
    flagged = [r for r in report["answers"] if r["needs_review"]]
    lines = [
        "# Maple Test v4 review queue",
        "",
        (
            f"{len(flagged)} of {len(report['answers'])} answers "
            f"({_pct(len(flagged), len(report['answers']))}) need a person: the judge disagreed "
            "with the grader, was unsure, or failed. Settle each in `overrides_v4.json` as "
            '`"ref:<ref>": {"outcome": ..., "reason": "Review: ..."}`. Arms are hidden.'
        ),
    ]
    by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in flagged:
        by_q[r["run"]["question_id"]].append(r)
    rng = random.Random(42)
    for qid in sorted(by_q):
        q = questions[qid]
        rows = by_q[qid]
        rng.shuffle(rows)
        lines += ["", f"## {qid} ({q['qtype']}, {q['split']})", "", f"> {q['question']}", ""]
        lines += [f"Key: `{q['expected']}`", ""]
        for r in rows:
            j = r.get("judge", {})
            lines += [
                f"### ref {r['ref']}",
                "",
                (
                    f"- Grader: **{r['grade']['outcome']}** ({r['grade'].get('basis')}: "
                    f"{r['grade']['reason']})"
                ),
                (
                    f"- Judge: **{j.get('outcome', 'failed')}**, confidence "
                    f"{j.get('confidence', '–')}: {j.get('reason') or j.get('error', '')}"
                ),
                "",
                "```text",
                texts[r["ref"]].strip(),
                "```",
                "",
            ]
    return "\n".join(lines) + "\n"
