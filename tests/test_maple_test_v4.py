"""Offline checks of the Maple Test v4 key, its JSON-block grading and the review triage.

No network and no model: the key is the committed JSON, built from the v1 to v3 keys by
`build_key_v4` (which `--check` also runs).
"""

from __future__ import annotations

import json

import pytest

from tests.maple_test import build_key_v4, judge, run
from tests.maple_test.grade import SUITES, grade_answer, grade_v4, load_key, structured_block

V4 = {q["id"]: q for q in load_key("v4")}
# A refusal phrased in the source's own words; T-23 left v4 as a ceiling but grades the same.
T23 = {q["id"]: q for q in load_key("v3")}["T-23"]


def block(**fields: object) -> str:
    return "The answer.\n\n```json\n" + json.dumps(fields) + "\n```"


def test_the_committed_key_is_what_the_builder_makes():
    key = build_key_v4.build()
    assert build_key_v4.problems(key) == []
    text = json.dumps(key, indent=1, ensure_ascii=False) + "\n"
    assert SUITES["v4"].key.read_text(encoding="utf-8") == text


def test_every_earlier_question_is_kept_or_dropped_with_a_reason():
    every = {q["id"] for v in ("v1", "v2", "v3") for q in load_key(v)}
    assert set(build_key_v4.KEEP) | set(build_key_v4.DROP) == every
    assert not set(build_key_v4.KEEP) & set(build_key_v4.DROP)
    assert all(reason.strip() for reason in build_key_v4.DROP.values())


def test_kept_questions_are_copied_unchanged():
    sources = {q["id"]: q for v in ("v1", "v2", "v3") for q in load_key(v)}
    fresh = json.loads(build_key_v4.FRESH_KEY.read_text(encoding="utf-8"))["questions"]
    sources |= {q["id"]: q for q in fresh}
    added = {
        "source_version",
        "source",
        "qtype",
        "split",
        "extra_passes",
        "in_sample_for",
        "why_kept",
        "item",
    }
    for qid, q in V4.items():
        assert {k: v for k, v in q.items() if k not in added} == sources[qid]


def test_dev_and_test_cover_every_source_and_kind():
    dev = [q for q in V4.values() if q["split"] == "dev"]
    assert {q["source"] for q in dev} == set(build_key_v4.KEEP_SOURCES)
    assert {q["qtype"] for q in dev} == set(build_key_v4.QTYPES)
    # Test may lack a stratum only while a replacement for a moved question is due.
    test = [q for q in V4.values() if q["split"] == "test"]
    due = build_key_v4.REPLACEMENT_DUE.values()
    assert {q["source"] for q in test} | {s for s, _ in due} == set(build_key_v4.KEEP_SOURCES)
    assert {q["qtype"] for q in test} | {t for _, t in due} == set(build_key_v4.QTYPES)
    # The test set is the fresh one, nothing from v1 to v3 (rotation rule 3), less the
    # fresh questions that motivated a change since.
    test_ids = {q["id"] for q in test}
    assert test_ids == set(build_key_v4.FRESH_TEST) - set(build_key_v4.FRESH_MOVED_TO_DEV)
    assert all(V4[q]["in_sample_for"] == [] for q in test_ids)
    for qid in build_key_v4.FRESH_MOVED_TO_DEV:
        assert V4[qid]["split"] == "dev"
        assert V4[qid]["in_sample_for"] == ["maplestats"]


def test_fresh_questions_repeat_no_earlier_question():
    earlier = {q["question"].strip().lower() for v in ("v1", "v2", "v3") for q in load_key(v)}
    fresh = [q for q in V4.values() if q["source_version"] == "v4-test"]
    assert len(fresh) == 25
    assert not {q["question"].strip().lower() for q in fresh} & earlier


def test_the_split_is_fixed_by_its_salt():
    assert build_key_v4.split_of() == build_key_v4.split_of()
    old = {q: V4[q]["split"] for q in V4 if V4[q]["source_version"] != "v4-test"}
    assert old == build_key_v4.split_of()
    # SALT was the first balanced salt at launch; questions moved under rule 3 go to dev.
    assert build_key_v4._balanced(build_key_v4._alternate(build_key_v4.SALT))
    assert all(V4[q]["split"] == "dev" for q in build_key_v4.MOVED_TO_DEV)


def test_extra_passes_only_for_volatile_questions():
    jobs = run.jobs(list(V4.values()), repeat=1, extra_passes=2)
    volatile = [q for q in V4.values() if q["extra_passes"]]
    assert 0 < len(volatile) < len(V4) / 3
    assert len(jobs) == len(V4) + 2 * len(volatile)
    assert {q["id"] for q, r in jobs if r > 0} == {q["id"] for q in volatile}


def test_prompt_asks_for_the_json_block():
    prompt = run.PROMPTS["v4"].format(today="2026-11-09")
    assert "```json" in prompt and '"not_published"' in prompt and '"abstain"' in prompt


def test_structured_block_takes_the_last_parseable_one():
    text = 'x\n```json\n{"a": 1}\n```\nmore\n```json\n{"b": 2}\n```'
    assert structured_block(text) == {"b": 2}
    assert structured_block("```json\n{not json}\n```") is None
    assert structured_block("no block") is None


