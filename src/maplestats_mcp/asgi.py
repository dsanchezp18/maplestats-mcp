"""Compose the hosted ASGI app: health check -> CORS -> security -> FastMCP's app.

`FastMCP.http_app()` (confirmed this session, fastmcp==4.0.3) returns a
Starlette ASGI app exposing the MCP endpoint at /mcp — exactly the
callable shared/security.py's middleware was designed to wrap.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from maplestats_mcp import __version__, config

# Before the server module is imported: it reads the transport to describe the export tools
# (local files on stdio, hosted downloads on HTTP), and a self-hoster who starts this app
# with uvicorn sets no MAPLE_TRANSPORT.
config.mark_serving_http()

from maplestats_mcp.server import mcp, preload
from maplestats_mcp.shared.security import (
    with_cors,
    with_health_endpoint,
    with_http_security,
    with_icon_routes,
    with_openai_apps_challenge,
    with_stats_endpoint,
)
from maplestats_mcp.shared.usage import STATS, public_snapshot

ASSETS_DIR = Path(__file__).parent / "assets"

logger = logging.getLogger("maplestats_mcp.asgi")


def check_hosting_config() -> None:
    """Refuse or warn about an unsafe hosted configuration.

    Runs inside build_asgi_app(), so it applies however the app is started:
    `python -m maplestats_mcp` and `uvicorn maplestats_mcp.asgi:app` alike. The
    bind address is read from MAPLE_HOST; a bind chosen only with uvicorn's own
    --host flag is not visible here, which is why the refusal below (which does
    not depend on the address) is the part to rely on.
    """
    auth_token = config.get_auth_token()
    if config.get_require_auth() and not auth_token:
        raise RuntimeError("MAPLE_REQUIRE_AUTH is set but MAPLE_AUTH_TOKEN is empty.")
    loopback = config.get_host() in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not auth_token:
        logger.warning(
            "MCP HTTP endpoint is bound externally without MAPLE_AUTH_TOKEN; "
            "set a token before exposing it beyond a trusted network."
        )


# Sent on every response. Browsers ignore HSTS on plain http, so a local server is
# unaffected; behind https (the hosted one) it keeps later visits on https.
_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"strict-transport-security", b"max-age=31536000"),
)


def with_security_headers(app):
    """Add _SECURITY_HEADERS to every HTTP response the wrapped app sends."""

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await app(scope, receive, send_with_headers)

    return wrapped


def with_shutdown_save(app, save):
    """Run `save()` when the server shuts down, before the wrapped app's own shutdown.

    The exit hook in shared/usage.py is not enough on its own: uvicorn re-raises
    SIGTERM once it has shut down (checked with uvicorn 0.54 on 2026-11-06), so the
    process ends by the signal and Python's atexit hooks never run. The ASGI
    lifespan shutdown does run, so the /stats counts are saved there.
    """

    async def wrapped(scope, receive, send):
        if scope["type"] != "lifespan":
            await app(scope, receive, send)
            return

        async def receive_and_save():
            message = await receive()
            if message["type"] == "lifespan.shutdown":
                try:
                    save()
                except Exception:  # never block the shutdown on the counts
                    logger.exception("Saving the usage counts at shutdown failed")
            return message

        await app(scope, receive_and_save, send)

    return wrapped


def with_startup_preload(app, preload):
    """Await `preload()` when the server starts, before the wrapped app's own startup.

    uvicorn runs the lifespan startup before it binds the port, so until preload
    finishes /health does not answer and the platform's startup and readiness
    probes keep traffic on the previous revision. A failed preload is logged and
    the server starts anyway: the modules then load lazily on first use, as on stdio.
    """

    async def wrapped(scope, receive, send):
        if scope["type"] != "lifespan":
            await app(scope, receive, send)
            return

        async def receive_after_preload():
            message = await receive()
            if message["type"] == "lifespan.startup":
                started = time.perf_counter()
                try:
                    await preload()
                except Exception:  # never refuse to start over a warm-up
                    logger.exception("Preloading the modules failed; they will load on first use")
                else:
                    logger.info(
                        "Preloaded every module and the search index in %.1f s",
                        time.perf_counter() - started,
                    )
            return message

        await app(scope, receive_after_preload, send)

    return wrapped


def build_asgi_app():
    check_hosting_config()
    # Idle sessions are dropped after 5 minutes (the default is 30): a small instance
    # cannot hold the 10,000 sessions one busy caller could otherwise open.
    inner = mcp.http_app(session_idle_timeout=300)
    if config.get_preload_enabled():
        inner = with_startup_preload(inner, lambda: preload(mcp))
    secured = with_http_security(
        inner,
        auth_token=config.get_auth_token(),
        max_concurrent_requests=config.get_max_concurrent_requests(),
        max_requests_per_client=config.get_max_requests_per_client(),
        rate_limit_requests=config.get_rate_limit_requests(),
        rate_limit_window_seconds=config.get_rate_limit_window_seconds(),
        trust_proxy_headers=config.get_trust_proxy_headers(),
        trusted_proxy_hops=config.get_trusted_proxy_hops(),
        client_ip_header=config.get_client_ip_header(),
    )
    cors = with_cors(secured, allowed_origins=config.get_allowed_origins())
    png = (ASSETS_DIR / "favicon.png").read_bytes()
    svg = (ASSETS_DIR / "mark.svg").read_bytes()
    iconed = with_icon_routes(
        cors,
        icons={
            "/favicon.ico": (png, "image/png"),
            "/favicon.png": (png, "image/png"),
            "/favicon.svg": (svg, "image/svg+xml"),
        },
    )
    challenged = with_openai_apps_challenge(iconed, token=config.get_openai_apps_challenge())
    healthy = with_health_endpoint(challenged, version=__version__)
    if not config.get_usage_stats_enabled():
        return with_security_headers(healthy)
    stats = with_stats_endpoint(healthy, snapshot=public_snapshot)
    return with_security_headers(with_shutdown_save(stats, STATS.save))


app = build_asgi_app()
