from __future__ import annotations

import asyncio

from maple_data_mcp.shared import security
from maple_data_mcp.shared.security import with_health_endpoint, with_http_security


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
