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
optionally "false_claim" (the claim, as text) and "referral", and are marked in the report.

A false claim is a statement about the data that is verifiably false: that a figure is or
is not published when the opposite is true, or a wrong unit, basis or coverage presented as
fact. A referral (an answer that gives no figure and sends the user to another publisher's
page, for a source the arm does not claim to cover) is counted separately, not as a false
claim. Every v2 answer was read for both, not only the ones the grader missed.
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
    # Technical data and documentation questions (README, "Version 3"), out of sample.
    "v3": Suite(
        "v3",
        HERE / "maple_test_v3.json",
        HERE / "runs_v3",
        HERE / "overrides_v3.json",
        HERE / "results_v3.json",
        HERE / "citation_checks.json",
    ),
    # One de-duplicated set drawn from v1 to v3, split into dev and test, answered with a
    # closing JSON block and checked by an LLM judge (README, "Version 4").
    "v4": Suite(
        "v4",
        HERE / "maple_test_v4.json",
        HERE / "runs_v4",
        HERE / "overrides_v4.json",
        HERE / "results_v4.json",
        HERE / "citation_checks.json",
    ),
}

TABLE = re.compile(r"\b\d{2}-\d{2}-\d{4}(?:-\d{2})?\b|\b\d{10}\b|\b\d{8}\b")
# Vectors run from v1 (Canada's population, 17-10-0009) upward; the first version of this
# pattern wanted four digits and missed v1, v12 and v15.
VECTOR = re.compile(r"\bv\d{1,11}\b", re.IGNORECASE)
# A thousands separator (comma, space or no-break space) must be followed by exactly three
# digits. The pattern once took any run of digits, commas and spaces, so "July 1, 2026,
# 399,133" read as one number and correct answers were graded hallucinated (v2 review).
NUMBER = re.compile(
    r"(?<![\w.])[-−–]?\$?\d+(?:[,   ]\d{3}(?!\d))*(?:\.\d+)?"
    r"(?:\s*(million|thousand|billion))?",
    re.IGNORECASE,
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
    r"closed|isn't out|is not out|doesn't exist yet|does not exist yet|hasn't ended|"
    # Found in v2 runs: correct refusals the phrases above missed ("isn't available yet",
    # "Statistics Canada hasn't published", "has no 2025 value").
    r"(?:is|are)(?:n't|n’t| not) (?:yet )?(?:available|published|released|out) yet|"
    r"(?:has|have)(?:n't|n’t| not) (?:yet )?(?:published|released)|"
    r"(?:has|have) no (?:\d{4} )?(?:value|figure|data|estimate|observation)s?\b|"
    r"there is no (?:\w+ )?(?:figure|value|number|data))",
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
# Report column names for groups that do not read well capitalized (v3's sources).
GROUP_LABELS = {"boc": "BoC", "cmhc": "CMHC", "statcan": "StatCan"}


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


MONTH_NUMBERS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        1,
    )
    for name in names
}
_MONTH = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
# "November 5, 2026", "Nov. 5", "Thursday, November 5th, 2026", "5 November 2026", "2026-11-05".
DATE_WORDS = re.compile(
    rf"\b(?P<m1>{_MONTH})\.?\s+(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y1>20\d\d))?"
    rf"|\b(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m2>{_MONTH})\.?(?:,?\s+(?P<y2>20\d\d))?\b"
    r"|\b(?P<y3>20\d\d)-(?P<m3>\d{2})-(?P<d3>\d{2})\b",
    re.IGNORECASE,
)


def dates_in(text: str) -> list[tuple[int | None, int, int]]:
    """Every calendar date written in the text, as (year or None, month, day)."""
    found: list[tuple[int | None, int, int]] = []
    for m in DATE_WORDS.finditer(text):
        if m.group("y3"):
            year, month, day = int(m.group("y3")), int(m.group("m3")), int(m.group("d3"))
        else:
            name = (m.group("m1") or m.group("m2")).lower()
            year_text = m.group("y1") or m.group("y2")
            year = int(year_text) if year_text else None
            month, day = MONTH_NUMBERS[name], int(m.group("d1") or m.group("d2"))
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.append((year, month, day))
    return found


