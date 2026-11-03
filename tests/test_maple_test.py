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


def test_v2_key_is_half_core_half_beyond():
    v2 = load_key("v2")
    assert len(v2) == 53 and len({q["id"] for q in v2}) == 53
    assert sum(q["group"] == "core" for q in v2) == 24
    assert sum(q["group"] == "beyond" for q in v2) == 24
    # Added after the first runs: four analyst questions, graded as their own group.
    assert [q["id"] for q in v2 if q["group"] == "analyst"] == [f"A-0{i}" for i in range(1, 6)]
    for q in v2:
        assert "?" in q["question"] or q["eval_type"] == "flag", q["id"]
        assert q["citations"] and q["traps"], q["id"]
        numeric = {
            k
            for k, v in q["expected"].items()
            if isinstance(v, int | float) and not isinstance(v, bool)
        }
        if q["group"] == "beyond":
            assert numeric <= set(q["tolerances"]), q["id"]


def test_name_answers_and_own_refusal_wording():
    v2 = {q["source_id"]: q for q in load_key("v2") if q.get("source_id")}
    brand = v2["B-01"]
    right = f"DIN 02524031 is {brand['answer_pattern']}, 150 mg and 100 mg."
    assert grade_answer(brand, right).outcome == "correct"
    assert grade_answer(brand, "DIN 02524031 is Lagevrio, 150 mg and 100 mg.").outcome != "correct"
    cancelled = v2["B-04"]
    said = "No one: Zantac 75 mg was cancelled after it left the market in 2022."
    assert grade_answer(cancelled, said).outcome == "correct"
    assert grade_answer(v2["B-08"], "Round #460 has not been held yet.").outcome == "correct"


@pytest.mark.parametrize(
    ("qid", "text", "outcome"),
    [
        # Written out in full: -68.3 thousand jobs as "68,300 jobs".
        ("C-03", "Canada lost about 68,300 jobs; employment was 21,104.8 thousand.", "correct"),
        ("C-03", "Canada gained 12,000 jobs; employment was 21,104.8 thousand.", "hallucinated"),
        # Refusals worded in ways v2 runs used.
        (
            "C-23",
            "Q3 2026 real GDP growth isn't available yet, so I can't give you one.",
            "correct",
        ),
        ("C-22", "Statistics Canada hasn't published October yet. September was 2.4%.", "correct"),
        ("X-08", "The World Bank has no 2025 value for Canada. 2024 was 82.11.", "correct"),
        ("C-23", "Real GDP grew 0.6% in the third quarter of 2026.", "hallucinated"),
    ],
)
def test_v2_grader_reads_written_out_units_and_refusals(qid, text, outcome):
    questions = {q["id"]: q for q in load_key("v2")}
    assert grade_answer(questions[qid], text).outcome == outcome


@pytest.mark.parametrize(
    ("qid", "text", "outcome"),
    [
        (
            "A-02",
            (
                "Provincial public administration (NAICS 912) earned $1,883.03 a week "
                "(SEPH, table 14-10-0203-01)."
            ),
            "correct",
        ),
        ("A-02", "Public administration workers earned $1,500 a week (LFS).", "hallucinated"),
        ("A-03", "The average was $66,100 and the median $48,100.", "correct"),
        ("A-03", "The average income was $66,100.", "partial"),
        ("A-03", "The median income was $48,100.", "partial"),
        (
            "A-04",
            (
                "The Census median household income was $96,000 (2020); the CIS median "
                "for economic families and persons not in one was $96,600 (2024)."
            ),
            "correct",
        ),
        # The Census household median answers the question as asked (v2 review); the
        # income survey's median alone, with its unit named, is partial.
        ("A-04", "The median household income was $96,000 in 2020 (Census).", "correct"),
        (
            "A-05",
            (
                "Statistics Canada publishes this rate only for Canada as a whole: 17.8% "
                "in 2024. There is no Alberta figure."
            ),
            "correct",
        ),
        (
            "A-05",
            "In Alberta, 17.8% of people with disabilities lived in poverty in 2024.",
            "hallucinated",
        ),
        ("A-04", "The CIS median for economic families was $96,600 (2024).", "partial"),
    ],
)
def test_v2_analyst_questions_grade_the_trap(qid, text, outcome):
    questions = {q["id"]: q for q in load_key("v2")}
    assert grade_answer(questions[qid], text).outcome == outcome


