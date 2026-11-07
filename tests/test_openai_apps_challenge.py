"""The /.well-known/openai-apps-challenge route OpenAI's plugin portal checks."""

from __future__ import annotations

from maplestats_mcp import config
from maplestats_mcp.shared.security import (
    OPENAI_APPS_CHALLENGE_PATH,
    with_http_security,
    with_openai_apps_challenge,
)


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"inner"})


async def _get(app, path: str, method: str = "GET") -> tuple[int, dict[bytes, bytes], bytes]:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": ("1.2.3.4", 1),
    }
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


async def test_token_is_served_as_exact_plain_text():
    app = with_openai_apps_challenge(_ok_app, token="abc123-token")
    status, headers, body = await _get(app, OPENAI_APPS_CHALLENGE_PATH)
    assert status == 200
    assert body == b"abc123-token"
    assert headers[b"content-type"].startswith(b"text/plain")


async def test_head_has_no_body():
    app = with_openai_apps_challenge(_ok_app, token="abc123-token")
    status, headers, body = await _get(app, OPENAI_APPS_CHALLENGE_PATH, "HEAD")
    assert status == 200
    assert body == b""
    assert headers[b"content-length"] == b"12"


async def test_no_token_is_404():
    app = with_openai_apps_challenge(_ok_app, token=None)
    status, _, body = await _get(app, OPENAI_APPS_CHALLENGE_PATH)
    assert status == 404
    assert body != b"inner"


async def test_other_paths_reach_the_inner_app():
    app = with_openai_apps_challenge(_ok_app, token="abc123-token")
    assert await _get(app, "/mcp") == (200, {}, b"inner")


async def test_route_bypasses_the_bearer_token():
    # The portal fetches the token anonymously, so it must answer even when
    # /mcp requires a bearer token.
    secured = with_http_security(_ok_app, auth_token="secret")
    app = with_openai_apps_challenge(secured, token="abc123-token")
    status, _, body = await _get(app, OPENAI_APPS_CHALLENGE_PATH)
    assert (status, body) == (200, b"abc123-token")


def test_env_variable_is_read_and_blank_means_unset(monkeypatch):
    monkeypatch.setenv("MAPLE_OPENAI_APPS_CHALLENGE", "  tok  ")
    assert config.get_openai_apps_challenge() == "tok"
    monkeypatch.setenv("MAPLE_OPENAI_APPS_CHALLENGE", "   ")
    assert config.get_openai_apps_challenge() is None
    monkeypatch.delenv("MAPLE_OPENAI_APPS_CHALLENGE")
    assert config.get_openai_apps_challenge() is None
