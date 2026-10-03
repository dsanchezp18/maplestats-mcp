from __future__ import annotations

import asyncio
from typing import Any, cast

from maplestats_mcp import config
from maplestats_mcp.shared import security
from maplestats_mcp.shared.security import (
    origin_allowed,
    with_cors,
    with_health_endpoint,
    with_http_security,
)


def _scope(method: str = "POST", path: str = "/mcp", headers=None, client=("1.2.3.4", 1)):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "client": client,
    }


async def _call(app, scope) -> int:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_missing_or_wrong_token_is_401():
    app = with_http_security(_ok_app, auth_token="secret")
    assert await _call(app, _scope()) == 401
    wrong = [(b"authorization", b"Bearer nope")]
    assert await _call(app, _scope(headers=wrong)) == 401


async def test_valid_token_is_accepted():
    app = with_http_security(_ok_app, auth_token="secret")
    assert await _call(app, _scope(headers=[(b"authorization", b"Bearer secret")])) == 200


async def test_non_ascii_token_is_401_not_a_crash():
    app = with_http_security(_ok_app, auth_token="secret")
    headers = [(b"authorization", "Bearer sécret".encode("latin-1"))]
    assert await _call(app, _scope(headers=headers)) == 401


async def test_rate_limit_returns_429():
    app = with_http_security(_ok_app, rate_limit_requests=2, rate_limit_window_seconds=60)
    assert await _call(app, _scope()) == 200
    assert await _call(app, _scope()) == 200
    assert await _call(app, _scope()) == 429


async def test_open_sse_streams_do_not_consume_concurrency_slots():
    """Long-lived GET /mcp streams must not lock out POST tool calls."""
    release = asyncio.Event()

    async def streaming_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if scope["method"] == "GET":
            await release.wait()
        await send({"type": "http.response.body", "body": b""})

    app = with_http_security(streaming_app, max_concurrent_requests=1, rate_limit_requests=0)
    streams = [asyncio.create_task(_call(app, _scope("GET"))) for _ in range(3)]
    await asyncio.sleep(0)
    assert await asyncio.wait_for(_call(app, _scope("POST")), timeout=1) == 200
    release.set()
    assert await asyncio.gather(*streams) == [200, 200, 200]


async def test_short_burst_queues_instead_of_503(monkeypatch):
    monkeypatch.setattr(security, "_QUEUE_TIMEOUT_SECONDS", 1.0)

    async def slow_app(scope, receive, send):
        await asyncio.sleep(0.05)
        await _ok_app(scope, receive, send)

    app = with_http_security(slow_app, max_concurrent_requests=2, rate_limit_requests=0)
    statuses = await asyncio.gather(*(_call(app, _scope()) for _ in range(6)))
    assert statuses == [200] * 6


async def test_saturated_server_still_sheds_load(monkeypatch):
    monkeypatch.setattr(security, "_QUEUE_TIMEOUT_SECONDS", 0.05)
    release = asyncio.Event()

    async def blocking_app(scope, receive, send):
        await release.wait()
        await _ok_app(scope, receive, send)

    app = with_http_security(blocking_app, max_concurrent_requests=1, rate_limit_requests=0)
    first = asyncio.create_task(_call(app, _scope()))
    await asyncio.sleep(0)
    assert await _call(app, _scope()) == 503
    release.set()
    assert await first == 200


async def test_health_bypasses_auth():
    app = with_health_endpoint(with_http_security(_ok_app, auth_token="secret"), version="x")
    assert await _call(app, _scope("GET", "/health")) == 200


async def _response(app, scope) -> tuple[int, dict[bytes, bytes]]:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return start["status"], {k.lower(): v for k, v in start["headers"]}


async def _no_options_app(scope, receive, send):
    # FastMCP's Streamable HTTP app answers OPTIONS on /mcp with 405.
    status = 405 if scope["method"] == "OPTIONS" else 200
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _hosted(**security_options):
    secured = with_http_security(_no_options_app, **security_options)
    return with_cors(secured, allowed_origins=config.DEFAULT_ALLOWED_ORIGINS)


_SITE = [(b"origin", b"https://dsanchezp18.github.io")]


