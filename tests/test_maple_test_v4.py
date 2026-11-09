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
    for split in ("dev", "test"):
        part = [q for q in V4.values() if q["split"] == split]
        assert {q["source"] for q in part} == set(build_key_v4.KEEP_SOURCES)
        assert {q["qtype"] for q in part} == set(build_key_v4.QTYPES)
    test = sum(q["split"] == "test" for q in V4.values())
    assert abs(2 * test - len(V4)) <= 6


def test_the_split_is_fixed_by_its_salt():
    assert build_key_v4.split_of() == build_key_v4.split_of()
    assert {q: V4[q]["split"] for q in V4} == build_key_v4.split_of()
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

    original = httpx.AsyncClient.send
    path = tmp_path / "cassette.jsonl.gz"
    try:
        frozen_server.install(frozen_server.Cassette(path, "auto"))
        assert asyncio.run(fetch()) == {"value": 2.5}
        monkeypatch.setattr(httpx.AsyncClient, "send", original)
        frozen_server.install(frozen_server.Cassette(path, "replay"))
        assert asyncio.run(fetch()) == {"value": 2.5}
        assert len(calls) == 1  # the replay never reached the upstream
    finally:
        httpx.AsyncClient.send = original


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
