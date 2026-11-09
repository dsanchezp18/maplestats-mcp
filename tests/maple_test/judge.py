"""An LLM judge for Maple Test answers, so a person reads only the answers it flags.

The regex grader (`grade.py`) reads numbers and phrases; it misses correct answers worded
oddly (v3: "no 2024 file") and passes some wrong ones (a status named only among
possibilities). The judge reads the answer against the key with a rubric for the
question's kind of answer, and returns an outcome, a confidence, a false claim and whether
the answer is a referral. An answer goes to a person only when:

- the judge's outcome differs from the deterministic grade (JSON block, then regex); or
- the judge's confidence is below `LOW_CONFIDENCE`; or
- the judge failed (no verdict).

The judge never overrides a grade by itself: a person settles every flagged answer in
`overrides_v4.json`, as in v2 and v3. Unflagged answers keep the deterministic grade,
which the judge agreed with. `calibrate.py` measures how often that agreement is wrong,
against the v1 and v2 hand reviews.

The judge runs headless Claude Code (`claude -p`) with no tools and a JSON schema, as the
arms do, so it needs the same logged-in CLI (README, "Running it"). Verdicts are cached in
`v4/judge_cache.jsonl` by model, rubric version and answer text, so re-grading is free.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CACHE = HERE / "v4" / "judge_cache.jsonl"
MODEL = "claude-sonnet-5-5"
LOW_CONFIDENCE = 0.7
TIMEOUT_S = 180
# Bump when the rubric text changes: cached verdicts under an older rubric are not reused.
RUBRIC_VERSION = "2026-11-09.1"

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["correct", "partial", "abstained", "hallucinated"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "false_claim": {"type": "string"},
        "referral": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["outcome", "confidence", "false_claim", "referral", "reason"],
}

# The rules the v2 and v3 hand reviews applied to every arm (README, "How it was graded"
# and "The review"), written once for the judge.
GENERAL = """\
You grade one answer from the Maple Test, a benchmark of Canadian official data. You get \
the question, its answer key and the answer. Grade what the answer states, against the \
key, not whether you agree with the key. Outcomes:

- correct: every value the key requires, within its tolerance, for the period asked, and \
  the right call (comparison, refusal or flag).
- partial: the right call and at least half the values with every headline value, or the \
  problem flagged without the figure where the key requires one, or a wrong first answer \
  corrected in the same reply.
- abstained: declined, gave no figure or fact, or gave only an older period than the one \
  asked (labelled as older), or wrote tool calls that never ran, or hit a run error.
- hallucinated: states a value, date, code or fact that is wrong for what was asked, or \
  gives a figure for something the key says is not published, or does the misleading \
  calculation without flagging it.

Rules from the hand reviews:
- Numbers are checked against the key with its tolerance; rounding within the tolerance \
  is fine. Values the key lists under "reference" are context, not required.
- A status or a refusal named only among possibilities ("marketed, cancelled or dormant") \
  is not a call.
- An answer that offers the previous month or year, clearly labelled, in place of the one \
  asked is abstained, even if the number happens to be close.
- A figure recalled from memory and flagged as unverified is graded on its value.
- Saying a figure "could not be found" is not the same as saying it is not published: on \
  a refusal question only the latter is correct.
- A referral is an answer with no figure that says it cannot reach the publisher at all \
  and points to the publisher's page. A data copy that ends early, an empty lookup or a \
  tool error is not a referral.
- false_claim: a statement about the data that is verifiably false by the key (a figure \
  said to be published or not published when the opposite is true; a wrong unit, basis or \
  coverage presented as fact). Empty string if none.
- The answer may end with a JSON block; grade the answer as a whole, prose and block.

confidence: your probability that a careful human reviewer, applying these rules, gives \
the same outcome. Use below 0.7 when the key's tolerance, the period asked or the call \
is ambiguous for this answer."""

