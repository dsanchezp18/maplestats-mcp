"""ASGI middleware protecting a hosted MCP endpoint. Adds: Bearer-token
auth, a per-client sliding-window rate limit, a concurrency-limiting
semaphore, CORS with Origin validation for browser clients — plus a
/health endpoint that bypasses all of it.

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
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

ASGIApp = Callable[[dict, Callable, Callable], Awaitable[None]]
_MCP_PATHS = {"/mcp", "/mcp/"}

# How long a request may wait for a free concurrency slot before a 503.
# Long enough to absorb an ordinary burst of parallel tool calls (the
# previous 50 ms turned a 9th simultaneous call into an error), short
# enough that a saturated server still sheds load instead of queueing
# without bound.
_QUEUE_TIMEOUT_SECONDS = 5.0


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _client_key(scope: dict, *, trust_proxy_headers: bool) -> str:
    """Identify the caller for rate limiting.

    `X-Forwarded-For` is only honored when `trust_proxy_headers` is
    explicitly enabled — trusting it unconditionally would let any
    direct caller spoof a different rate-limit bucket per request. Set
    MAPLE_TRUST_PROXY_HEADERS only when this process sits behind a
    reverse proxy/load balancer that itself sets (and cannot be told to
    forward a spoofed) X-Forwarded-For; otherwise every request behind
    such a proxy would key off the proxy's own address and the
    per-client limit degrades into one shared global limit.
    """
    if trust_proxy_headers:
        forwarded_for = _header(scope, b"x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
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
    trust_proxy_headers: bool = False,
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
        # OPTIONS is a CORS preflight: browsers send it without credentials
        # and before every cross-origin POST, so it must not need a token
        # or spend the caller's rate-limit budget. with_cors() answers it;
        # without that wrapper the inner app's 405 passes through.
        if (
            scope.get("type") != "http"
            or scope.get("path") not in _MCP_PATHS
            or scope.get("method") == "OPTIONS"
        ):
            await inner_app(scope, receive, send)
            return

        if auth_token:
            authorization = _header(scope, b"authorization") or ""
            scheme, _, token = authorization.partition(" ")
            # Compare bytes, not str: hmac.compare_digest raises TypeError on
            # non-ASCII str input, which would surface as a 500 instead of a
            # 401. Header values were decoded as latin-1, so re-encoding that
            # way recovers the raw bytes the client sent.
            valid = scheme.lower() == "bearer" and hmac.compare_digest(
                token.encode("latin-1"), auth_token.encode("utf-8")
            )
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
            client_key = _client_key(scope, trust_proxy_headers=trust_proxy_headers)
            async with rate_lock:
                # Opportunistically drop any other client's entry once its
                # hits have all aged out of the window — otherwise every
                # distinct client this process has ever seen accumulates
                # a permanent dict entry, an unbounded-growth DoS surface
                # on a long-running hosted instance.
                for other_key in [k for k in rate_hits if k != client_key]:
                    if all(now - hit >= rate_limit_window_seconds for hit in rate_hits[other_key]):
                        del rate_hits[other_key]

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

        # A GET on /mcp is the Streamable HTTP transport's long-lived
        # server-to-client SSE stream, held open for the whole session.
        # Counting it against the concurrency cap would let a handful of
        # connected clients occupy every slot indefinitely and lock
        # everyone else out, so only request-carrying methods (POST,
        # DELETE) take a slot; GET is still authenticated and rate-limited.
        if scope.get("method") == "GET":
            await inner_app(scope, receive, send)
            return

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


def origin_allowed(origin: str, allowed_origins: Sequence[str]) -> bool:
    """Whether a browser Origin header matches one allow-list entry.

    Entries are exact origins (`https://example.org`), `*` for any origin,
    a port wildcard (`http://localhost:*`), or a subdomain wildcard
    (`https://*.example.org`, which does not match the bare domain).
    Comparison ignores case and a trailing slash.
    """
    origin = origin.strip().rstrip("/").lower()
    for entry in allowed_origins:
        entry = entry.strip().rstrip("/").lower()
        if entry == "*" or entry == origin:
            return True
        if entry.endswith(":*"):
            base = entry[:-2]
            if origin == base or (
                origin.startswith(base + ":") and origin[len(base) + 1 :].isdigit()
            ):
                return True
        if "://*." in entry:
            scheme, _, domain = entry.partition("://*.")
            prefix = scheme + "://"
            host = origin[len(prefix) :] if origin.startswith(prefix) else ""
            if host.endswith("." + domain) and "/" not in host:
                return True
    return False


def with_cors(inner_app: ASGIApp, *, allowed_origins: Sequence[str]) -> ASGIApp:
    """CORS and Origin validation for the /mcp endpoint.

    The MCP Streamable HTTP transport requires servers to validate the
    Origin header to stop a web page the user happens to visit from
    driving a local server (DNS rebinding). A request with no Origin is a
    non-browser client (a desktop app, curl, an agent runtime) and is
    allowed; a request whose Origin is not in `allowed_origins` gets 403.
    Allowed browser origins get the headers a browser-based MCP client
    needs: preflight answers, and Mcp-Session-Id exposed to scripts so
    the client can resume its session.

    Wrap this outside with_http_security() so preflights are answered
    before auth and rate limiting, and so 401/429/503 responses still
    carry the headers a browser needs to read them.
    """
    allowed = tuple(allowed_origins)

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or scope.get("path") not in _MCP_PATHS:
            await inner_app(scope, receive, send)
            return

        origin = _header(scope, b"origin")
        if origin is not None and not origin_allowed(origin, allowed):
            await _json_response(
                send, 403, {"error": "Origin not allowed for /mcp."}, [(b"vary", b"Origin")]
            )
            return

        if scope.get("method") == "OPTIONS":
            headers = [(b"allow", _CORS_METHODS), (b"content-length", b"0")]
            if origin is not None:
                headers += _cors_headers(origin)
                headers += [
                    (b"access-control-allow-methods", _CORS_METHODS),
                    (b"access-control-allow-headers", _CORS_ALLOW_HEADERS),
                    (b"access-control-max-age", b"600"),
                ]
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        if origin is None:
            await inner_app(scope, receive, send)
            return

        async def send_with_cors(message: dict) -> None:
            if message.get("type") == "http.response.start":
                kept = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if not key.lower().startswith(b"access-control-")
                ]
                message = {**message, "headers": kept + _cors_headers(origin)}
            await send(message)

        await inner_app(scope, receive, send_with_cors)

    return app


_CORS_METHODS = b"GET, POST, DELETE, OPTIONS"
_CORS_ALLOW_HEADERS = (
    b"Content-Type, Accept, Authorization, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID"
)
_CORS_EXPOSE_HEADERS = b"Mcp-Session-Id, MCP-Protocol-Version, WWW-Authenticate, Retry-After"


def _cors_headers(origin: str) -> list[tuple[bytes, bytes]]:
    # Echo the caller's origin rather than "*": a wildcard cannot be used
    # with the Authorization header the token feature relies on.
    return [
        (b"access-control-allow-origin", origin.encode("latin-1")),
        (b"access-control-expose-headers", _CORS_EXPOSE_HEADERS),
        (b"vary", b"Origin"),
    ]


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


def with_stats_endpoint(inner_app: ASGIApp, *, snapshot: Callable[[], dict]) -> ASGIApp:
    """Add a public /stats route with the aggregate usage counts, bypassing security.

    The counts are tool names and outcomes only (shared/usage.py); nothing a
    caller typed is in them, so the route needs no token.
    """

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("path") == "/stats"
            and scope.get("method") in ("GET", "HEAD")
        ):
            body = json.dumps(snapshot()).encode("utf-8")
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("utf-8")),
                (b"cache-control", b"no-store"),
            ]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send(
                {"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body}
            )
            return

        await inner_app(scope, receive, send)

    return app


def with_icon_routes(inner_app: ASGIApp, *, icons: dict[str, tuple[bytes, str]]) -> ASGIApp:
    """Serve static icon files by path, bypassing security.

    MCP clients such as claude.ai fetch the connector icon from the server's own
    domain (usually /favicon.ico), so the hosted server has to answer there.
    """

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        icon = icons.get(scope.get("path", "")) if scope.get("type") == "http" else None
        if icon is not None and scope.get("method") in ("GET", "HEAD"):
            body, content_type = icon
            headers = [
                (b"content-type", content_type.encode("ascii")),
                (b"content-length", str(len(body)).encode("utf-8")),
                (b"cache-control", b"public, max-age=86400"),
            ]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send(
                {"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body}
            )
            return

        await inner_app(scope, receive, send)

    return app
