# ============================================================
# Tests for the chat demo's validation, limits and routing
# Author: Daniel Sanchez
# Purpose: Check the public endpoint's guards without calling any model
# Inputs:  none
# Outputs: pass/fail
# ============================================================

import asyncio
import base64
import hashlib
import re
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import app as chat_app


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    chat_app._hits_by_client.clear()
    chat_app._daily_count["n"] = 0
    chat_app._daily_tokens["n"] = 0

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


def test_unexpected_error_stays_counted_and_logs_only_the_type(monkeypatch, caplog):
    # Not a BackendFailure, so nothing says no model call was billed: no refund.
    async def failing_model(messages):
        raise RuntimeError("the secret question text")

    monkeypatch.setattr(chat_app, "ask_model", failing_model)
    client = TestClient(chat_app.app)
    response = post(client, [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    assert chat_app._daily_count["n"] == 1
    assert len(chat_app._hits_by_client) == 1
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


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_deployment_fault_is_not_presented_as_a_blip(monkeypatch, status):
    class ApiError(Exception):
        status_code = status

    async def misconfigured(messages):
        try:
            raise ApiError("model not found")
        except ApiError as error:
            raise chat_app.BackendFailure(billed=False) from error

    monkeypatch.setattr(chat_app, "ask_model", misconfigured)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "hi"}])
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["error"]
    assert chat_app._daily_count["n"] == 0  # not billed, so refunded


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
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_page_policy_allows_only_its_own_inline_script():
    response = TestClient(chat_app.app).get("/")
    page = (chat_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert response.text == page
    inline = re.findall(r"<script>(.*?)</script>", page, flags=re.DOTALL)
    assert len(inline) == 1
    digest = base64.b64encode(hashlib.sha256(inline[0].encode()).digest()).decode()
    policy = dict(
        part.strip().split(" ", 1)
        for part in response.headers["content-security-policy"].split(";")
    )
    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == (
        f"'self' https://cdnjs.cloudflare.com https://gc.zgo.at 'sha256-{digest}'"
    )
    assert "'unsafe-inline'" not in policy["script-src"]
    assert policy["img-src"] == "'self' data: https://dsanchezp18.goatcounter.com"
    assert policy["connect-src"] == "'self' https://dsanchezp18.goatcounter.com"
    assert policy["base-uri"] == "'none'"
    assert policy["form-action"] == "'self'"
    assert policy["frame-ancestors"] == "'none'"


def test_inline_script_hashes_skip_external_scripts():
    page = '<script src="https://x/a.js"></script><script>alert(1)</script>'
    digest = base64.b64encode(hashlib.sha256(b"alert(1)").digest()).decode()
    assert chat_app.inline_script_hashes(page) == [f"'sha256-{digest}'"]


@pytest.mark.parametrize("path", ["/", "/health", "/api/chat"])
def test_every_response_carries_the_common_security_headers(path):
    client = TestClient(chat_app.app)
    if path == "/api/chat":
        response = post(client, [{"role": "user", "content": "hi"}])
    else:
        response = client.get(path)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


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
    monkeypatch.setattr(chat_app, "CLIENT_IP_HEADER", None)
    request = FakeRequest({"x-forwarded-for": "198.51.100.9, 192.0.2.1"})
    assert chat_app.client_address(request) == "192.0.2.1"
    assert chat_app.client_address(FakeRequest({})) == "203.0.113.5"


def test_client_ip_header_comes_first_when_trusted(monkeypatch):
    # Behind Cloudflare, the rightmost X-Forwarded-For entry can be a shared edge.
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(chat_app, "CLIENT_IP_HEADER", "CF-Connecting-IP")
    headers = {
        "cf-connecting-ip": "198.51.100.23",
        "x-forwarded-for": "198.51.100.23, 172.70.1.1",
    }
    assert chat_app.client_address(FakeRequest(headers)) == "198.51.100.23"
    assert chat_app.client_address(
        FakeRequest({"cf-connecting-ip": "2001:db8::1"})
    ) == ("2001:db8::1")


@pytest.mark.parametrize("value", ["", "not-an-address", "999.1.1.1"])
def test_client_ip_header_falls_back_to_forwarded_for(monkeypatch, value):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(chat_app, "CLIENT_IP_HEADER", "CF-Connecting-IP")
    headers = {"cf-connecting-ip": value, "x-forwarded-for": "198.51.100.9, 192.0.2.1"}
    assert chat_app.client_address(FakeRequest(headers)) == "192.0.2.1"
    assert chat_app.client_address(FakeRequest({})) == "203.0.113.5"


def test_client_ip_header_is_ignored_unless_proxy_headers_are_trusted(monkeypatch):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(chat_app, "CLIENT_IP_HEADER", "CF-Connecting-IP")
    request = FakeRequest({"cf-connecting-ip": "198.51.100.23"})
    assert chat_app.client_address(request) == "203.0.113.5"


def test_client_ip_header_separates_callers_behind_one_edge(monkeypatch):
    monkeypatch.setattr(chat_app, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(chat_app, "CLIENT_IP_HEADER", "CF-Connecting-IP")
    monkeypatch.setattr(chat_app, "RATE_PER_HOUR", 1)
    client = TestClient(chat_app.app)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    statuses = [
        client.post(
            "/api/chat",
            json=body,
            headers={"cf-connecting-ip": ip, "x-forwarded-for": f"{ip}, 172.70.1.1"},
        ).status_code
        for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.1")
    ]
    assert statuses == [200, 200, 429]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, None),
        ({"RENDER": "true"}, "CF-Connecting-IP"),
        ({"RENDER": "true", "CHAT_CLIENT_IP_HEADER": ""}, None),
        ({"CHAT_CLIENT_IP_HEADER": "True-Client-IP"}, "True-Client-IP"),
    ],
)
def test_client_ip_header_default_follows_render(environ, expected):
    assert chat_app.client_ip_header(environ) == expected


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
    assert len(tags) == 3  # two CDN libraries and GoatCounter's counter
    for tag in tags:
        assert re.search(r'integrity="sha384-[A-Za-z0-9+/]{64}"', tag), tag
        assert 'crossorigin="anonymous"' in tag, tag