def test_json_not_published_settles_a_refusal_the_prose_regex_missed():
    text = "The dataset has CSV files for 2011 to 2022, so there's no 2024 file."
    assert grade_answer(T23, text).outcome != "correct"
    g = grade_v4(T23, text + block(values=[], not_published=True, abstain=False))
    assert (g.outcome, g.basis) == ("correct", "json")


def test_json_values_in_thousands_and_the_comparison_call():
    q = V4["C-01"]
    values = [{"name": k, "value": v, "unit": "%"} for k, v in q["expected"].items()]
    right = grade_v4(q, "Ontario's rate was higher." + block(values=values))
    assert (right.outcome, right.basis) == ("correct", "json")
    wrong = grade_v4(q, "Quebec's rate was higher." + block(values=values))
    assert wrong.outcome != "correct"


def test_json_release_date_and_abstain():
    q = V4["R-04"]
    (date,) = q["expected"].values()
    g = grade_v4(q, block(values=[{"name": "release", "value": date}]))
    assert (g.outcome, g.basis) == ("correct", "json")
    g = grade_v4(q, block(values=[], abstain=True, abstain_reason="calendar unreachable"))
    assert (g.outcome, g.basis) == ("abstained", "json")


def test_a_wrong_json_value_falls_back_to_the_prose():
    q = V4["C-19"]
    prose = grade_answer(q, "The target was 9.99%.")
    g = grade_v4(q, "The target was 9.99%." + block(values=[{"name": "rate", "value": 9.99}]))
    assert g.basis == "regex" and g.outcome == prose.outcome


def test_frozen_server_records_then_replays_offline(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from tests.maple_test import frozen_server

    calls = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"value": 2.5})

    async def fetch() -> dict:
        transport = httpx.MockTransport(upstream)
        async with httpx.AsyncClient(transport=transport) as client:
            return (await client.get("https://example.test/series")).json()

    # install() patches httpx.AsyncClient.send for the whole process. Register the
    # unpatched method with monkeypatch first, so teardown restores it: an earlier version
    # registered the patched one, and the cassette stayed installed for every later test
    # in the same worker (CI, #218: "mocked but not requested" in unrelated modules).
    original = httpx.AsyncClient.send
    monkeypatch.setattr(httpx.AsyncClient, "send", original)
    path = tmp_path / "cassette.jsonl.gz"
    frozen_server.install(frozen_server.Cassette(path, "auto"))
    assert asyncio.run(fetch()) == {"value": 2.5}
    httpx.AsyncClient.send = original  # type: ignore[method-assign]
    frozen_server.install(frozen_server.Cassette(path, "replay"))
    assert asyncio.run(fetch()) == {"value": 2.5}
    assert len(calls) == 1  # the replay never reached the upstream


@pytest.mark.parametrize(
    ("deterministic", "verdict", "flag"),
    [
        ("correct", {"outcome": "correct", "confidence": 0.95}, False),
        ("correct", {"outcome": "partial", "confidence": 0.95}, True),
        ("correct", {"outcome": "correct", "confidence": 0.5}, True),
        ("correct", {"error": "timed out"}, True),
    ],
)
def test_review_triage(deterministic, verdict, flag):
    assert judge.needs_review(deterministic, verdict) is flag


def test_judge_prompt_has_the_key_but_not_the_patterns_or_split():
    q = V4["X-24"]
    text = judge.prompt(q, "answer")
    assert "flag_pattern" not in text and '"split"' not in text and "why_kept" not in text
    assert q["question"] in text and judge.RUBRICS["flag"] in text
    assert all(judge.qtype_of(q) in judge.RUBRICS for q in V4.values())


def test_no_httpx_patch_outlives_the_frozen_server_test():
    """Runs after the frozen-server test (file order): the global send must be httpx's own."""
    import httpx

    assert httpx.AsyncClient.send.__module__.startswith("httpx")


FRESH = {q["id"]: q for q in V4.values() if q["source_version"] == "v4-test"}


def test_fresh_calls_are_graded():
    # The review (2026-11-09): N-12 and N-13 were typed numeric, so a wrong call passed.
    q = FRESH["N-13"]
    rates = list(q["expected"].values())
    right = (
        "the Canadian dollar strengthened against the yen"
        if rates[1] < rates[0]
        else ("the Canadian dollar weakened against the yen")
    )
    wrong = (
        right.replace("strengthened", "X")
        .replace("weakened", "strengthened")
        .replace("X", "weakened")
    )
    numbers = f" The rates were {rates[0]} and {rates[1]}."
    assert grade_v4(q, right + "." + numbers).outcome == "correct"
    assert grade_v4(q, wrong + "." + numbers).outcome != "correct"


def test_review_regex_fixes():
    # "Normals" is not "no": an invented CSV is no refusal.
    assert grade_v4(FRESH["N-23"], "Its Climate Normals CSV files cover 1981-2010.").outcome != (
        "correct"
    )
    # A DataStore said to be inactive is wrong.
    text = "Toronto Public Health owns it; it is refreshed daily. The DataStore is not active."
    assert grade_v4(FRESH["N-19"], text).outcome != "correct"
    text = "Toronto Public Health owns it, refreshed daily, and it is in the DataStore (active)."
    assert grade_v4(FRESH["N-19"], text).outcome == "correct"
