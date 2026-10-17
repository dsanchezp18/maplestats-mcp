# ============================================================
# Tests for the chat demo's validation, limits and routing
# Author: Daniel Sanchez
# Purpose: Check the public endpoint's guards without calling any model
# Inputs:  none
# Outputs: pass/fail
# ============================================================

import re
from types import SimpleNamespace

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


def test_deeply_nested_json_is_a_400_not_a_crash():
    response = TestClient(chat_app.app).post(
        "/api/chat",
        content=b"[" * 400000,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_backend_failure_refunds_the_budget_and_logs_only_the_type(monkeypatch, caplog):
    async def failing_model(messages):
        raise RuntimeError("the secret question text")

    monkeypatch.setattr(chat_app, "ask_model", failing_model)
    client = TestClient(chat_app.app)
    response = post(client, [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    assert chat_app._daily_count["n"] == 0
    assert chat_app._hits_by_client == {}
    assert "RuntimeError" in caplog.text
    assert "secret question" not in caplog.text


def test_empty_answer_stays_counted(monkeypatch):
    async def empty_model(messages):
        return {"answer": "  ", "tools_used": []}

    monkeypatch.setattr(chat_app, "ask_model", empty_model)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    # The model call ran and was billed, so retrying cannot get it for free.
    assert chat_app._daily_count["n"] == 1
    assert len(chat_app._hits_by_client) == 1


def test_failure_after_a_billed_call_stays_counted(monkeypatch, caplog):
    class ApiError(Exception):
        status_code = 529

    async def late_failure(messages):
        try:
            raise ApiError("secret question text")
        except ApiError as error:
            raise chat_app.BackendFailure(billed=True) from error

    monkeypatch.setattr(chat_app, "ask_model", late_failure)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    assert chat_app._daily_count["n"] == 1
    assert "ApiError" in caplog.text and "529" in caplog.text
    assert "secret question" not in caplog.text


def test_failure_before_any_billed_call_is_refunded(monkeypatch):
    async def early_failure(messages):
        raise chat_app.BackendFailure(billed=False)

    monkeypatch.setattr(chat_app, "ask_model", early_failure)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    assert chat_app._daily_count["n"] == 0
    assert chat_app._hits_by_client == {}


@pytest.mark.parametrize(("fail_on_call", "billed"), [(1, False), (2, True)])
def test_anthropic_backend_reports_whether_a_call_was_billed(
    monkeypatch, fail_on_call, billed
):
    import asyncio
    from types import SimpleNamespace

    calls = 0

    class FakeMessages:
        async def create(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == fail_on_call:
                raise RuntimeError("upstream down")
            return SimpleNamespace(content=[], stop_reason="pause_turn")

    class FakeClient:
        beta = SimpleNamespace(messages=FakeMessages())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(chat_app, "AsyncAnthropic", lambda **kwargs: FakeClient())
    with pytest.raises(chat_app.BackendFailure) as raised:
        asyncio.run(chat_app.ask_anthropic([{"role": "user", "content": "hi"}]))
    assert raised.value.billed is billed
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_idle_clients_are_evicted(monkeypatch):
    chat_app._hits_by_client["198.51.100.7"] = chat_app.deque([0.0])
    assert chat_app.over_limit("203.0.113.9") is None
    assert list(chat_app._hits_by_client) == ["203.0.113.9"]


def test_concurrent_first_requests_do_not_duplicate_tools(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(chat_app, "_openai_tools", [])

    class FakeMcp:
        async def list_tools(self):
            await asyncio.sleep(0.01)
            return [
                SimpleNamespace(name=n, description="d", inputSchema={})
                for n in ("search_tools", "call_tool", "plan_query")
            ]

    mcp = FakeMcp()

    async def burst():
        await asyncio.gather(*(chat_app.load_openai_tools(mcp) for _ in range(5)))

    asyncio.run(burst())
    names = [tool["function"]["name"] for tool in chat_app._openai_tools]
    assert names == ["search_tools", "call_tool", "plan_query"]


def test_page_cannot_be_framed():
    # A framed page arriving with ?q= would spend a billed call per visitor.
    response = TestClient(chat_app.app).get("/?q=GDP")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/plain"},
        {"content-type": "application/x-www-form-urlencoded"},
        {"content-type": "multipart/form-data; boundary=x"},
        {},
    ],
)
def test_non_json_post_is_rejected_before_the_model(monkeypatch, headers):
    # A cross-site page can send these without a preflight; none may spend a call.
    reached_model = []

    async def spy_model(messages):
        reached_model.append(messages)
        return {"answer": "ok", "tools_used": []}

    monkeypatch.setattr(chat_app, "ask_model", spy_model)
    body = b'{"messages": [{"role": "user", "content": "GDP?"}]}'
    response = TestClient(chat_app.app).post("/api/chat", content=body, headers=headers)
    assert response.status_code == 415
    assert "application/json" in response.json()["error"]
    assert reached_model == []
    assert chat_app._daily_count["n"] == 0
    assert chat_app._hits_by_client == {}


def test_json_content_type_with_charset_is_accepted():
    response = TestClient(chat_app.app).post(
        "/api/chat",
        content=b'{"messages": [{"role": "user", "content": "GDP?"}]}',
        headers={"content-type": "Application/JSON; charset=utf-8"},
    )
    assert response.status_code == 200


class FakeRequest:
    def __init__(self, headers, host="203.0.113.5"):
        self.headers = headers
        self.client = SimpleNamespace(host=host)


def test_forwarded_for_is_ignored_unless_proxy_headers_are_trusted(monkeypatch):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", False)
    request = FakeRequest({"x-forwarded-for": "198.51.100.9, 192.0.2.1"})
    assert chat_app.client_address(request) == "203.0.113.5"


def test_forwarded_for_is_read_from_the_right_when_trusted(monkeypatch):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", True)
    request = FakeRequest({"x-forwarded-for": "198.51.100.9, 192.0.2.1"})
    assert chat_app.client_address(request) == "192.0.2.1"
    assert chat_app.client_address(FakeRequest({})) == "203.0.113.5"


def test_a_forged_header_cannot_dodge_the_limit_when_untrusted(monkeypatch):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(chat_app, "RATE_PER_HOUR", 2)
    client = TestClient(chat_app.app)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    statuses = [
        client.post(
            "/api/chat", json=body, headers={"x-forwarded-for": f"198.51.100.{n}"}
        ).status_code
        for n in range(3)
    ]
    assert statuses == [200, 200, 429]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        ({"RENDER": "true"}, True),
        ({"RENDER": "true", "CHAT_TRUST_PROXY_HEADERS": "0"}, False),
        ({"CHAT_TRUST_PROXY_HEADERS": "1"}, True),
    ],
)
def test_proxy_header_default_follows_render(environ, expected):
    assert chat_app.trusts_proxy_headers(environ) is expected


def test_third_party_scripts_carry_integrity_hashes():
    # The page renders model output through innerHTML, so the sanitiser it loads
    # from a CDN must be pinned by hash, not trusted by URL alone.
    page = (chat_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    tags = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", page)
    assert len(tags) == 2
    for tag in tags:
        assert re.search(r'integrity="sha384-[A-Za-z0-9+/]{64}"', tag), tag
        assert 'crossorigin="anonymous"' in tag, tag
