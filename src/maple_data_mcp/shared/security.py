"""ASGI middleware protecting a hosted MCP endpoint, ported near-verbatim
from EcuDataMCP's helpers/http_security.py (MIT, same author). Adds:
Bearer-token auth, a per-client sliding-window rate limit, and a
concurrency-limiting semaphore — plus a /health endpoint that bypasses
all of it.

Dependency-free by design (stdlib asyncio/hmac/time only) so it has no
opinion about which ASGI framework sits underneath — it wraps whatever
callable FastMCP's `.http_app()` returns.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

ASGIApp = Callable[[dict, Callable, Callable], Awaitable[None]]
_MCP_PATHS = {"/mcp", "/mcp/"}
_QUEUE_TIMEOUT_SECONDS = 0.05


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _client_key(scope: dict) -> str:
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return str(client[0])
    return "unknown"


async def _json_response(
    send: Callable,
    status: int,
    payload: dict,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def with_http_security(
    inner_app: ASGIApp,
    *,
    auth_token: str | None = None,
    max_concurrent_requests: int = 8,
    rate_limit_requests: int = 120,
    rate_limit_window_seconds: float = 60.0,
) -> ASGIApp:
    """Protect MCP requests while leaving health checks and stdio untouched.

    Authentication is opt-in so a local, no-token configuration keeps
    working. When enabled, clients must send `Authorization: Bearer
    <token>`. The concurrency limit rejects excess work instead of
    allowing an unbounded queue of upstream fetches to pile up. The
    per-client sliding-window limit protects a remotely exposed instance
    from one client consuming all available request capacity. Set the
    request limit to 0 to disable it for a trusted local-only deployment.
    """
    slots = asyncio.Semaphore(max(1, max_concurrent_requests))
    rate_limit_requests = max(0, rate_limit_requests)
    rate_limit_window_seconds = max(1.0, rate_limit_window_seconds)
    rate_hits: dict[str, list[float]] = {}
    rate_lock = asyncio.Lock()

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or scope.get("path") not in _MCP_PATHS:
            await inner_app(scope, receive, send)
            return

        if auth_token:
            authorization = _header(scope, b"authorization") or ""
            scheme, _, token = authorization.partition(" ")
            valid = scheme.lower() == "bearer" and hmac.compare_digest(token, auth_token)
            if not valid:
                await _json_response(
                    send,
                    401,
                    {"error": "A valid Bearer token is required for /mcp."},
                    [(b"www-authenticate", b"Bearer")],
                )
                return

        if rate_limit_requests:
            now = time.monotonic()
            client_key = _client_key(scope)
            async with rate_lock:
                hits = [
                    hit
                    for hit in rate_hits.get(client_key, [])
                    if now - hit < rate_limit_window_seconds
                ]
                if len(hits) >= rate_limit_requests:
                    rate_hits[client_key] = hits
                    retry_after = max(1, math.ceil(rate_limit_window_seconds - (now - hits[0])))
                    await _json_response(
                        send,
                        429,
                        {"error": "Rate limit exceeded."},
                        [(b"retry-after", str(retry_after).encode("ascii"))],
                    )
                    return
                hits.append(now)
                rate_hits[client_key] = hits

        try:
            await asyncio.wait_for(slots.acquire(), timeout=_QUEUE_TIMEOUT_SECONDS)
        except TimeoutError:
            await _json_response(
                send,
                503,
                {"error": "Server is busy; please try again."},
                [(b"retry-after", b"1")],
            )
            return

        try:
            await inner_app(scope, receive, send)
        finally:
            slots.release()

    return app


def with_health_endpoint(inner_app: ASGIApp, *, version: str) -> ASGIApp:
    """Add a /health route reporting uptime and version, bypassing security."""
    start_time = datetime.now(UTC)

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") == "http" and scope.get("path") == "/health":
            body = json.dumps(
                {
                    "status": "ok",
                    "uptime_since": start_time.isoformat(),
                    "version": version,
                }
            ).encode("utf-8")
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("utf-8")),
            ]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        await inner_app(scope, receive, send)

    return app
