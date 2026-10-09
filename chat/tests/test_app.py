# ============================================================
# Tests for the chat demo's validation, limits and routing
# Author: Daniel Sanchez
# Purpose: Check the public endpoint's guards without calling any model
# Inputs:  none
# Outputs: pass/fail
# ============================================================

import pytest
from starlette.testclient import TestClient

import app as chat_app


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    chat_app._hits_by_client.clear()
    chat_app._daily_count["n"] = 0

    async def fake_model(messages):
        return {"answer": "ok", "tools_used": []}

    monkeypatch.setattr(chat_app, "ask_model", fake_model)


def post(client, messages):
    return client.post("/api/chat", json={"messages": messages})


def test_answers_a_valid_question():
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "GDP?"}])
    assert response.status_code == 200
    assert response.json()["answer"] == "ok"


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "x"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "x" * 5000}],
        [{"role": "assistant", "content": "hi"}],
    ],
)
def test_rejects_bad_input(messages):
    assert post(TestClient(chat_app.app), messages).status_code == 400


def test_rate_limit_per_client(monkeypatch):
    monkeypatch.setattr(chat_app, "RATE_PER_HOUR", 2)
    client = TestClient(chat_app.app)
    body = [{"role": "user", "content": "hi"}]
    assert [post(client, body).status_code for _ in range(3)] == [200, 200, 429]


def test_daily_limit(monkeypatch):
    monkeypatch.setattr(chat_app, "DAILY_LIMIT", 1)
    client = TestClient(chat_app.app)
    body = [{"role": "user", "content": "hi"}]
    assert [post(client, body).status_code for _ in range(2)] == [200, 429]


def test_unwraps_call_tool():
    call = chat_app.describe_call(
        "call_tool", {"name": "wds_get_series_info", "arguments": {"v": 1}}
    )
    assert call == {"name": "wds_get_series_info", "arguments": {"v": 1}}


class Block:
    def __init__(self, type, text=""):
        self.type = type
        self.text = text


def test_final_text_drops_narration_before_tools():
    content = [
        Block("text", "I'll check whether the tool can aggregate."),
        Block("mcp_tool_use"),
        Block("mcp_tool_result"),
        Block("text", "Crude oil was the largest export."),
    ]
    assert chat_app.final_text(content) == "Crude oil was the largest export."


def test_final_text_without_tools_keeps_everything():
    assert chat_app.final_text([Block("text", "Hello"), Block("text", " there")]) == (
        "Hello there"
    )