def _date_matches(question: dict[str, Any], text: str) -> dict[str, bool]:
    """Expected ISO dates the text states; a date written without a year counts."""
    seen = dates_in(text)
    matched = {}
    for key, value in question["expected"].items():
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            continue
        y, m, d = (int(p) for p in value.split("-"))
        matched[key] = any(sm == m and sd == d and sy in (None, y) for sy, sm, sd in seen)
    return matched


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
    # The grader's own outcome, kept when a person re-grades it, so the report can show
    # which way the review moved each arm.
    auto_outcome: str = ""
    citations: dict[str, Any] = field(default_factory=dict)
    # v4: "json" when the closing JSON block decided the outcome, "regex" when the prose did.
    basis: str = "regex"


# v4 answers end with a fenced JSON block (run.PROMPTS["v4"]); the last one is the answer's.
JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def structured_block(text: str) -> dict[str, Any] | None:
    """The answer's closing JSON block, or None when there is none or it does not parse."""
    for raw in reversed(JSON_BLOCK.findall(text)):
        try:
            block = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(block, dict):
            return block
    return None


def _block_text(block: dict[str, Any]) -> str:
    """The block's values and sources as plain sentences, for the same patterns as prose.

    "68.3" with unit "thousands" reads as "68.3 thousands", which `numbers_in` scales like
    prose; a date value "2026-11-05" reads as a date.
    """
    lines = []
    for v in block.get("values") or []:
        if not isinstance(v, dict) or v.get("value") in (None, ""):
            continue
        value = v["value"]
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        parts = [str(v.get("name") or ""), str(value), str(v.get("unit") or "")]
        if v.get("period"):
            parts.append(f"({v['period']})")
        lines.append(" ".join(p for p in parts if p).strip() + ".")
    for c in block.get("sources") or []:
        if isinstance(c, dict):
            lines.append(" ".join(str(x) for x in c.values() if x) + ".")
        elif c:
            lines.append(f"{c}.")
    return "\n".join(lines)


def grade_structured(question: dict[str, Any], text: str) -> Grade | None:
    """Grade from the JSON block when it settles the answer; None to fall back to prose.

    The block settles an answer only in its favour or as a plain abstention: every expected
    value, date or fact stated in the block's values (and, for a comparison, the right
    call), a refusal question answered with `not_published`, or `abstain` with no values.
    Anything else (no block, a value off, a missing fact) goes to the regex grader on the
    whole text, block included, so a block can never make an answer worse than its prose.
    """
    block = structured_block(text)
    if block is None:
        return None
    kind = question["eval_type"]
    values = [v for v in block.get("values") or [] if isinstance(v, dict)]
    has_values = any(v.get("value") not in (None, "") for v in values)
    not_published = block.get("not_published") is True
    abstain = block.get("abstain") is True
    said = _block_text(block)
    outcome: str | None = None
    reason = ""
    if kind == "refusal" and not_published:
        outcome, reason = "correct", "JSON: not_published"
    elif abstain and not has_values and not not_published:
        outcome, reason = "abstained", "JSON: abstain, " + str(block.get("abstain_reason") or "")
    elif kind == "date":
        dated = _date_matches(question, said)
        table = question.get("table_pattern")
        table_ok = not table or bool(re.search(table, said + "\n" + text, re.IGNORECASE))
        if dated and all(dated.values()) and table_ok:
            outcome, reason = "correct", "JSON: every expected date"
    elif kind == "facts":
        facts = question["facts"]
        wrong = any(re.search(p, text, re.IGNORECASE) for p in question.get("wrong", []))
        if not wrong and all(re.search(p, said, re.IGNORECASE) for p in facts.values()):
            outcome, reason = "correct", "JSON: every expected fact"
    elif kind in ("numeric", "comparison"):
        matched = _matches(question, said)
        regex = grade_answer(question, said + "\n" + text)
        call_ok = regex.outcome == "correct" or not question.get("answer_pattern")
        if matched and all(matched.values()) and call_ok:
            outcome, reason = "correct", "JSON: all values within tolerance"
    if outcome is None:
        return None
    g = grade_answer(question, text)
    g.outcome, g.reason, g.basis = outcome, reason, "json"
    return g


def grade_v4(question: dict[str, Any], text: str) -> Grade:
    """v4: the JSON block first, then the regex grader on the whole answer."""
    return grade_structured(question, text) or grade_answer(question, text)


