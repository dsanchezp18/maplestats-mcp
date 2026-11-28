"""The Maple Test harness: --resume and the wait on the CLI's usage-limit reply.

On 2026-11-22 the account's 5-hour limit was reached mid-run: every later question came back
as "You've hit your 5-hour limit" in about 3 seconds, was recorded as a run error, and 55
answers had to be set aside and asked again by hand. `run` now waits for the reset instead of
recording that reply, and `--resume` carries on in an existing run file.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.maple_test import inputs, run

LIMIT = "You've hit your 5-hour limit · resets 6:30am (UTC)"


def test_limit_wait_runs_to_the_named_reset_plus_three_minutes():
    now = datetime(2026, 11, 22, 2, 33, tzinfo=UTC)
    assert run.limit_wait(LIMIT, now) == (3 * 3600 + 57 * 60) + 180


def test_limit_wait_rolls_to_the_next_day_once_the_reset_has_passed():
    now = datetime(2026, 11, 22, 7, 0, tzinfo=UTC)
    assert run.limit_wait(LIMIT, now) == (23 * 3600 + 30 * 60) + 180


def test_limit_wait_handles_pm_and_a_missing_reset_time():
    now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    assert run.limit_wait("You've hit your limit · resets 1pm (UTC)", now) == 3600 + 180
    assert run.limit_wait("You've hit your limit", now) == 1800.0


def _answer(question: dict[str, Any], response: str, duration: float = 12.0) -> run.Answer:
    return run.Answer(
        question_id=question["id"],
        arm="",
        requested_model="m",
        model_ids=["m"],
        tools_available=[],
        started_at="2026-11-22T00:00:00+00:00",
        duration_s=duration,
        tool_calls=[],
        is_error=False,
        response=response,
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Two questions, no model: `ask` replies from a script and logs what it was asked."""
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"questions": [{"id": "Q-1"}, {"id": "Q-2"}]}))
    monkeypatch.setitem(run.SUITES, "v1", replace(run.SUITES["v1"], runs=tmp_path, key=key))
    monkeypatch.setattr(inputs, "environment", lambda repo: {"python": "test"})
    monkeypatch.setattr(run, "limit_wait", lambda message, now=None: 0.0)
    asked: list[str] = []
    replies = {"Q-1": ["The answer is 1."], "Q-2": [LIMIT, LIMIT, "The answer is 2."]}

    def ask(
        arm: str,
        model: str,
        question: dict[str, Any],
        config: Any,
        version: str = "v1",
        *,
        system_prompt: str | None = None,
    ):
        asked.append(question["id"])
        text = replies[question["id"]].pop(0)
        return _answer(question, text, 3.0 if text == LIMIT else 12.0)

    monkeypatch.setattr(run, "ask", ask)
    return asked


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_a_usage_limit_reply_is_asked_again_not_recorded(harness: list[str]):
    out = run.run("no_tools", "m", run.REPO, None, "", version="v1")
    rows = _rows(out)
    assert [(r["question_id"], r["response"]) for r in rows] == [
        ("Q-1", "The answer is 1."),
        ("Q-2", "The answer is 2."),
    ]
    assert harness == ["Q-1", "Q-2", "Q-2", "Q-2"]


def test_resume_asks_only_what_the_newest_run_file_lacks(
    harness: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Started on an earlier day under the same name and model; another arm's file whose name
    # ends the same way must not be picked up.
    class EarlierDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 21, tzinfo=UTC)

    ask = run.ask

    def interrupted(arm, model, question, config, version="v1", *, system_prompt=None):
        if question["id"] == "Q-2":
            raise RuntimeError("session interrupted")
        return ask(arm, model, question, config, version, system_prompt=system_prompt)

    monkeypatch.setattr(run, "datetime", EarlierDay)
    monkeypatch.setattr(run, "ask", interrupted)
    with pytest.raises(RuntimeError, match="session interrupted"):
        run.run("no_tools", "m", run.REPO, None, "", version="v1")
    monkeypatch.setattr(run, "datetime", datetime)
    monkeypatch.setattr(run, "ask", ask)
    harness.clear()
    started = tmp_path / "2026-11-21_no_tools_m.jsonl"
    before = started.read_bytes()
    (tmp_path / "2026-11-22_other_no_tools_m.jsonl").write_text("", encoding="utf-8")
    out = run.run("no_tools", "m", run.REPO, None, "", version="v1", resume=True)
    assert out == started
    assert [(r["question_id"], r["response"]) for r in _rows(out)] == [
        ("Q-1", "The answer is 1."),
        ("Q-2", "The answer is 2."),
    ]
    assert "Q-1" not in harness
    assert started.read_bytes().startswith(before)
    record = inputs.read_manifest(started, "v1")
    assert record is not None and "2026-11-21" in record["system_prompt"]


def test_without_resume_an_existing_run_file_is_never_overwritten(harness: list[str]):
    run.run("no_tools", "m", run.REPO, None, "", version="v1")
    with pytest.raises(SystemExit, match="--resume"):
        run.run("no_tools", "m", run.REPO, None, "", version="v1")


# Issue #273: the first call to a tool through call_tool, and whether its arguments were refused.
def _use(call_id: str, tool: str, server: str = "maplestats") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": f"mcp__{server}__call_tool",
                    "input": {"name": tool, "arguments": {}},
                }
            ]
        },
    }


def _result(call_id: str, text: str | None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id}
    if text is not None:
        block |= {"is_error": True, "content": [{"type": "text", "text": text}]}
    else:
        block["content"] = "ok"
    return {"type": "user", "message": {"content": [block]}}


def test_routed_calls_reads_the_tool_and_the_error_code_of_each_call_tool_call():
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "s", "name": "mcp__maplestats__search_tools"}
                ]
            },
        },
        _use("a", "jobbank_get_wages"),
        _result("a", "[invalid_input] noc is required. Next: ..."),
        _use("b", "jobbank_get_wages"),
        _result("b", None),
        _use("c", "boc_get_observations", server="maplestats-local"),
        _result("c", "something went wrong"),
    ]
    assert run.routed_calls(events) == [
        {"tool": "jobbank_get_wages", "error": "invalid_input"},
        {"tool": "jobbank_get_wages", "error": None},
        {"tool": "boc_get_observations", "error": "error"},
    ]


def test_first_calls_counts_only_each_answers_first_call_to_a_tool():
    from tests.maple_test.grade import first_calls

    runs = [
        {
            "routed_calls": [
                {"tool": "jobbank_get_wages", "error": "invalid_input"},
                {"tool": "jobbank_get_wages", "error": None},  # the retry: not counted
                {"tool": "wds_get_series", "error": None},
            ]
        },
        {"routed_calls": [{"tool": "jobbank_get_wages", "error": "not_found"}]},
        {"tool_calls": []},  # a run from before 2026-11-24: nothing recorded
    ]
    assert first_calls(runs) == {
        "first_calls": 3,
        "first_call_rejected": 0.33,
        "first_call_rejected_tools": {"jobbank_get_wages": 1},
    }
    assert first_calls([{"tool_calls": []}])["first_call_rejected"] is None