RUBRICS = {
    "figure": "Kind: figure. Every required value in the key, for the period asked.",
    "comparison": (
        "Kind: comparison. The right call (which one is higher, which status, which name) "
        "and the values. A right call with wrong values is hallucinated; right values with "
        "the wrong call are hallucinated."
    ),
    "flag": (
        "Kind: flag. The question invites a misleading calculation or a figure that does not "
        "exist as asked. Correct: states the problem and, where the key requires a figure "
        "(figure_required), gives the published one. Doing the calculation without the "
        "warning is hallucinated; doing it and warning after is partial."
    ),
    "documentation": (
        "Kind: documentation. Text answers (a definition, a licence, a code, a field type, a "
        "frequency). Every fact in the key is correct; at least half with every headline "
        "fact is partial; a fact the key shows is false, or a code of its own, is "
        "hallucinated. The key's `grading` notes, when present, are the reviewers' rule."
    ),
    "refusal": (
        "Kind: refusal. What is asked is not published or does not exist. Correct: says so "
        "(not published, not released yet, discontinued, cancelled, not held yet, no such "
        "file). A figure for it is hallucinated. Declining without saying it does not exist "
        "is abstained."
    ),
    "release": (
        "Kind: release date. The expected dates; a date written without the year counts. "
        "Another date given as the answer is hallucinated; other dates mentioned only for "
        "context are fine. Where the key names a table (table_pattern), it is required for "
        "correct."
    ),
}

# Key fields a grader needs; the rest (patterns, item statistics, split) would only
# distract it or tell it how the regex grader decides.
KEY_FIELDS = (
    "question",
    "expected",
    "reference",
    "headline",
    "tolerance",
    "tolerances",
    "alternatives",
    "traps",
    "grading",
    "figure_required",
    "facts",
    "wrong",
)


def qtype_of(question: dict[str, Any]) -> str:
    """v4 names the kind; v1 to v3 questions get it from their grading kind."""
    if "qtype" in question:
        return question["qtype"]
    return {
        "numeric": "figure",
        "comparison": "comparison",
        "flag": "flag",
        "facts": "documentation",
        "refusal": "refusal",
        "date": "release",
    }[question["eval_type"]]


def prompt(question: dict[str, Any], answer: str) -> str:
    key = {k: question[k] for k in KEY_FIELDS if k in question}
    return (
        f"{RUBRICS[qtype_of(question)]}\n\n"
        f"Answer key:\n```json\n{json.dumps(key, ensure_ascii=False, indent=1)}\n```\n\n"
        f"Answer to grade:\n<answer>\n{answer}\n</answer>"
    )


def _cache_key(model: str, question: dict[str, Any], answer: str) -> str:
    raw = f"{model}|{RUBRIC_VERSION}|{question['id']}|{answer}"
    return hashlib.sha256(raw.encode()).hexdigest()


class Cache:
    def __init__(self, path: Path = CACHE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.items: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.items[row["key"]] = row["verdict"]

    def get(self, key: str) -> dict[str, Any] | None:
        return self.items.get(key)

    def put(self, key: str, verdict: dict[str, Any]) -> None:
        with self.lock:
            self.items[key] = verdict
            self.path.parent.mkdir(exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({"key": key, "verdict": verdict}, ensure_ascii=False) + "\n")


def ask(question: dict[str, Any], answer: str, model: str = MODEL) -> dict[str, Any]:
    """One verdict from headless Claude Code; `error` set (and no outcome) when it fails."""
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--system-prompt",
        GENERAL,
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA),
    ]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        try:
            proc = subprocess.run(
                command,
                input=prompt(question, answer),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                cwd=empty,
                env=os.environ.copy(),
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"timed out after {TIMEOUT_S}s", "model": model}
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": (proc.stderr or proc.stdout or "no output")[:300], "model": model}
    verdict = result.get("structured_output")
    if result.get("is_error") or not isinstance(verdict, dict) or "outcome" not in verdict:
        return {"error": str(result.get("result") or "no verdict")[:300], "model": model}
    return {**verdict, "model": model, "cost_usd": result.get("total_cost_usd")}


def judge_many(
    items: Iterable[tuple[dict[str, Any], str]],
    model: str = MODEL,
    workers: int = 6,
    cache: Cache | None = None,
) -> list[dict[str, Any]]:
    """Verdicts for (question, answer) pairs, in order; cached ones are not asked again."""
    cache = cache or Cache()
    pairs = list(items)

    def one(pair: tuple[dict[str, Any], str]) -> dict[str, Any]:
        question, answer = pair
        key = _cache_key(model, question, answer)
        hit = cache.get(key)
        if hit is not None:
            return {**hit, "cached": True}
        verdict = ask(question, answer, model)
        if "error" not in verdict:
            cache.put(key, verdict)
        return verdict

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, pairs))


def needs_review(deterministic: str, verdict: dict[str, Any]) -> bool:
    """Flag for a person: the judge disagrees, is unsure, or failed."""
    if "outcome" not in verdict:
        return True
    return verdict["outcome"] != deterministic or verdict["confidence"] < LOW_CONFIDENCE