def _alternative_matched(question: dict[str, Any], text: str) -> dict[str, Any] | None:
    """The documented alternative answer whose values the text all states, if any.

    A key lists `alternatives` when the question, as worded, has another published answer
    (X-12 does not name the BIS, so each country's own series answers it too; A-02's
    payroll-survey figure may be the latest month or the last annual average). An
    alternative's `outcome` says what it earns: correct unless it says partial (A-04: the
    income survey's median, which is not a household unit).
    """
    for alt in question.get("alternatives", []):
        variant = {**question, "expected": alt["expected"]}
        found = _matches(variant, text)
        if found and all(found.values()):
            return alt
    return None


def _matches(question: dict[str, Any], text: str) -> dict[str, bool]:
    seen = [abs(n) for n in numbers_in(text)]
    matched: dict[str, bool] = {}
    for key, value in _expected_numbers(question).items():
        hit = any(abs(n - abs(value)) <= tolerance(key, value, question) for n in seen)
        # A value keyed in thousands or millions may be written out in full ("68,300 jobs"
        # for a change of -68.3 thousand).
        unit = {"_thousands": 1e3, "_millions": 1e6}.get(
            next((u for u in ("_thousands", "_millions") if key.endswith(u)), ""), 0
        )
        if not hit and unit:
            hit = any(abs(n / unit - abs(value)) <= tolerance(key, value, question) for n in seen)
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
    # A refusal question can name its own wording for "this does not exist" (a cancelled
    # drug, an Express Entry round not yet held), on top of the general phrases.
    own = question.get("absent_pattern")
    absent = bool(ABSENT.search(text)) or bool(own and re.search(own, text, re.IGNORECASE))

    if kind == "date":
        # Release-date questions (v2's release group): the expected dates, and for R-03 the
        # table that now holds the series. Other dates in the answer are fine (an earlier
        # release named for context); only an answer with none of the expected dates and a
        # date of its own is graded as a wrong date.
        dated = _date_matches(question, text)
        recall = sum(dated.values()) / len(dated) if dated else 0.0
        missing = [k for k, ok in dated.items() if not ok]
        table = question.get("table_pattern")
        table_ok = not table or bool(re.search(table, text, re.IGNORECASE))
        headline_ok = all(dated.get(k, False) for k in question.get("headline", []))
        if recall == 1.0 and table_ok:
            outcome, reason = "correct", "every expected date"
        elif recall == 1.0 or (recall >= 0.5 and headline_ok):
            outcome = "partial"
            reason = "missing: " + ", ".join(missing + ([] if table_ok else ["the table"]))
        elif dates_in(text) and not declined:
            outcome, reason = "hallucinated", "gave a date that is not the release date"
        else:
            outcome, reason = "abstained", "no release date"
    elif kind == "facts":
        # v3: text answers (a definition, a licence, a field type), graded on the facts each
        # must state, one pattern per fact; `wrong` holds statements the key shows are false.
        hit = {k: bool(re.search(p, text, re.IGNORECASE)) for k, p in question["facts"].items()}
        recall = sum(hit.values()) / len(hit)
        missing = [k for k, ok in hit.items() if not ok]
        wrong = any(re.search(p, text, re.IGNORECASE) for p in question.get("wrong", []))
        headline_ok = all(hit.get(k, False) for k in question.get("headline", []))
        if wrong:
            outcome, reason = "hallucinated", "states a fact the key shows is false"
        elif recall == 1.0:
            outcome, reason = "correct", "every expected fact"
        elif recall >= 0.5 and headline_ok:
            outcome, reason = "partial", "missing: " + ", ".join(missing)
        elif declined or (not any(hit.values()) and not figures):
            outcome, reason = "abstained", "declined, or none of the key's facts"
        else:
            # Some facts wrong or missing, or none right with a code or figure of its own.
            outcome, reason = "hallucinated", "missing: " + ", ".join(missing)
    elif kind == "refusal":
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
        # When the question asks for a figure, the key holds it (or documents an
        # alternative), and a flag alone is not the whole answer: the flag passed on
        # pattern alone until v2's review found flagged answers with no figure, or the
        # wrong one, graded correct.
        alternative = _alternative_matched(question, text)
        has_figure = (all(matched.values()) if matched else False) or alternative is not None
        if flagged and (has_figure or not question.get("figure_required")):
            outcome, reason = "correct", "flagged the problem"
        elif flagged:
            # Naming the right source without a figure (A-02) is no answer at all.
            outcome = question.get("flag_alone", "partial")
            reason = "flagged the problem without the key's figure"
        elif has_figure:
            outcome, reason = "correct", "gave the published figure instead"
        elif figures:
            outcome, reason = "hallucinated", "did the misleading calculation without a flag"
        else:
            outcome, reason = "abstained", "no answer and no flag"
    else:
        pattern = question.get("answer_pattern")
        right_call = True
        if question.get("answer_regex"):
            # A direction stated in words ("strengthened", "lower"): any phrasing the regex
            # allows is the call (v4's fresh test set).
            right_call = bool(re.search(question["answer_regex"], text, re.IGNORECASE))
        elif pattern and question.get("answer_contains"):
            # A name answer (a brand, a status): naming it is the call.
            right_call = bool(re.search(rf"\b{re.escape(pattern)}\b", text, re.IGNORECASE))
        elif pattern:
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
        alternative = _alternative_matched(question, text)
        if recall == 1.0 and right_call:
            outcome, reason = "correct", "all values within tolerance"
        elif alternative and right_call:
            outcome = alternative.get("outcome", "correct")
            reason = f"values match the alternative: {alternative['label']}"
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
    retired = sorted({r["question_id"] for r in runs} - set(questions))
    for run in runs:
        # A run made with an earlier key can hold questions the key has since dropped (v4's
        # selection changed when v3's hand review came in); they are left out, and listed.
        if run["question_id"] not in questions:
            continue
        q = questions[run["question_id"]]
        g = grade_v4(q, run["response"]) if version == "v4" else grade_answer(q, run["response"])
        if run["is_error"]:
            g.outcome, g.reason = "abstained", "run error"
        repeat = run.get("repeat", 0)
        base = f"{run['arm']}/{run['question_id']}"
        o = overrides.get(f"{base}#{repeat}", overrides.get(base, {}))
        if "outcome" in o:
            g.auto_outcome = g.outcome
            g.outcome, g.reason, g.overridden = o["outcome"], o["reason"], True
        check: CitationCheck = cache.check(run["response"], figures_in(run["response"]))
        g.citations = asdict(check)
        rows.append(
            {
                "run": {k: v for k, v in run.items() if k != "response"},
                "grade": asdict(g),
                "false_claim": o.get("false_claim"),
                # Declined and pointed the user to another publisher's page for a source the
                # arm does not cover: counted apart from false claims (v2 review).
                "referral": bool(o.get("referral")),
                "has_figures": bool(figures_in(run["response"])) and q["eval_type"] != "refusal",
                # v4 reports by source (StatCan, BoC, ...) and keeps the dev and test sets
                # apart; earlier versions by their own groups.
                "group": q["source"] if version == "v4" else q.get("group", "core"),
                "split": q.get("split"),
            }
        )
    return {
        "benchmark": f"maple_test_{version}",
        "answers": rows,
        "summary": summarise(rows),
        "retired_questions": retired,
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
        checkable = [
            i
            for i in with_figures
            if i["grade"]["citations"]["vectors"] or i["grade"]["citations"]["valet"]
        ]
        costs = [i["run"]["cost_usd"] for i in items if i["run"].get("cost_usd") is not None]
        tokens_in = [t for i in items if (t := tokens_read(i["run"])) is not None]
        tokens_out = [
            i["run"]["output_tokens"] for i in items if i["run"].get("output_tokens") is not None
        ]
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
                "referrals": sum(bool(i.get("referral")) for i in items),
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
                # Only StatCan vectors and Bank of Canada series can be checked. Answers on
                # other publishers (ECCC stations, World Bank codes) count as untraceable
                # above, so an arm that answers more of them scored lower (v2: MapleStats'
                # 48% was 0 of 63 beyond answers); this share leaves them out.
                "traceability_checked": _share(
                    sum(i["grade"]["citations"]["traceable"] for i in checkable),
                    len(checkable),
                ),
                "release_mentions": _share(sum(c["release_mentioned"] for c in cites), len(cites)),
                "tool_calls": round(mean(len(i["run"]["tool_calls"]) for i in items), 1),
                "seconds": round(mean(i["run"]["duration_s"] for i in items), 1),
                "cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
                "tokens_in": round(mean(tokens_in)) if tokens_in else None,
                "tokens_out": round(mean(tokens_out)) if tokens_out else None,
                "errors": sum(i["run"]["is_error"] for i in items),
                "groups": groups,
            }
        )
    return out


