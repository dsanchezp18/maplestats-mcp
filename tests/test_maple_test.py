"""Offline checks of the Maple Test: the answer key's shape and the grader's calls.

No network: the key is the committed JSON. `python -m tests.maple_test.build_key --check`
compares it with the live sources.
"""

from __future__ import annotations

import re

import pytest

from tests.maple_test.grade import grade_answer, load_key, numbers_in

QUESTIONS = {q["id"]: q for q in load_key()}


def test_fifteen_questions_of_every_kind():
    assert sorted(QUESTIONS) == [f"M-{i:02d}" for i in range(1, 16)]
    kinds = {q["eval_type"] for q in QUESTIONS.values()}
    assert kinds == {"numeric", "comparison", "refusal", "flag"}


@pytest.mark.parametrize("qid", sorted(QUESTIONS))
def test_every_question_is_cited_and_explained(qid):
    q = QUESTIONS[qid]
    assert "?" in q["question"] and q["traps"] and q["citations"]
    for c in q["citations"]:
        assert c["table_id"] == "Valet" or re.fullmatch(r"\d{2}-10-\d{4}-01", c["table_id"])
        assert c["url"].startswith("https://")
    assert set(q.get("headline", [])) <= set(q["expected"])


def test_numbers_drop_identifiers_and_read_scales():
    text = "Table 14-10-0287-01, v2062815: 6.5% and 41.8 million people, $1,354.55."
    found = numbers_in(text)
    assert 6.5 in found and 41_800_000 in found and 1354.55 in found
    assert 2062815 not in found and 14100287 not in found


def test_a_correct_answer_is_correct():
    q = QUESTIONS["M-01"]
    e = q["expected"]
    text = (
        f"Canada's unemployment rate was {e['rate_sep_2026_pct']}% in September 2026, "
        f"against {e['rate_sep_2025_pct']}% a year earlier, a change of "
        f"{e['change_pp']} percentage points (14-10-0287-01, v2062815)."
    )
    g = grade_answer(q, text)
    assert g.outcome == "correct" and g.table_coverage == 1.0 and g.vector_coverage == 1.0


def test_a_wrong_figure_is_hallucinated():
    g = grade_answer(QUESTIONS["M-01"], "It was 5.2% in September 2026, from 5.9%.")
    assert g.outcome == "hallucinated"


def test_comparison_needs_the_right_winner():
    q = QUESTIONS["M-04"]
    e = q["expected"]
    loser = "Ontario" if e["answer"] == "Alberta" else "Alberta"
    right = (
        f"{e['answer']} grew faster: {e['alberta_growth_pct']}% for Alberta and "
        f"{e['ontario_growth_pct']}% for Ontario."
    )
    wrong = (
        f"{loser} grew faster: {e['alberta_growth_pct']}% for Alberta and "
        f"{e['ontario_growth_pct']}% for Ontario."
    )
    assert grade_answer(q, right).outcome == "correct"
    assert grade_answer(q, wrong).outcome == "hallucinated"


def test_refusals():
    q13, q14 = QUESTIONS["M-13"], QUESTIONS["M-14"]
    assert grade_answer(q13, "Q4 2026 GDP has not been published yet.").outcome == "correct"
    assert grade_answer(q13, "Real GDP grew 0.4% in Q4 2026.").outcome == "hallucinated"
    assert (
        grade_answer(
            q14, "November 1, 2026 was a Sunday, so no rate was published; Oct 30 was 1.3960."
        ).outcome
        == "correct"
    )
    assert grade_answer(q14, "The rate on November 1, 2026 was 1.3960.").outcome == "hallucinated"


def test_flag_question():
    q = QUESTIONS["M-15"]
    count = q["expected"]["unemployed_sep_2026_thousands"]
    assert (
        grade_answer(
            q, "That mixes a 2021 Census count with a 2026 rate, which is not comparable."
        ).outcome
        == "correct"
    )
    assert grade_answer(q, f"The LFS counts {count:,} thousand unemployed.").outcome == "correct"
    assert (
        grade_answer(q, "20.1 million times 6.5% is about 1.3 million.").outcome == "hallucinated"
    )


def test_a_flat_month_can_be_said_in_words():
    q = QUESTIONS["M-08"]
    if abs(q["expected"]["change_pct"]) >= 0.05:
        pytest.skip("August 2026 GDP was not flat in this key")
    e = q["expected"]
    text = f"Real GDP was essentially unchanged in August, at {e['gdp_aug_2026']:,.0f} million."
    assert grade_answer(q, text).outcome in {"correct", "partial"}


def test_short_vector_ids_are_read():
    from tests.maple_test.grade import VECTOR

    assert VECTOR.findall("Canada is v1 and Alberta v15; LFS v2062815.") == [
        "v1",
        "v15",
        "v2062815",
    ]


def test_citation_checks_use_the_cache(tmp_path):
    from tests.maple_test.citations import Cache

    cache = Cache(tmp_path / "checks.json")
    cache.data = {
        "vector:2062815": {"exists": True, "product_id": 14100287, "values": [6.5, 7.1]},
        "vector:999": {"exists": False},
        "vector:41690973": {"exists": True, "product_id": 18100004, "values": [170.0]},
        "table:14100287": {"exists": True},
        "valet:FXUSDCAD": {"exists": True, "values": [1.396]},
    }
    text = (
        "6.5% (table 14-10-0287-01, vector v2062815); also v999 and v41690973; "
        "USD/CAD 1.3960 (FXUSDCAD). Released 2026-10-09."
    )
    check = cache.check(text, [6.5, 1.396])
    assert check.vectors_supporting == [2062815]
    assert check.vectors_invented == [999]
    assert check.vectors_off_table == [41690973]  # not in the one table cited
    assert check.valet_supporting == ["FXUSDCAD"]
    assert check.traceable and check.release_mentioned
