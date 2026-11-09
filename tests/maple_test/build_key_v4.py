"""Build the Maple Test v4 key from the v1, v2 and v3 keys (README, "Version 4").

v4 asks no new questions. It keeps 47 of the 112 asked so far: one from each group of
near-duplicates, and only questions that separate servers in the item analysis
(`item_analysis.py`, `v4/item_analysis.json`): a question every comparable arm always got
right, or always got wrong, is dropped. Every one of the 112 is listed below, kept or
dropped with its reason, and `--check` fails if one is missing or listed twice.

Each kept question is copied unchanged from its source key (values, tolerances, patterns,
citations), so v4 grades exactly as its source did, plus:

- `source` and `qtype`, the two strata the selection balances: publisher (StatCan, Bank of
  Canada, CMHC, provincial, municipal, federal, international) and kind of answer (figure,
  comparison, flag, documentation, refusal, release date);
- `split`: `dev` (public, for tuning) or `test` (held out); see the rotation rule;
- `extra_passes`: true where the outcome changed between passes for at least 40% of
  the arms that answered it more than once; `run --adaptive` asks only these again;
- `in_sample_for`: servers whose code was changed with this question's answers in view.

The split is fixed by a hash, not by hand (`split_of`): within each source, questions are
ordered by a salted sha256 of their id and alternate test, dev, test, ..., with the first
salt that balances the kinds of answer, so neither set was chosen by looking at the
questions or the answers.

    uv run python -m tests.maple_test.build_key_v4           # writes maple_test_v4.json
    uv run python -m tests.maple_test.build_key_v4 --check   # fails if the file is stale

The source keys are rebuilt from the publishers by `build_key --check`,
`build_key_v2 --check`, `key_v2_release` and `build_key_v3 --check`; this script never
reads a publisher, so a revised source shows up here only after its own key is rebuilt.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from tests.maple_test import grade

HERE = Path(__file__).resolve().parent
KEY = HERE / "maple_test_v4.json"
ANALYSIS = HERE / "v4" / "item_analysis.json"
VOLATILE_AT = 0.4
KEEP_SOURCES = ("statcan", "boc", "cmhc", "provincial", "municipal", "federal", "international")
QTYPES = ("figure", "comparison", "flag", "documentation", "refusal", "release")

# id: (source, qtype, why it is kept). Sources: statcan, boc, cmhc, provincial, municipal,
# federal (federal publishers other than StatCan and the BoC, and open.canada.ca),
# international. qtypes: figure, comparison, flag, documentation, refusal, release.
KEEP: dict[str, tuple[str, str, str]] = {
    "M-04": ("statcan", "comparison", "population growth call; mcp_statcan and no_tools split"),
    "M-09": ("statcan", "figure", "customs vs balance-of-payments basis trap; replay fixture"),
    "M-15": ("statcan", "flag", "mixed census/LFS calculation; grader wrong on every answer"),
    "C-01": ("statcan", "comparison", "Ontario vs Quebec; volatile; replay fixture"),
    "C-05": ("statcan", "figure", "job vacancies; most volatile core figure"),
    "C-09": ("statcan", "comparison", "provincial CPI ranking"),
    "C-11": ("statcan", "figure", "annualized quarterly GDP, not the q/q rate"),
    "C-16": ("statcan", "figure", "building permits; volatile"),
    "X-23": ("statcan", "figure", "2021 Census renters share; volatile"),
    "X-24": ("statcan", "flag", "a 2026 census figure does not exist; most volatile flag"),
    "A-01": ("statcan", "figure", "child poverty: the annual income survey"),
    "A-02": ("statcan", "flag", "SEPH NAICS 912 vs the LFS; volatile"),
    "A-03": ("statcan", "figure", "average income with the median beside it; volatile"),
    "A-05": ("statcan", "refusal", "provincial disability poverty is not published"),
    "R-01": ("statcan", "release", "PTEA release date"),
    "R-03": ("statcan", "release", "release date and the table that moved"),
    "R-04": ("statcan", "release", "a monthly release date; volatile"),
    "R-06": ("statcan", "refusal", "no date set for the 2026 PTEA"),
    "T-02": ("statcan", "documentation", "mandatory surveys; volatile"),
    "T-06": ("statcan", "documentation", "CPI time base"),
    "T-30": ("statcan", "documentation", "vector to table and frequency (WDS)"),
    "T-31": ("statcan", "documentation", "seasonal adjustment of a vector (WDS)"),
    "M-11": ("boc", "figure", "USD/CAD on a date; replay fixture"),
    "C-10": ("boc", "figure", "CPI-common"),
    "C-19": ("boc", "figure", "the target rate after the Oct. 29 move; replay fixture"),
    "C-21": ("boc", "figure", "BCPI"),
    "T-12": ("boc", "refusal", "noon rates ended in 2017"),
    "C-24": ("cmhc", "flag", "housing starts times 12 (SAAR trap); CMHC's starts"),
    "T-15": ("cmhc", "documentation", "RMS reliability codes; outcome varied in every arm"),
    "T-14": ("cmhc", "documentation", "RMS timing and coverage; volatile"),
    "T-20": ("provincial", "documentation", "BC catalogue: licence, no CSV or DataStore"),
    "T-22": ("provincial", "documentation", "SAAQ property-damage threshold and its date"),
    "T-34": ("provincial", "documentation", "Ontario DataStore fields and types"),
    "T-36": ("provincial", "documentation", "Alberta: open data or publication"),
    "T-25": ("municipal", "documentation", "Toronto CKAN: owner, refresh, field type"),
    "T-28": ("municipal", "documentation", "Montréal DataStore: severity field, a field type"),
    "X-01": ("federal", "figure", "ECCC monthly climate"),
    "X-15": ("federal", "comparison", "drug status call; grader wrong on most answers"),
    "X-16": ("federal", "refusal", "cancelled drug; grader wrong on most answers"),
    "X-17": ("federal", "figure", "Express Entry round"),
    "X-20": ("federal", "refusal", "an Express Entry round not yet held"),
    "T-17": ("federal", "documentation", "open.canada.ca metadata; grader wrong on most"),
    "T-19": ("federal", "documentation", "open.canada.ca licence and dates; volatile"),
    "X-05": ("international", "figure", "World Bank GDP per capita"),
    "X-08": ("international", "refusal", "a 2025 World Bank value not published"),
    "X-10": ("international", "figure", "BIS property prices"),
    "X-12": ("international", "comparison", "BIS debt service, Canada vs US"),
}

# Ceiling: every comparable arm always right. Floor: always wrong. dup: a near-duplicate
# of the kept question named. budget: separates servers, dropped to keep the set short
# (another question tests the same skill on the same source).
DROP: dict[str, str] = {
    "M-01": "ceiling; dup of C-01 (LFS rates)",
    "M-02": "ceiling",
    "M-03": "ceiling",
    "M-05": "ceiling",
    "M-06": "ceiling; dup of C-09 (CPI)",
    "M-07": "ceiling; dup of C-10 (core CPI)",
    "M-08": "ceiling; dup of C-11 (GDP)",
    "M-10": "budget: wages are A-02",
    "M-12": "ceiling",
    "M-13": "ceiling; dup of A-05/T-04 (StatCan refusals)",
    "M-14": "ceiling",
    "C-02": "budget: dup of C-01 (LFS rates)",
    "C-03": "budget: dup of C-01 (LFS)",
    "C-04": "budget: dup of A-02 (wages)",
    "C-06": "budget: dup of C-09 (CPI); keeps a replay fixture in v2",
    "C-07": "budget: dup of C-09 (CPI)",
    "C-08": "budget: dup of C-09 (CPI)",
    "C-12": "budget: dup of C-16 (monthly level and change)",
    "C-13": "budget: dup of C-16 (monthly level and change)",
    "C-14": "budget: StatCan revised the key value after the runs; grader wrong on 77%",
    "C-15": "budget: dup of C-24 (housing starts)",
    "C-17": "ceiling",
    "C-18": "budget: near ceiling (spread 0.67, mean 0.94)",
    "C-20": "budget: dup of M-11/C-19 (BoC daily series)",
    "C-22": "ceiling",
    "C-23": "near ceiling (one arm missed once); dup of A-05/T-04",
    "X-02": "budget: dup of X-01 (ECCC climate)",
    "X-03": "budget: dup of X-01 (ECCC station data)",
    "X-04": "floor",
    "X-06": "budget: dup of X-05 (World Bank)",
    "X-07": "budget: dup of X-05 (World Bank)",
    "X-09": "budget: dup of C-19 (policy rate)",
    "X-11": "budget: dup of X-12 (BIS debt service)",
    "X-13": "budget: dup of X-15 (DIN lookup)",
    "X-14": "budget: dup of X-15 (DIN lookup)",
    "X-18": "budget: dup of X-17 (Express Entry)",
    "X-19": "budget: dup of X-17 (Express Entry)",
    "X-21": "budget: dup of X-23 (2021 Census)",
    "X-22": "budget: dup of A-03 (incomes)",
    "A-04": "near floor (one arm right once in three)",
    "R-02": "budget: dup of R-01 (PTEA and SUT dates)",
    "R-05": "budget: dup of R-04 (monthly release date)",
    "R-07": "budget: dup of R-04 (monthly release date)",
    "R-08": "budget: dup of R-04 (monthly release date)",
    "T-01": "ceiling",
    "T-03": "floor",
    "T-05": "floor",
    "T-07": "floor",
    "T-08": "ceiling",
    "T-09": "ceiling",
    "T-10": "ceiling",
    "T-11": "ceiling",
    "T-13": "ceiling",
    "T-04": "ceiling (v3 hand review)",
    "T-18": "floor among comparable arms",
    "T-21": "budget: dup of T-34 (baby names datasets)",
    "T-16": "ceiling (v3 hand review)",
    "T-23": "ceiling (v3 hand review)",
    "T-24": "ceiling",
    "T-26": "ceiling",
    "T-27": "ceiling",
    "T-29": "budget: dup of T-30 (WDS series metadata)",
    "T-32": "budget: dup of T-30 (WDS metadata); its key changes when the table is updated",
    "T-33": "budget: dup of T-34 (Ontario baby names)",
    "T-35": "budget: dup of T-36 (Alberta catalogue)",
}

# MapleStats was changed with v1 and v2 answers in view (README, "MapleStats after these
# runs"), the release history after R-06, and `maplestats-postfix` after v3's runs, so
# every question here is in-sample for MapleStats at launch. Other servers' maintainers
# may have read the published answers too; nothing records it.
IN_SAMPLE_FOR = ["maplestats"]

# The split's salt, found by first_balanced_salt() when the key was first built
# (2026-11-09). Never change it: that would reshuffle dev and test.
SALT = 2
# Test questions moved to dev under rotation rule 3: id -> the change they motivated.
MOVED_TO_DEV: dict[str, str] = {}

PROMPT_NOTE = (
    "v4 asks every question with one prompt (`run.PROMPTS['v4']`) that covers figures and "
    "documentation and asks for a closing JSON block (README, 'Structured answers')."
)


def _order(qid: str, salt: int) -> str:
    return hashlib.sha256(f"maple-v4:{salt}:{qid}".encode()).hexdigest()


def _alternate(salt: int) -> dict[str, str]:
    out: dict[str, str] = {}
    by_source: dict[str, list[str]] = {}
    for qid, (source, _, _) in KEEP.items():
        by_source.setdefault(source, []).append(qid)
    for ids in by_source.values():
        for i, qid in enumerate(sorted(ids, key=lambda q: _order(q, salt))):
            out[qid] = "test" if i % 2 == 0 else "dev"
    return out


def _balanced(split: dict[str, str]) -> bool:
    """Every kind of answer in both sets, and no kind more than two apart between them."""
    for qtype in QTYPES:
        ids = [q for q, (_, t, _) in KEEP.items() if t == qtype]
        test = sum(split[q] == "test" for q in ids)
        if not 0 < test < len(ids) or abs(2 * test - len(ids)) > 2:
            return False
    return True


def first_balanced_salt() -> int:
    """The first salt from 0 up whose split puts every kind of answer in both sets."""
    for salt in range(10_000):
        if _balanced(_alternate(salt)):
            return salt
    raise SystemExit("no balanced split; add questions to the thin strata")


def split_of() -> dict[str, str]:
    """dev or test for each kept question.

    Within each source, questions are ordered by sha256 of `maple-v4:<SALT>:<id>` and
    alternate test, dev, test, ...; SALT was the first salt whose split puts every kind of
    answer in both sets, no kind more than two apart (`first_balanced_salt`). It is fixed,
    so the split never reshuffles: a test question that motivated a change moves to dev
    through MOVED_TO_DEV (rotation rule 3, README), and nothing else moves with it.
    """
    split = _alternate(SALT)
    split.update({qid: "dev" for qid in MOVED_TO_DEV})
    return split


def build() -> dict[str, Any]:
    sources = {
        q["id"]: (version, q) for version in ("v1", "v2", "v3") for q in grade.load_key(version)
    }
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))["questions"]
    splits = split_of()
    questions = []
    for qid, (source, qtype, why) in KEEP.items():
        version, original = sources[qid]
        stats = analysis[qid]
        q = copy.deepcopy(original)
        # Kept as the source key has it; `group` stays the source version's own group.
        q.update(
            {
                "source_version": version,
                "source": source,
                "qtype": qtype,
                "split": splits[qid],
                "extra_passes": (stats["volatile"] or 0) >= VOLATILE_AT,
                "in_sample_for": IN_SAMPLE_FOR,
                "why_kept": why,
                "item": {
                    k: stats[k] for k in ("arms", "mean", "spread", "volatile", "ceiling", "floor")
                },
            }
        )
        questions.append(q)
    order = {s: i for i, s in enumerate(KEEP_SOURCES)}
    questions.sort(key=lambda q: (q["split"], order[q["source"]], q["id"]))
    return {
        "benchmark": "maple_test_v4",
        "built_from": {
            v: json.loads(grade.SUITES[v].key.read_text(encoding="utf-8"))["built_at"]
            for v in ("v1", "v2", "v3")
        },
        "note": PROMPT_NOTE,
        "dropped": DROP,
        "questions": questions,
    }


def problems(key: dict[str, Any]) -> list[str]:
    """What is wrong with a built key: coverage, balance and the accounting of all 112."""
    found = []
    every = {q["id"] for v in ("v1", "v2", "v3") for q in grade.load_key(v)}
    both = set(KEEP) & set(DROP)
    if both:
        found.append(f"kept and dropped: {sorted(both)}")
    missing = every - set(KEEP) - set(DROP)
    if missing:
        found.append(f"not accounted for: {sorted(missing)}")
    unknown = (set(KEEP) | set(DROP)) - every
    if unknown:
        found.append(f"not in any source key: {sorted(unknown)}")
    qs = key["questions"]
    if not 40 <= len(qs) <= 50:
        found.append(f"{len(qs)} questions; v4 keeps 40 to 50")
    for split in ("dev", "test"):
        part = [q for q in qs if q["split"] == split]
        for s in KEEP_SOURCES:
            if not any(q["source"] == s for q in part):
                found.append(f"no {s} question in {split}")
        for t in QTYPES:
            if not any(q["qtype"] == t for q in part):
                found.append(f"no {t} question in {split}")
    for q in qs:
        if q["source"] not in KEEP_SOURCES or q["qtype"] not in QTYPES:
            found.append(f"{q['id']}: unknown source or qtype")
        if q["item"]["ceiling"] or q["item"]["floor"]:
            found.append(f"{q['id']}: every comparable arm always right, or always wrong")
    return found


def strata_table(key: dict[str, Any]) -> str:
    qs = key["questions"]
    counts = Counter((q["source"], q["split"]) for q in qs)
    kinds = Counter((q["qtype"], q["split"]) for q in qs)
    lines = ["| Source | Dev | Test |", "| :-- | --: | --: |"]
    lines += [f"| {s} | {counts[(s, 'dev')]} | {counts[(s, 'test')]} |" for s in KEEP_SOURCES]
    lines += ["", "| Kind | Dev | Test |", "| :-- | --: | --: |"]
    lines += [f"| {t} | {kinds[(t, 'dev')]} | {kinds[(t, 'test')]} |" for t in QTYPES]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.maple_test.build_key_v4")
    parser.add_argument("--check", action="store_true", help="fail if maple_test_v4.json is stale")
    parser.add_argument("--table", action="store_true", help="print the strata table")
    args = parser.parse_args()
    key = build()
    issues = problems(key)
    for issue in issues:
        print(f"problem: {issue}", file=sys.stderr)
    text = json.dumps(key, indent=1, ensure_ascii=False) + "\n"
    if args.table:
        print(strata_table(key))
    if args.check:
        current = KEY.read_text(encoding="utf-8") if KEY.exists() else ""
        if current != text:
            print("maple_test_v4.json is stale: run build_key_v4", file=sys.stderr)
            return 1
        return 1 if issues else 0
    if issues:
        return 1
    KEY.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {KEY.name}: {len(key['questions'])} questions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