def tokens_read(run: dict[str, Any]) -> int | None:
    """Input tokens the model read for one answer, cached or not; None if not recorded.

    Runs before 2026-11-08 kept only `input_tokens`, which with prompt caching counts
    a few dozen tokens: without the cache counts there is no total to report.
    """
    cached = run.get("cache_read_tokens")
    if cached is None:
        return None
    return (run.get("input_tokens") or 0) + cached + (run.get("cache_creation_tokens") or 0)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def _thousands(value: float | None) -> str:
    return "–" if value is None else f"{value / 1000:.1f}k"


def cost_per_question(answers: list[dict[str, Any]], version: str = "v1") -> list[str]:
    """Markdown: mean cost (USD) and input tokens of each question's answers, by arm.

    `answers` are run records (an Answer as written to a run file), or graded rows
    holding one under "run".
    """
    runs = [a.get("run", a) for a in answers]
    arms = sorted({r["arm"] for r in runs})
    cells: dict[tuple[str, str], tuple[list[float], list[int]]] = {}
    for r in runs:
        costs, tokens = cells.setdefault((r["arm"], r["question_id"]), ([], []))
        if r.get("cost_usd") is not None:
            costs.append(r["cost_usd"])
        if (read := tokens_read(r)) is not None:
            tokens.append(read)
    lines = [
        "| Question | " + " | ".join(arms) + " |",
        "| :-- |" + " --: |" * len(arms),
    ]
    for q in load_key(version):
        row = []
        for arm in arms:
            costs, tokens = cells.get((arm, q["id"]), ([], []))
            cost = f"{mean(costs):.3f}" if costs else "–"
            row.append(cost + (f" ({_thousands(mean(tokens))})" if tokens else ""))
        lines.append(f"| {q['id']} | " + " | ".join(row) + " |")
    return lines