V2 = {q["id"]: q for q in load_key("v2")}


def test_separate_numbers_are_not_joined():
    # "July 1, 2026, 399,133" once read as one number, so correct answers failed.
    found = numbers_in("On July 1, 2026, 399,133 people; July 1, 2025, 539,960.")
    assert found == [1.0, 2026.0, 399133.0, 1.0, 2025.0, 539960.0]
    text = "On July 1, 2026, 399,133 people held only a study permit; on July 1, 2025, 539,960."
    assert grade_answer(V2["C-18"], text).outcome == "correct"


@pytest.mark.parametrize(
    ("qid", "text", "outcome"),
    [
        # Values the question did not ask for are reference only.
        ("C-03", "Canada lost about 68,300 jobs in September 2026.", "correct"),
        ("C-11", "Real GDP grew at an annualized rate of about 3.3% in Q2 2026.", "correct"),
        ("C-12", "Retail sales rose 1.2% in August 2026 from July.", "correct"),
        ("X-24", "No 2026 Census counts yet. The 2021 Census counted 1,418,118.", "correct"),
    ],
)
def test_v2_unasked_values_are_not_required(qid, text, outcome):
    assert grade_answer(V2[qid], text).outcome == outcome


@pytest.mark.parametrize(
    ("qid", "text", "outcome"),
    [
        # A flag question that asks for a figure is correct only with the figure.
        (
            "X-04",
            (
                "Station 6158733 stopped reporting in 2013. The successor, Toronto Intl A "
                "(6158731), recorded 215.4 mm in July 2024."
            ),
            "correct",
        ),
        ("X-04", "Station 6158733 closed in June 2013, so it has no July 2024 value.", "partial"),
        # A dropped tool connection is not the station's closure.
        (
            "X-04",
            "The data tools failed (connection closed, then timed out), so I can't give it.",
            "abstained",
        ),
        (
            "C-24",
            "Don't multiply by 12: the figure is already a seasonally adjusted annual rate.",
            "partial",
        ),
        (
            "C-24",
            (
                "Don't multiply by 12: September's 248,896 is already a seasonally adjusted "
                "annual rate."
            ),
            "correct",
        ),
        ("X-24", "The 2026 Census counts are not published yet.", "partial"),
        # A-02: naming SEPH is no answer without its NAICS 912 figure.
        ("A-02", "SEPH (14-10-0203) has this, but I couldn't retrieve it.", "abstained"),
        (
            "A-02",
            (
                "SEPH average weekly earnings, provincial public administration, Alberta: "
                "$1,883.03 in August 2026."
            ),
            "correct",
        ),
        ("A-02", "SEPH puts the 2025 annual average at $1,702.65 a week.", "correct"),
        (
            "A-02",
            "SEPH (14-10-0203): all of public administration in Alberta, $1,651.53 a week.",
            "abstained",
        ),
    ],
)
def test_v2_flag_questions_need_the_figure(qid, text, outcome):
    assert grade_answer(V2[qid], text).outcome == outcome


@pytest.mark.parametrize(
    ("text", "outcome"),
    [
        ("Canada was higher: 14% against 8% for the United States (BIS).", "correct"),
        # The question does not name the BIS: each country's own series, with the right call.
        (
            (
                "Canada was higher: 14.68% (Statistics Canada) against 11.32% for the United "
                "States (Federal Reserve)."
            ),
            "correct",
        ),
        ("The United States was higher: 14.68% against 11.32%.", "hallucinated"),
    ],
)
def test_x12_accepts_each_countrys_own_series(text, outcome):
    assert grade_answer(V2["X-12"], text).outcome == outcome
