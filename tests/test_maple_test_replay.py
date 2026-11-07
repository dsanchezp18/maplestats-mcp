"""Replay recorded Maple Test tool exchanges against this checkout, offline.

Each fixture in tests/maple_test/replay/ holds one question's tool call, the HTTP the
server exchanged with StatCan or the Bank of Canada when it was recorded, and the result.
pytest-httpx serves the recorded HTTP, so nothing leaves the machine and no model runs.
A failure means this checkout would hand a model a different result for a Maple Test
question. If that change is intended, re-record (`uv run python -m tests.maple_test.replay
record`) and explain the fixture diff in the pull request; tests/maple_test/replay.py has
the details.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from pytest_httpx import HTTPXMock

from tests.maple_test.replay import (
    CASES,
    Case,
    call,
    fixture_path,
    frozen_today,
    load_http,
    normalize,
    problems,
    question,
    response_kwargs,
)

HTTP = load_http()
RERECORD = "re-record with `uv run python -m tests.maple_test.replay record` if this is intended"


def test_every_case_has_a_fixture_and_every_fixture_a_case():
    recorded = sorted(p.stem for p in fixture_path(CASES[0]).parent.glob("*.json"))
    assert recorded == sorted(c.question_id for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c.question_id for c in CASES])
def test_the_fixture_still_answers_the_key(case: Case):
    """The recorded result holds the key's figures; a rebuilt key needs a re-record."""
    fixture = json.loads(fixture_path(case).read_text(encoding="utf-8"))
    assert (fixture["tool"], fixture["arguments"]) == (case.tool, case.arguments), RERECORD
    assert question(case), case.question_id
    assert problems(case, fixture["result"]) == []


# Unrecorded requests fail (pytest-httpx's default); a recorded request the server no
# longer makes does not, since the result comparison catches any effect it had.
@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
@pytest.mark.parametrize("case", CASES, ids=[c.question_id for c in CASES])
async def test_replayed_call_gives_the_recorded_result(case: Case, httpx_mock: HTTPXMock):
    fixture = json.loads(fixture_path(case).read_text(encoding="utf-8"))
    for rid in fixture["requests"]:
        httpx_mock.add_response(**response_kwargs(HTTP[rid]))
    with frozen_today(date.fromisoformat(fixture["recorded_on"])):
        structured, text = await call(case)
    # What the model reads is the text; it must carry the same result.
    assert normalize(json.loads(text)) == normalize(structured)
    assert problems(case, structured) == [], RERECORD
    assert normalize(structured) == fixture["result"], RERECORD