def _fake_anthropic(monkeypatch, responses):
    """Make ask_anthropic see these responses, one per model call."""
    from types import SimpleNamespace

    queue = list(responses)

    class FakeMessages:
        async def create(self, **kwargs):
            return queue.pop(0)

    class FakeClient:
        beta = SimpleNamespace(messages=FakeMessages())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(chat_app, "AsyncAnthropic", lambda **kwargs: FakeClient())


def _ask():
    import asyncio

    return asyncio.run(chat_app.ask_anthropic([{"role": "user", "content": "hi"}]))


def test_step_limit_is_an_answer_not_an_empty_reply(monkeypatch, caplog):
    monkeypatch.setattr(chat_app, "MAX_TOOL_STEPS", 2)
    paused = SimpleNamespace(
        content=[SimpleNamespace(type="mcp_tool_use", name="search_tools", input={})],
        stop_reason="pause_turn",
    )
    _fake_anthropic(monkeypatch, [paused, paused])
    with caplog.at_level("INFO", logger="maplestats_chat"):
        result = _ask()
    assert result["answer"] == chat_app.STEP_LIMIT_ANSWER
    assert len(result["tools_used"]) == 2
    assert "stop_reason=pause_turn" in caplog.text
    assert "hi" not in caplog.text.split("stop_reason")[1]


def test_length_limit_explains_or_marks_the_cut(monkeypatch):
    _fake_anthropic(
        monkeypatch, [SimpleNamespace(content=[], stop_reason="max_tokens")]
    )
    assert _ask()["answer"] == chat_app.LENGTH_LIMIT_ANSWER
    cut = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Partial table")],
        stop_reason="max_tokens",
    )
    _fake_anthropic(monkeypatch, [cut])
    assert _ask()["answer"] == "Partial table" + chat_app.CUT_OFF_NOTE


def test_tool_errors_with_no_answer_point_to_the_data_server(monkeypatch):
    blocks = [
        SimpleNamespace(type="mcp_tool_use", name="call_tool", input={}),
        SimpleNamespace(type="mcp_tool_result", is_error=True),
    ]
    _fake_anthropic(
        monkeypatch, [SimpleNamespace(content=blocks, stop_reason="end_turn")]
    )
    assert _ask()["answer"] == chat_app.DATA_SERVER_ANSWER


# Token budget ----


def _usage(**counts):
    return SimpleNamespace(**counts)


def test_anthropic_calls_add_their_tokens(monkeypatch):
    usage = _usage(
        input_tokens=1000,
        output_tokens=200,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=None,
    )
    paused = SimpleNamespace(content=[], stop_reason="pause_turn", usage=usage)
    done = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Answer")],
        stop_reason="end_turn",
        usage=usage,
    )
    _fake_anthropic(monkeypatch, [paused, done])
    assert _ask()["answer"] == "Answer"
    assert chat_app._daily_tokens["n"] == 2 * 1250


def _fake_openai(monkeypatch, responses, call_tool=None):
    """Make ask_openai_compatible see these responses and a fake MCP server."""
    queue = list(responses)

    class FakeCompletions:
        async def create(self, **kwargs):
            return queue.pop(0)

    class FakeOpenAI:
        chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeMcp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools(self):
            return [SimpleNamespace(name="call_tool", description="", inputSchema={})]

        async def call_tool(self, name, arguments, raise_on_error=False):
            if call_tool:
                return call_tool(name, arguments)
            return SimpleNamespace(
                content=[SimpleNamespace(text="{}")],
                is_error=False,
                structured_content=None,
            )

    monkeypatch.setattr(chat_app, "_openai_tools", [])
    monkeypatch.setattr(chat_app, "AsyncOpenAI", lambda **kwargs: FakeOpenAI())
    monkeypatch.setattr(chat_app, "Client", lambda url: FakeMcp())