async def test_preflight_from_allowed_origin_gets_cors_headers():
    preflight = _SITE + [
        (b"access-control-request-method", b"POST"),
        (b"access-control-request-headers", b"content-type, mcp-session-id"),
    ]
    status, headers = await _response(_hosted(), _scope("OPTIONS", headers=preflight))
    assert status == 204
    assert headers[b"access-control-allow-origin"] == b"https://dsanchezp18.github.io"
    allow_headers = headers[b"access-control-allow-headers"].lower()
    for name in (b"content-type", b"mcp-session-id", b"mcp-protocol-version", b"authorization"):
        assert name in allow_headers
    assert b"POST" in headers[b"access-control-allow-methods"]


async def test_preflight_bypasses_auth_and_rate_limit():
    app = _hosted(auth_token="secret", rate_limit_requests=1)
    statuses = [(await _response(app, _scope("OPTIONS", headers=_SITE)))[0] for _ in range(5)]
    assert statuses == [204] * 5
    # The preflights spent none of the budget: the first real call still passes.
    authed = _SITE + [(b"authorization", b"Bearer secret")]
    assert (await _response(app, _scope(headers=authed)))[0] == 200


async def test_options_skips_rate_limit_without_cors_wrapper():
    app = with_http_security(_no_options_app, auth_token="secret", rate_limit_requests=1)
    statuses = [await _call(app, _scope("OPTIONS")) for _ in range(3)]
    assert 401 not in statuses and 429 not in statuses


async def test_post_from_unknown_origin_is_403():
    evil = [(b"origin", b"https://evil.example")]
    assert (await _response(_hosted(), _scope(headers=evil)))[0] == 403
    assert (await _response(_hosted(), _scope("OPTIONS", headers=evil)))[0] == 403


async def test_post_without_origin_is_allowed_without_cors_headers():
    status, headers = await _response(_hosted(), _scope())
    assert status == 200
    assert b"access-control-allow-origin" not in headers


async def test_allowed_origin_response_exposes_session_id():
    local = [(b"origin", b"http://localhost:3000")]
    status, headers = await _response(_hosted(), _scope(headers=local))
    assert status == 200
    assert headers[b"access-control-allow-origin"] == b"http://localhost:3000"
    assert b"mcp-session-id" in headers[b"access-control-expose-headers"].lower()


async def test_error_responses_carry_cors_headers():
    status, headers = await _response(_hosted(auth_token="secret"), _scope(headers=_SITE))
    assert status == 401
    assert headers[b"access-control-allow-origin"] == b"https://dsanchezp18.github.io"


def test_origin_patterns():
    allowed = ["https://*.office.com", "http://localhost:*", "https://example.org"]
    assert origin_allowed("https://excel.office.com", allowed)
    assert not origin_allowed("https://office.com", allowed)
    assert not origin_allowed("https://excel.office.com.evil.example", allowed)
    assert origin_allowed("http://localhost", allowed)
    assert origin_allowed("http://LOCALHOST:8080", allowed)
    assert not origin_allowed("http://localhost.evil.example", allowed)
    assert not origin_allowed("http://localhost:80x", allowed)
    assert origin_allowed("https://example.org/", allowed)
    assert not origin_allowed("null", allowed)
    assert not origin_allowed("https://excel.office.com", config.DEFAULT_ALLOWED_ORIGINS)
    assert origin_allowed("https://anything.example", ["*"])


def test_allowed_origins_env(monkeypatch):
    monkeypatch.delenv("MAPLE_ALLOWED_ORIGINS", raising=False)
    assert config.get_allowed_origins() == config.DEFAULT_ALLOWED_ORIGINS
    monkeypatch.setenv("MAPLE_ALLOWED_ORIGINS", " https://*.office.com , https://a.example ")
    assert config.get_allowed_origins() == ("https://*.office.com", "https://a.example")


def test_hosted_app_answers_preflight_and_rejects_foreign_origin():
    from starlette.testclient import TestClient

    from maplestats_mcp.asgi import build_asgi_app

    with TestClient(cast(Any, build_asgi_app())) as client:
        preflight = client.options(
            "/mcp",
            headers={
                "Origin": "https://dsanchezp18.github.io",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert preflight.status_code == 204
        assert preflight.headers["access-control-allow-origin"] == ("https://dsanchezp18.github.io")
        evil = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example", "Accept": "application/json"},
        )
        assert evil.status_code == 403
