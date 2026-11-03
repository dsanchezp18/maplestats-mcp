"""Grade Maple Test answers against a version's answer key.

Each answer gets one outcome:

- correct: every expected value within tolerance and, for comparison, refusal and flag
  questions, the right call.
- partial: at least half the values, every headline value, and the right call.
- abstained: declined, or gave no figures.
- hallucinated: stated figures that do not match, gave a figure for something that does
  not exist, or did the misleading calculation without flagging it.

Beside the outcome, each answer's citations are checked against the publishers
(citations.py): IDs that exist, IDs that hold a figure the answer states, invented IDs,
and vectors cited beside a table they do not belong to. A run can repeat every question
(`run --repeat`); the summary then reports the mean per run, the worst and best run, and
how often an arm gave the same outcome to the same question.

Grading reads numbers and phrases out of the text, so it can miss a correct answer worded
oddly. Every non-correct grade should be read by a person; re-grades go in the version's
overrides file as {"<arm>/<question id>": {...}} (every repeat) or
{"<arm>/<question id>#<repeat>": {...}} (one repeat), with "outcome", "reason" and
optionally "false_claim", and are marked in the report.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from tests.maple_test.citations import Cache, CitationCheck

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Suite:
    version: str
    key: Path
    runs: Path
    overrides: Path
    results: Path  # results JSON; the Markdown report sits beside it
    citation_cache: Path


SUITES = {
    "v1": Suite(
        "v1",
        HERE / "maple_test_v1.json",
        HERE / "runs",
        HERE / "overrides.json",
        HERE / "results.json",
        HERE / "citation_checks.json",
    ),
    "v2": Suite(
        "v2",
        HERE / "maple_test_v2.json",
        HERE / "runs_v2",
        HERE / "overrides_v2.json",
        HERE / "results_v2.json",
        HERE / "citation_checks.json",
    ),
}

TABLE = re.compile(r"\b\d{2}-\d{2}-\d{4}(?:-\d{2})?\b|\b\d{10}\b|\b\d{8}\b")
# Vectors run from v1 (Canada's population, 17-10-0009) upward; the first version of this
# pattern wanted four digits and missed v1, v12 and v15.
VECTOR = re.compile(r"\bv\d{1,11}\b", re.IGNORECASE)
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
    r"value|observation|series|estimate)s? (?:was |were |is |are )?(?:published|available|for|"
    r"exists?)|has(?:n't|n’t| not) (?:yet )?been (?:published|released)|does(?:n't|n’t| not) "
    r"(?:publish|exist)|weekend|sunday|saturday|not a business day|market(?:s)? (?:was|were) "
    r"closed|isn't out|is not out|doesn't exist yet|does not exist yet|hasn't ended)",
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
WINNER = re.compile(
    r"\b(highest|most|faster|fastest|more quickly|led|outpac\w*|largest|biggest|higher|lowest|"
    r"smallest|fewer|slower)\b",
    re.IGNORECASE,
)
OUTCOMES = ("correct", "partial", "abstained", "hallucinated")


def load_key(version: str = "v1") -> list[dict[str, Any]]:
    return json.loads(SUITES[version].key.read_text(encoding="utf-8"))["questions"]


def tolerance(key: str, value: float, question: dict[str, Any] | None = None) -> float:
    """How far a stated number may be from the expected one (plus float slack)."""
    slack = 1e-9
    explicit = (question or {}).get("tolerances", {}).get(key)
    if explicit is not None:
        return float(explicit) + slack
    if key.endswith(("_pct", "_pp")):
        return 0.1 + slack
    if key.startswith("usdcad"):
        return 0.00005 + slack
    if key.startswith("yield"):
        return 0.005 + slack
    if key.startswith("awe"):
        return 0.05 + slack
    if key.endswith(("_millions", "_thousands")):
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


def figures_in(text: str) -> list[float]:
    """The numbers that state something: years left out."""
    return [n for n in numbers_in(text) if not YEAR.match(f"{n:g}")]


def _expected_numbers(question: dict[str, Any]) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in question["expected"].items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


@dataclass
class Grade:
    question_id: str
    outcome: str
    reason: str
    recall: float
    tables_cited: list[str] = field(default_factory=list)
    vectors_cited: list[str] = field(default_factory=list)
    table_coverage: float = 0.0
    vector_coverage: float = 0.0
    overridden: bool = False
    citations: dict[str, Any] = field(default_factory=dict)


def _matches(question: dict[str, Any], text: str) -> dict[str, bool]:
    seen = [abs(n) for n in numbers_in(text)]
    matched: dict[str, bool] = {}
    for key, value in _expected_numbers(question).items():
        hit = any(abs(n - abs(value)) <= tolerance(key, value, question) for n in seen)
        # Large counts quoted rounded ("41.8 million") get credit within 0.1%.
        if not hit and abs(value) >= 100_000:
            hit = any(abs(n - abs(value)) <= abs(value) * 0.001 for n in seen)
        # A change of zero to one decimal may be stated in words.
        if not hit and abs(value) < 0.05 and key.endswith("_pct") and UNCHANGED.search(text):
            hit = True
        matched[key] = hit
    return matched


def _key_coverage(question: dict[str, Any], text: str) -> tuple[list[str], list[str], float, float]:
    """Share of the key's own tables and vectors the answer names."""
    statcan = [c for c in question["citations"] if c["table_id"] not in ("Valet", "Other")]
    tables = {c["table_id"][:10] for c in statcan}
    vectors = {c["vector_id"].lower() for c in statcan if c.get("vector_id")}
    valet = {c["vector_id"] for c in question["citations"] if c["table_id"] == "Valet"}
    said_tables = {re.sub(r"\D", "", t)[:8] for t in TABLE.findall(text)}
    want_tables = {re.sub(r"\D", "", t)[:8] for t in tables}
    said_vectors = {v.lower() for v in VECTOR.findall(text)}
    cited_t = sorted(want_tables & said_tables)
    cited_v = sorted(vectors & said_vectors)
    if valet:
        cited_v += [v for v in valet if v.lower() in text.lower()]
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
    figures = figures_in(text)
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
        # A question names its own warning sign when the problem is not mixed years
        # (v2's "multiply an annual rate by 12").
        pattern = question.get("flag_pattern")
        if pattern:
            flagged = bool(re.search(pattern, text, re.IGNORECASE))
        else:
            flagged = all(y in text for y in years) and bool(MISMATCH.search(text))
        direct = all(matched.values()) if matched else False
        if flagged or direct:
            why = "flagged the mismatch" if flagged else "gave the published figure instead"
            outcome, reason = "correct", why
        elif figures:
            outcome, reason = "hallucinated", "did the misleading calculation without a flag"
        else:
            outcome, reason = "abstained", "no answer and no flag"
    else:
        pattern = question.get("answer_pattern")
        right_call = True
        if pattern:
            right_call = bool(
                re.search(
                    rf"{re.escape(pattern)}[^.\n]{{0,80}}{WINNER.pattern}", text, re.IGNORECASE
                )
                or re.search(
                    rf"{WINNER.pattern}[^.\n]{{0,80}}{re.escape(pattern)}", text, re.IGNORECASE
                )
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
    tables, vectors, t_cov, v_cov = _key_coverage(question, text)
    return Grade(question["id"], outcome, reason, round(recall, 2), tables, vectors, t_cov, v_cov)


def load_runs(paths: list[Path]) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(paths):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                runs.append(json.loads(line))
    return runs


def grade_runs(paths: list[Path], version: str = "v1", verify: bool = False) -> dict[str, Any]:
    suite = SUITES[version]
    questions = {q["id"]: q for q in load_key(version)}
    overrides = (
        json.loads(suite.overrides.read_text(encoding="utf-8")) if suite.overrides.exists() else {}
    )
    runs = load_runs(paths)
    cache = Cache(suite.citation_cache)
    if verify:
        cache.fetch([r["response"] for r in runs])
        cache.save()
    rows: list[dict[str, Any]] = []
    for run in runs:
        q = questions[run["question_id"]]
        g = grade_answer(q, run["response"])
        if run["is_error"]:
            g.outcome, g.reason = "abstained", "run error"
        repeat = run.get("repeat", 0)
        base = f"{run['arm']}/{run['question_id']}"
        o = overrides.get(f"{base}#{repeat}", overrides.get(base, {}))
        if "outcome" in o:
            g.outcome, g.reason, g.overridden = o["outcome"], o["reason"], True
        check: CitationCheck = cache.check(run["response"], figures_in(run["response"]))
        g.citations = asdict(check)
        rows.append(
            {
                "run": {k: v for k, v in run.items() if k != "response"},
                "grade": asdict(g),
                "false_claim": o.get("false_claim"),
                "has_figures": bool(figures_in(run["response"])) and q["eval_type"] != "refusal",
                "group": q.get("group", "core"),
            }
        )
    return {
        "benchmark": f"maple_test_{version}",
        "answers": rows,
        "summary": summarise(rows),
    }


def _share(num: float, den: float) -> float | None:
    return round(num / den, 2) if den else None


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    arms: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        arms.setdefault(row["run"]["arm"], []).append(row)
    out = []
    for arm, items in sorted(arms.items()):
        repeats = sorted({i["run"].get("repeat", 0) for i in items})
        per_run = {
            r: {
                k: sum(i["grade"]["outcome"] == k for i in items if i["run"].get("repeat", 0) == r)
                for k in OUTCOMES
            }
            for r in repeats
        }
        by_question: dict[str, set[str]] = {}
        for i in items:
            by_question.setdefault(i["run"]["question_id"], set()).add(i["grade"]["outcome"])
        cites = [i["grade"]["citations"] for i in items]
        cited = sum(len(c["vectors"]) + len(c["valet"]) for c in cites)
        supporting = sum(len(c["vectors_supporting"]) + len(c["valet_supporting"]) for c in cites)
        with_figures = [i for i in items if i["has_figures"]]
        costs = [i["run"]["cost_usd"] for i in items if i["run"].get("cost_usd") is not None]
        # v2 reports the core half (StatCan, Bank of Canada) and the beyond half apart.
        groups = {}
        for g in sorted({i.get("group", "core") for i in items}):
            in_group = [i for i in items if i.get("group", "core") == g]
            groups[g] = {
                "questions": len({i["run"]["question_id"] for i in in_group}),
                "correct": round(
                    mean(
                        sum(
                            i["grade"]["outcome"] == "correct"
                            for i in in_group
                            if i["run"].get("repeat", 0) == r
                        )
                        for r in repeats
                    ),
                    1,
                ),
            }
        out.append(
            {
                "arm": arm,
                "model_ids": sorted({m for i in items for m in i["run"]["model_ids"]}),
                "run_date": min(i["run"]["started_at"][:10] for i in items),
                "questions": len(by_question),
                "repeats": len(repeats),
                **{k: round(mean(p[k] for p in per_run.values()), 1) for k in OUTCOMES},
                "correct_worst": min(p["correct"] for p in per_run.values()),
                "correct_best": max(p["correct"] for p in per_run.values()),
                "consistency": _share(
                    sum(len(v) == 1 for v in by_question.values()), len(by_question)
                )
                if len(repeats) > 1
                else None,
                "false_claims": sum(bool(i["false_claim"]) for i in items),
                "table_coverage": round(mean(i["grade"]["table_coverage"] for i in items), 2),
                "vector_coverage": round(mean(i["grade"]["vector_coverage"] for i in items), 2),
                "ids_cited": cited,
                "citation_precision": _share(supporting, cited),
                "invented_ids": sum(
                    len(c["vectors_invented"]) + len(c["tables_invented"]) for c in cites
                ),
                "off_table_vectors": sum(len(c["vectors_off_table"]) for c in cites),
                "traceability": _share(
                    sum(i["grade"]["citations"]["traceable"] for i in with_figures),
                    len(with_figures),
                ),
                "release_mentions": _share(sum(c["release_mentioned"] for c in cites), len(cites)),
                "tool_calls": round(mean(len(i["run"]["tool_calls"]) for i in items), 1),
                "seconds": round(mean(i["run"]["duration_s"] for i in items), 1),
                "cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
                "errors": sum(i["run"]["is_error"] for i in items),
                "groups": groups,
            }
        )
    return out


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def render(report: dict[str, Any], version: str = "v1") -> str:
    summary = report["summary"]
    repeated = any(s["repeats"] > 1 for s in summary)
    group_names = sorted({g for s in summary for g in s.get("groups", {})})
    split = len(group_names) > 1
    lines = [
        f"# Maple Test {version} results",
        "",
        "> Written by `python -m tests.maple_test grade`. Do not edit by hand.",
        "",
        "## Answers",
        "",
        "Outcomes are per run"
        + (" (mean over repeats; worst and best run beside correct)" if repeated else "")
        + ".",
        "",
        "| Arm | Correct | "
        + "".join(f"{g.capitalize()} | " for g in group_names if split)
        + ("Worst–best | Consistency | " if repeated else "")
        + "Partial | Abstained | Hallucinated | False claims |",
        "| :-- | --: | "
        + ("--: | " * len(group_names) if split else "")
        + ("--: | --: | " if repeated else "")
        + "--: | --: | --: | --: |",
    ]
    for s in summary:
        extra = (
            f"{s['correct_worst']}–{s['correct_best']} | {_pct(s['consistency'])} | "
            if repeated
            else ""
        )
        halves = (
            "".join(
                f"{s['groups'][g]['correct']:g} of {s['groups'][g]['questions']} | "
                for g in group_names
                if g in s["groups"]
            )
            if split
            else ""
        )
        lines.append(
            f"| {s['arm']} | {s['correct']:g} | {halves}{extra}{s['partial']:g} "
            f"| {s['abstained']:g} "
            f"| {s['hallucinated']:g} | {s['false_claims']} |"
        )
    lines += [
        "",
        "## Citations and cost",
        "",
        "- **Key coverage:** share of the answer key's own tables and vectors the answer names.",
        (
            "- **Precision:** of the StatCan vectors and Bank of Canada series an answer cites, the "
            "share that hold a figure the answer states (checked against the publishers)."
        ),
        (
            "- **Invented:** cited StatCan vectors or tables that do not exist. **Off-table:** a "
            "vector cited beside a table it does not belong to."
        ),
        (
            "- **Traceable:** answers stating figures in which at least one cited ID holds one of "
            "them. **Release:** answers that mention a release date."
        ),
        "",
        (
            "| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table "
            "| Traceable | Release | Tool calls | Seconds | Cost (USD) |"
        ),
        "| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for s in summary:
        cost = "–" if s["cost_usd"] is None else f"{s['cost_usd']:.3f}"
        lines.append(
            f"| {s['arm']} | {_pct(s['table_coverage'])} | {_pct(s['vector_coverage'])} "
            f"| {s['ids_cited']} | {_pct(s['citation_precision'])} | {s['invented_ids']} "
            f"| {s['off_table_vectors']} | {_pct(s['traceability'])} "
            f"| {_pct(s['release_mentions'])} | {s['tool_calls']} | {s['seconds']} | {cost} |"
        )
    arms = [s["arm"] for s in summary]
    outcomes: dict[tuple[str, str], list[str]] = {}
    for r in report["answers"]:
        mark = r["grade"]["outcome"] + ("*" if r["grade"]["overridden"] else "")
        outcomes.setdefault((r["run"]["arm"], r["run"]["question_id"]), []).append(mark)
    lines += [
        "",
        "## Per question",
        "",
        "| Question | " + " | ".join(arms) + " |",
        "| :-- |" + " :-: |" * len(arms),
    ]
    for q in load_key(version):
        cells = [" / ".join(outcomes.get((arm, q["id"]), ["–"])) for arm in arms]
        lines.append(f"| {q['id']} {q['category']} | " + " | ".join(cells) + " |")
    lines += ["", "`*` re-graded by hand (see the overrides file)."]
    claims = [r for r in report["answers"] if r["false_claim"]]
    if claims:
        lines += ["", "## False claims", ""]
        lines += [
            f"- {r['run']['arm']} {r['run']['question_id']}: {r['false_claim']}" for r in claims
        ]
    return "\n".join(lines) + "\n"