# MapleStats arms that ran code changed after the Nov. 3 runs, with these questions in view
# (README, "MapleStats after these runs"): in-sample, not comparable with the other arms.
IN_SAMPLE = (
    "maplestats-1105",
    "maplestats_after",
    "maplestats-cost",
    "maplestats-current",
    "maplestats-release",
)


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
        + "".join(f"{GROUP_LABELS.get(g, g.capitalize())} | " for g in group_names if split)
        + ("Worst–best | Consistency | " if repeated else "")
        + "Partial | Abstained | Hallucinated | False claims | Referrals |",
        "| :-- | --: | "
        + ("--: | " * len(group_names) if split else "")
        + ("--: | --: | " if repeated else "")
        + "--: | --: | --: | --: | --: |",
    ]
    for s in summary:
        extra = (
            f"{s['correct_worst']}–{s['correct_best']} | {_pct(s['consistency'])} | "
            if repeated
            else ""
        )
        halves = (
            "".join(
                # An arm asked only some groups (an "after" run on the analyst questions)
                # gets a dash, so its row keeps the table's columns.
                (
                    f"{s['groups'][g]['correct']:g} of {s['groups'][g]['questions']} | "
                    if g in s["groups"]
                    else "– | "
                )
                for g in group_names
            )
            if split
            else ""
        )
        lines.append(
            f"| {s['arm']} | {s['correct']:g} | {halves}{extra}{s['partial']:g} "
            f"| {s['abstained']:g} "
            f"| {s['hallucinated']:g} | {s['false_claims']} | {s.get('referrals', 0)} |"
        )
    marked = [s["arm"] for s in summary if s["arm"] in IN_SAMPLE]
    if version == "v3" and any(s["arm"] == "maplestats-postfix" for s in summary):
        lines += [
            "",
            (
                "Partly in-sample: `maplestats-postfix` ran server fixes chosen after seeing"
                " the first v3 runs' misses; MapleStats' comparable v3 score is"
                " `maplestats-brief` (README)."
            ),
        ]
    if marked:
        lines += [
            "",
            "In-sample, not comparable with the other arms: "
            + ", ".join(f"`{a}`" for a in marked)
            + ". These ran MapleStats code changed after the Nov. 3 runs with these questions in"
            " view; MapleStats' comparable score is `maplestats` (README).",
        ]
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
            "them (a stored value, or one scaled by the series' thousands or millions). "
            "**Checked:** the same share among answers that cite a StatCan vector or Bank of "
            "Canada series, the only IDs checked; other publishers' IDs are not, so answers on "
            "them count as untraceable in the first share. **Release:** answers that mention "
            "a release date."
        ),
        (
            "- **Cost** is per answer (headless Claude Code's `total_cost_usd`). **Tokens in** "
            "is the input the model read per answer, cached or not (runs before 2026-11-08 did "
            "not record the cached share, so they show a dash); **out** is what it wrote."
        ),
        "",
        (
            "| Arm | Table cov. | Vector cov. | IDs cited | Precision | Invented | Off-table "
            "| Traceable | Checked | Release | Tool calls | Seconds | Cost (USD) "
            "| Tokens in | Tokens out |"
        ),
        "| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for s in summary:
        cost = "–" if s["cost_usd"] is None else f"{s['cost_usd']:.3f}"
        lines.append(
            f"| {s['arm']} | {_pct(s['table_coverage'])} | {_pct(s['vector_coverage'])} "
            f"| {s['ids_cited']} | {_pct(s['citation_precision'])} | {s['invented_ids']} "
            f"| {s['off_table_vectors']} | {_pct(s['traceability'])} "
            f"| {_pct(s.get('traceability_checked'))} "
            f"| {_pct(s['release_mentions'])} | {s['tool_calls']} | {s['seconds']} | {cost} "
            f"| {_thousands(s.get('tokens_in'))} | {_thousands(s.get('tokens_out'))} |"
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
    lines += [
        "",
        "## Cost per question",
        "",
        "Mean USD per answer, with the input tokens read in brackets where the run recorded them.",
        "",
        *cost_per_question(report["answers"], version),
    ]
    claims = [r for r in report["answers"] if r["false_claim"]]
    if claims:
        lines += ["", "## False claims", ""]
        lines += [
            f"- {r['run']['arm']} {r['run']['question_id']}: {r['false_claim']}" for r in claims
        ]
    lines += review_direction(report)
    return "\n".join(lines) + "\n"


RANK = {"hallucinated": 0, "abstained": 1, "partial": 2, "correct": 3}


def review_direction(report: dict[str, Any]) -> list[str]:
    """Which way the hand review moved each arm: the check that it favoured no one."""
    moved: dict[str, dict[str, int]] = {}
    repeats: dict[str, set[int]] = {}
    for r in report["answers"]:
        g, arm = r["grade"], r["run"]["arm"]
        row = moved.setdefault(arm, {"up": 0, "down": 0, "gained": 0, "lost": 0, "n": 0})
        repeats.setdefault(arm, set()).add(r["run"].get("repeat", 0))
        row["n"] += 1
        before, after = g.get("auto_outcome") or g["outcome"], g["outcome"]
        if before == after:
            continue
        row["up" if RANK[after] > RANK[before] else "down"] += 1
        row["gained"] += after == "correct"
        row["lost"] += before == "correct"
    lines = [
        "",
        "## Direction of the hand review",
        "",
        (
            "Re-grades that changed the grader's outcome, by arm. A review that favoured one arm "
            "would raise it and lower the others; correct answers gained and lost are the ones "
            "that move the score."
        ),
        "",
        "| Arm | Answers | Raised | Lowered | Correct gained | Correct lost | Net correct per run |",
        "| :-- | --: | --: | --: | --: | --: | --: |",
    ]
    for arm, m in sorted(moved.items()):
        net = (m["gained"] - m["lost"]) / len(repeats[arm])
        lines.append(
            f"| {arm} | {m['n']} | {m['up']} | {m['down']} | {m['gained']} | {m['lost']} "
            f"| {net:+.1f} |"
        )
    return lines
