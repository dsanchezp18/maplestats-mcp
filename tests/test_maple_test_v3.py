"""Offline checks of the Maple Test v3 key (technical data and documentation questions).

No network: the key is the committed JSON. `python -m tests.maple_test.build_key_v3
--check` compares it with the publishers.
"""

from __future__ import annotations

import re

import pytest

from tests.maple_test.grade import SUITES, grade_answer, grade_runs, load_key, render
from tests.maple_test.run import PROMPTS

V3 = {q["id"]: q for q in load_key("v3")}
CKAN = ("federal", "provincial", "municipal")


def test_v3_is_registered_for_run_and_grade():
    suite = SUITES["v3"]
    assert suite.key.name == "maple_test_v3.json" and suite.runs.name == "runs_v3"
    assert "{today}" in PROMPTS["v3"] and "open-data portals" in PROMPTS["v3"]


def test_ids_and_spread_across_sources():
    assert sorted(V3) == [f"T-{i:02d}" for i in range(1, len(V3) + 1)]
    assert 24 <= len(V3) <= 40
    groups = [q["group"] for q in V3.values()]
    assert set(groups) == {"statcan", "boc", "cmhc", *CKAN}
    # About a third StatCan, at least a third CKAN portals, a few BoC and CMHC.
    assert groups.count("statcan") * 3 >= len(V3) - 1
    assert sum(g in CKAN for g in groups) * 3 >= len(V3)
    assert all(groups.count(g) >= 2 for g in ("boc", "cmhc", *CKAN))
    # Some questions have no answer to give (not published, discontinued).
    assert sum(q["eval_type"] == "refusal" for q in V3.values()) >= 3


@pytest.mark.parametrize("qid", sorted(V3))
def test_every_question_has_a_rule_a_source_and_a_trap(qid):
    q = V3[qid]
    assert q["question"].rstrip().endswith("?"), qid
    assert q["eval_type"] in ("facts", "refusal"), qid
    assert q["citations"] and q["traps"] and q["tolerance"], qid
    assert set(q["grading"]) == {"correct", "partial", "referral"}, qid
    for c in q["citations"]:
        assert c["table_id"] in ("Other", "Valet") and c["url"].startswith("https://"), qid
    if q["eval_type"] == "facts":
        assert q["facts"] and set(q["headline"]) <= set(q["facts"]), qid
        for pattern in [*q["facts"].values(), *q.get("wrong", [])]:
            re.compile(pattern)
    else:
        assert q["expected"]["behaviour"] and re.compile(q["absent_pattern"]), qid


@pytest.mark.parametrize(
    ("qid", "text", "outcome"),
    [
        # Facts: every fact correct, the headline alone partial, a known falsehood wrong.
        (
            "T-02",
            (
                "The Labour Force Survey is mandatory under the Statistics Act; the Canadian "
                "Income Survey is voluntary."
            ),
            "correct",
        ),
        ("T-02", "The LFS is mandatory and the CIS is also mandatory.", "hallucinated"),
        ("T-08", "Software publishers are NAICS 51321 (formerly 51121 in NAICS 2017).", "correct"),
        ("T-08", "NAICS 2022 code 51321.", "partial"),
        ("T-08", "It is 511210.", "hallucinated"),
        (
            "T-17",
            (
                "IRCC publishes it monthly as XLSX and CSV files; none of them is in the "
                "DataStore, so datastore_search cannot query them."
            ),
            "correct",
        ),
        (
            "T-25",
            (
                "Owned by the Toronto Transit Commission, refreshed monthly; Min Delay is "
                "a text field."
            ),
            "correct",
        ),
        ("T-25", "TTC; 'Min Delay' is numeric.", "hallucinated"),
        ("T-26", "MUSAN means 'Unsanitary vehicle'.", "correct"),
        ("T-26", "I can't find that code in my tools.", "abstained"),
        ("T-28", "Severity is in GRAVITE; NB_MORTS is numeric.", "correct"),
        # Added later (T-29 to T-36): WDS metadata, Ontario and Alberta catalogues.
        (
            "T-29",
            "Persons, in thousands: seasonally adjusted employment in Canada, 15 and over.",
            "correct",
        ),
        (
            "T-30",
            "Table 36-10-0104-01, quarterly: real GDP at market prices in chained 2017 dollars.",
            "correct",
        ),
        (
            "T-31",
            "No, it is not seasonally adjusted: the all-items CPI for Canada (18-10-0004-01).",
            "correct",
        ),
        (
            "T-32",
            (
                "Released on September 23, 2026; the table is updated annually and its latest "
                "reference date is July 1, 2026."
            ),
            "correct",
        ),
        (
            "T-34",
            (
                "Year/Année and Frequency/Fréquence are numeric, Name/Nom is text; names given "
                "fewer than five times are suppressed."
            ),
            "correct",
        ),
        (
            "T-35",
            (
                "Treasury Board and Finance publishes it annually as an XLSX file; its totals "
                "do not match the Financial Statement and Annual Report."
            ),
            "partial",
        ),
        (
            "T-36",
            "It is a publication: quarterly PDF reports from Agriculture and Irrigation.",
            "correct",
        ),
        # Refusals: say it does not exist; a figure for it is invented.
        ("T-04", "None: the unadjusted CPI is never revised.", "correct"),
        ("T-04", "It was revised up by 0.1 point to 165.3.", "hallucinated"),
        (
            "T-12",
            (
                "The Bank of Canada discontinued its noon rates in April 2017; the daily average "
                "for October 30, 2026 was 1.3960."
            ),
            "correct",
        ),
        ("T-12", "The noon rate was 1.3960.", "hallucinated"),
        (
            "T-16",
            "CMHC runs the Rental Market Survey only in October, so there is no April 2026 rate.",
            "correct",
        ),
        ("T-23", "No: the latest year in the dataset is 2022.", "correct"),
        ("T-23", "Yes, the 2024 file lists 98,412 accidents.", "hallucinated"),
    ],
)
def test_v3_grader(qid, text, outcome):
    assert grade_answer(V3[qid], text).outcome == outcome


def test_v3_report_names_each_source(tmp_path):
    run = tmp_path / "run.jsonl"
    base = {
        "arm": "demo",
        "model_ids": ["m"],
        "started_at": "2026-11-08T00:00:00+00:00",
        "tool_calls": [],
        "duration_s": 1.0,
        "is_error": False,
        "repeat": 0,
    }
    lines = [
        {**base, "question_id": "T-26", "response": "MUSAN: unsanitary vehicle."},
        {**base, "question_id": "T-10", "response": "No idea."},
    ]
    import json

    run.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    report = grade_runs([run], "v3")
    groups = report["summary"][0]["groups"]
    assert groups["municipal"] == {"questions": 1, "correct": 1}
    assert groups["boc"] == {"questions": 1, "correct": 0}
    assert "| BoC | Municipal |" in render(report, "v3")