def _openai_reply(content, tool_calls=None, usage=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda **kwargs: {"role": "assistant", "content": content},
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _tool_call():
    return SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="call_tool", arguments='{"name": "x"}'),
    )


def test_openai_calls_add_their_tokens(monkeypatch):
    usage = _usage(prompt_tokens=700, completion_tokens=30)
    _fake_openai(
        monkeypatch,
        [
            _openai_reply(None, [_tool_call()], usage),
            _openai_reply("Done", None, usage),
        ],
    )
    result = asyncio.run(
        chat_app.ask_openai_compatible([{"role": "user", "content": "hi"}])
    )
    assert result["answer"] == "Done"
    assert chat_app._daily_tokens["n"] == 2 * 730


def test_spent_token_budget_refuses_before_the_model(monkeypatch):
    monkeypatch.setattr(chat_app, "DAILY_TOKENS", 5000)
    reached_model = []

    async def costly_model(messages):
        reached_model.append(messages)
        chat_app.add_tokens(_usage(input_tokens=4000, output_tokens=1500))
        return {"answer": "ok", "tools_used": []}

    monkeypatch.setattr(chat_app, "ask_model", costly_model)
    client = TestClient(chat_app.app)
    body = [{"role": "user", "content": "hi"}]
    assert post(client, body).status_code == 200
    refused = post(client, body)
    assert refused.status_code == 429
    assert "budget" in refused.json()["error"]
    assert len(reached_model) == 1
    # The refused request was not counted against the question caps.
    assert chat_app._daily_count["n"] == 1


def test_token_budget_resets_with_the_day(monkeypatch):
    monkeypatch.setattr(chat_app, "DAILY_TOKENS", 10)
    chat_app._daily_tokens.update(day=chat_app.datetime(2020, 1, 1).date(), n=10**9)
    assert chat_app.over_limit("203.0.113.9") is None
    assert chat_app._daily_tokens["n"] == 0


def test_usage_without_counts_adds_nothing():
    chat_app.add_tokens(None)
    chat_app.add_tokens(SimpleNamespace(input_tokens="12", output_tokens=True))
    assert chat_app._daily_tokens["n"] == 0


# Refunds after billed calls ----


def test_anthropic_failure_after_the_call_is_billed(monkeypatch):
    done = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Answer")], stop_reason="end_turn"
    )
    _fake_anthropic(monkeypatch, [done])

    def broken_collect(returned):
        raise ValueError("bad result")

    monkeypatch.setattr(chat_app.results, "collect", broken_collect)
    with pytest.raises(chat_app.BackendFailure) as raised:
        _ask()
    assert raised.value.billed is True
    assert isinstance(raised.value.__cause__, ValueError)


def test_anthropic_failure_reading_the_answer_is_billed(monkeypatch):
    # A block without .type breaks final_text after the call was billed.
    done = SimpleNamespace(content=[object()], stop_reason="end_turn")
    _fake_anthropic(monkeypatch, [done])
    with pytest.raises(chat_app.BackendFailure) as raised:
        _ask()
    assert raised.value.billed is True


def test_openai_failure_after_the_step_limit_is_billed(monkeypatch):
    monkeypatch.setattr(chat_app, "MAX_TOOL_STEPS", 1)
    _fake_openai(monkeypatch, [_openai_reply(None, [_tool_call()])])

    def broken_collect(returned):
        raise ValueError("bad result")

    monkeypatch.setattr(chat_app.results, "collect", broken_collect)
    with pytest.raises(chat_app.BackendFailure) as raised:
        asyncio.run(chat_app.ask_openai_compatible([{"role": "user", "content": "hi"}]))
    assert raised.value.billed is True


def test_post_call_failure_is_not_refunded_end_to_end(monkeypatch):
    done = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Answer")], stop_reason="end_turn"
    )
    _fake_anthropic(monkeypatch, [done])
    monkeypatch.setattr(chat_app, "PROVIDER", "anthropic")
    monkeypatch.setattr(chat_app, "ask_model", chat_app.ask_anthropic)

    def broken_collect(returned):
        raise ValueError("bad result")

    monkeypatch.setattr(chat_app.results, "collect", broken_collect)
    response = post(TestClient(chat_app.app), [{"role": "user", "content": "hi"}])
    assert response.status_code == 502
    assert chat_app._daily_count["n"] == 1
    assert len(chat_app._hits_by_client) == 1
