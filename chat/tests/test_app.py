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


def test_follow_up_accepts_a_long_assistant_reply():
    messages = [
        {"role": "user", "content": "GDP?"},
        {"role": "assistant", "content": "a" * 5000},
        {"role": "user", "content": "Why?"},
    ]
    assert post(TestClient(chat_app.app), messages).status_code == 200


def test_unlimited_assistant_history_is_rejected():
    messages = [{"role": "assistant", "content": "a" * 1000}] * 10000
    messages.append({"role": "user", "content": "GDP?"})
    assert isinstance(chat_app.validate_messages({"messages": messages}), str)


def test_messages_must_alternate():
    messages = [{"role": "user", "content": "GDP?"}] * 2
    assert post(TestClient(chat_app.app), messages).status_code == 400


def test_total_conversation_size_is_bounded(monkeypatch):
    monkeypatch.setattr(chat_app, "MAX_CONVERSATION_CHARS", 12)
    messages = [
        {"role": "user", "content": "GDP?"},
        {"role": "assistant", "content": "long answer"},
        {"role": "user", "content": "Why?"},
    ]
    assert post(TestClient(chat_app.app), messages).status_code == 400
    assert chat_app._daily_count["n"] == 0


def test_declared_body_limit_applies_before_model_call(monkeypatch):
    monkeypatch.setattr(chat_app, "MAX_BODY_BYTES", 32)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "x" * 200}])
    assert response.status_code == 413
    assert chat_app._daily_count["n"] == 0


def test_streamed_body_without_length_is_bounded(monkeypatch):
    monkeypatch.setattr(chat_app, "MAX_BODY_BYTES", 32)
    response = TestClient(chat_app.app).post(
        "/api/chat",
        content=iter([b"x" * 20, b"y" * 20]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert chat_app._daily_count["n"] == 0


def test_own_answers_stay_within_history_limit(monkeypatch):
    monkeypatch.setattr(chat_app, "MAX_ASSISTANT_CHARS", 1200)

    async def long_answer(messages):
        return {"answer": "a" * 3000, "tools_used": []}

    monkeypatch.setattr(chat_app, "ask_model", long_answer)
    client = TestClient(chat_app.app)
    messages = [{"role": "user", "content": "GDP?"}]
    first = post(client, messages)
    assert first.status_code == 200
    assert len(first.json()["answer"]) == 1200
    messages += [
        {"role": "assistant", "content": first.json()["answer"]},
        {"role": "user", "content": "Why?"},
    ]
    assert post(client, messages).status_code == 200
