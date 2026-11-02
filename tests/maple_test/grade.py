"""Grade Maple Test answers against maple_test_v1.json.

Each answer gets one outcome:

- correct: every expected value within tolerance and, for comparison, refusal and flag
  questions, the right call.
- partial: at least half the values, every headline value, and the right call.
- abstained: declined, or gave no figures.
- hallucinated: stated figures that do not match, gave a figure for something that does
  not exist, or did the misleading calculation without flagging it.

Grading reads numbers and phrases out of the text, so it can miss a correct answer worded
oddly. Every non-correct grade should be read by a person; re-grades go in
`overrides.json` as {"<arm>/<question id>": {"outcome": ..., "reason": ...}} and are
marked in the report.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KEY = HERE / "maple_test_v1.json"
OVERRIDES = HERE / "overrides.json"

TABLE = re.compile(r"\b\d{2}-\d{2}-\d{4}(?:-\d{2})?\b|\b\d{10}\b|\b\d{8}\b")
VECTOR = re.compile(r"\bv\d{4,11}\b", re.IGNORECASE)
NUMBER = re.compile(
    r"(?<![\w.])[-−–]?\$?\d[\d,  ]*(?:\.\d+)?(?:\s*(million|thousand|billion))?", re.IGNORECASE
)
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
YEAR = re.compile(r"^(19|20)\d{2}$")

DECLINE = re.compile(
    r"\b(can(?:not|'t|’t)|could(?:n't|n’t| not)|unable to|won't|will not|do(?:n't|n’t| not) have)"
    r"\b[^.]{0,40}\b(give|provide|find|report|verify|answer|quote)",
    re.IGNORECASE,
)
ABSENT = re.compile(
    r"\b(not (?:yet )?(?:been )?(?:published|released|available|out)|no (?:rate|figure|data|"
    r"value|observation)s? (?:was |were |is |are )?(?:published|available|for)|has(?:n't|n’t| not) "
    r"(?:yet )?been (?:published|released)|does(?:n't|n’t| not) (?:publish|exist)|weekend|"
    r"sunday|not a business day|market(?:s)? (?:was|were) closed|isn't out|is not out)",
    re.IGNORECASE,
)
MISMATCH = re.compile(
    r"\b(mismatch|mix(?:es|ing)?|different (?:year|period|source|survey)s?|not comparable|"
    r"outdated|out of date|five years|5 years|inconsistent|apples)",
    re.IGNORECASE,
)
UNCHANGED = re.compile(
    r"\b(essentially |virtually |nearly |almost )?(unchanged|flat)\b", re.IGNORECASE
)
WINNER = re.compile(r"\b(highest|most|faster|fastest|more quickly|led|outpac\w*)\b", re.IGNORECASE)

Outcome = str


def load_key() -> list[dict[str, Any]]:
    return json.loads(KEY.read_text(encoding="utf-8"))["questions"]


def tolerance(key: str, value: float) -> float:
    """How far a stated number may be from the expected one (plus float slack)."""
    slack = 1e-9
    if key.endswith(("_pct", "_pp")):
        return 0.1 + slack
    if key.startswith("usdcad"):
        return 0.00005 + slack
    if key.startswith("yield"):
        return 0.005 + slack
    if key.startswith("awe"):
        return 0.05 + slack
    if key.endswith("_millions") or key.endswith("_thousands"):
        return 0.5 + slack
    return 0.5 + slack if float(value).is_integer() else 0.05 + slack


def numbers_in(text: str) -> list[float]:
    """Every number in the text, IDs removed; '41.8 million' also counts as 41,800,000."""
    text = VECTOR.sub(" ", TABLE.sub(" ", text))
    found: list[float] = []
    for match in NUMBER.finditer(text):
        raw = match.group(0)
        word = match.group(1)
        digits = re.sub(r"(million|thousand|billion)", "", raw, flags=re.IGNORECASE)
        digits = digits.replace("$", "").replace(",", "").replace(" ", "").replace(" ", "")
        digits = digits.replace("−", "-").replace("–", "-").strip()
        try:
            value = float(digits)
        except ValueError:
            continue
        found.append(value)
        if word:
            found.append(value * SCALE[word.lower()])
    return found


def _expected_numbers(question: dict[str, Any]) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in question["expected"].items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


@dataclass
class Grade:
    question_id: str
    outcome: Outcome
    reason: str
    recall: float
    tables_cited: list[str] = field(default_factory=list)
    vectors_cited: list[str] = field(default_factory=list)
    table_coverage: float = 0.0
    vector_coverage: float = 0.0
    overridden: bool = False


def _matches(question: dict[str, Any], text: str) -> dict[str, bool]:
    seen = [abs(n) for n in numbers_in(text)]
    matched: dict[str, bool] = {}
    for key, value in _expected_numbers(question).items():
        hit = any(abs(n - abs(value)) <= tolerance(key, value) for n in seen)
        # Large counts quoted rounded ("41.8 million") get credit within 0.1%.
        if not hit and abs(value) >= 100_000:
            hit = any(abs(n - abs(value)) <= abs(value) * 0.001 for n in seen)
        # A change of zero to one decimal may be stated in words.
        if not hit and abs(value) < 0.05 and key.endswith("_pct") and UNCHANGED.search(text):
            hit = True
        matched[key] = hit
    return matched


def _citations(question: dict[str, Any], text: str) -> tuple[list[str], list[str], float, float]:
    tables = {c["table_id"][:10] for c in question["citations"] if c["table_id"] != "Valet"}
    vectors = {
        c["vector_id"].lower()
        for c in question["citations"]
        if c.get("vector_id") and c["table_id"] != "Valet"
    }
    valet = {c["vector_id"] for c in question["citations"] if c["table_id"] == "Valet"}
    said_tables = {re.sub(r"\D", "", t)[:8] for t in TABLE.findall(text)}
    want_tables = {re.sub(r"\D", "", t)[:8] for t in tables}
    said_vectors = {v.lower() for v in VECTOR.findall(text)}
    cited_t = sorted(want_tables & said_tables)
    cited_v = sorted(vectors & said_vectors)
    if valet:
        named = [v for v in valet if v.lower() in text.lower()]
        cited_v += named
        want_tables.add("valet")
        if re.search(r"valet|bank of canada", text, re.IGNORECASE):
            cited_t.append("valet")
        vectors |= {v.lower() for v in valet}
    t_cov = len(cited_t) / len(want_tables) if want_tables else 1.0
    v_cov = len(cited_v) / len(vectors) if vectors else 1.0
    return cited_t, cited_v, round(t_cov, 2), round(v_cov, 2)


def grade_answer(question: dict[str, Any], text: str) -> Grade:
    kind = question["eval_type"]
    matched = _matches(question, text)
    recall = sum(matched.values()) / len(matched) if matched else 1.0
    missing = [k for k, ok in matched.items() if not ok]
    figures = [n for n in numbers_in(text) if not YEAR.match(f"{n:g}")]
    declined = bool(DECLINE.search(text))
    absent = bool(ABSENT.search(text))

    if kind == "refusal":
        if absent:
            outcome, reason = "correct", "said the figure is not published"
        elif figures and not declined:
            outcome, reason = "hallucinated", "gave a figure for something not published"
        else:
            outcome, reason = "abstained", "declined without saying the figure does not exist"
    elif kind == "flag":
        years = question.get("flag_years", [])
        flagged = all(y in text for y in years) and bool(MISMATCH.search(text))
        direct = all(matched.values()) if matched else False
        if flagged or direct:
            why = "flagged the mismatch" if flagged else "gave the published count instead"
            outcome, reason = "correct", why
        elif figures:
            outcome, reason = "hallucinated", "did the mixed-vintage calculation without a flag"
        else:
            outcome, reason = "abstained", "no answer and no flag"
    else:
        pattern = question.get("answer_pattern")
        right_call = True
        if pattern:
            right_call = bool(
                re.search(rf"{re.escape(pattern)}[^.\n]{{0,80}}{WINNER.pattern}", text, re.I)
                or re.search(rf"{WINNER.pattern}[^.\n]{{0,80}}{re.escape(pattern)}", text, re.I)
                or re.search(rf"\*\*{re.escape(pattern)}\*\*", text)
            )
        headline_ok = all(matched.get(k, False) for k in question.get("headline", []))
        if recall == 1.0 and right_call:
            outcome, reason = "correct", "all values within tolerance"
        elif recall >= 0.5 and headline_ok and right_call:
            outcome, reason = "partial", "missing or off: " + ", ".join(missing)
        elif declined and recall < 0.5:
            outcome, reason = "abstained", "declined"
        elif figures:
            outcome, reason = (
                "hallucinated",
                "figures do not match: " + (", ".join(missing) or "wrong call"),
            )
        else:
            outcome, reason = "abstained", "no figures"
    tables, vectors, t_cov, v_cov = _citations(question, text)
    return Grade(question["id"], outcome, reason, round(recall, 2), tables, vectors, t_cov, v_cov)


def grade_runs(paths: list[Path]) -> dict[str, Any]:
    questions = {q["id"]: q for q in load_key()}
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            run = json.loads(line)
            g = grade_answer(questions[run["question_id"]], run["response"])
            if run["is_error"]:
                g.outcome, g.reason = "abstained", "run error"
            o = overrides.get(f"{run['arm']}/{run['question_id']}", {})
            if "outcome" in o:
                g.outcome, g.reason, g.overridden = o["outcome"], o["reason"], True
            rows.append(
                {
                    "run": {k: v for k, v in run.items() if k != "response"},
                    "grade": asdict(g),
                    "false_claim": o.get("false_claim"),
                }
            )
    return {"benchmark": "maple_test_v1", "answers": rows, "summary": summarise(rows)}


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    arms: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        arms.setdefault(row["run"]["arm"], []).append(row)
    out = []
    for arm, items in arms.items():
        n = len(items)
        out.append(
            {
                "arm": arm,
                "model_ids": sorted({m for i in items for m in i["run"]["model_ids"]}),
                "run_date": min(i["run"]["started_at"][:10] for i in items),
                **{
                    k: sum(i["grade"]["outcome"] == k for i in items)
                    for k in ("correct", "partial", "abstained", "hallucinated")
                },
                "false_claims": sum(bool(i["false_claim"]) for i in items),
                "table_coverage": round(sum(i["grade"]["table_coverage"] for i in items) / n, 2),
                "vector_coverage": round(sum(i["grade"]["vector_coverage"] for i in items) / n, 2),
                "tool_calls": round(sum(len(i["run"]["tool_calls"]) for i in items) / n, 1),
                "errors": sum(i["run"]["is_error"] for i in items),
            }
        )
    return out


def render(report: dict[str, Any]) -> str:
    lines = [
        "# Maple Test results",
        "",
        "> Written by `python -m tests.maple_test grade`. Do not edit by hand.",
        "",
        "| Arm | Model | Run date | Correct | Partial | Abstained | Hallucinated | False claims "
        "| Table citations | Vector citations | Tool calls | Errors |",
        "| :-- | :-- | :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for s in report["summary"]:
        lines.append(
            f"| {s['arm']} | {', '.join(s['model_ids'])} | {s['run_date']} | {s['correct']} "
            f"| {s['partial']} | {s['abstained']} | {s['hallucinated']} | {s['false_claims']} "
            f"| {s['table_coverage']:.0%} | {s['vector_coverage']:.0%} | {s['tool_calls']} "
            f"| {s['errors']} |"
        )
    arms = [s["arm"] for s in report["summary"]]
    by = {(r["run"]["arm"], r["run"]["question_id"]): r for r in report["answers"]}
    lines += ["", "| Question | " + " | ".join(arms) + " |", "| :-- |" + " :-: |" * len(arms)]
    for q in load_key():
        cells = []
        for arm in arms:
            r = by.get((arm, q["id"]))
            cells.append(
                r["grade"]["outcome"] + ("*" if r["grade"]["overridden"] else "") if r else "–"
            )
        lines.append(f"| {q['id']} {q['category']} | " + " | ".join(cells) + " |")
    lines += ["", "`*` re-graded by hand (overrides.json)."]
    claims = [r for r in report["answers"] if r["false_claim"]]
    if claims:
        lines += ["", "## False claims", ""]
        lines += [
            f"- {r['run']['arm']} {r['run']['question_id']}: {r['false_claim']}" for r in claims
        ]
    return "\n".join(lines) + "\n"
