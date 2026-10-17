"""Compose the hosted ASGI app: health check -> CORS -> security -> FastMCP's app.

`FastMCP.http_app()` (confirmed this session, fastmcp==4.0.3) returns a
Starlette ASGI app exposing the MCP endpoint at /mcp — exactly the
callable shared/security.py's middleware was designed to wrap.
"""

from __future__ import annotations

import logging
from pathlib import Path

from maplestats_mcp import __version__, config
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.security import (
    with_cors,
    with_health_endpoint,
    with_http_security,
    with_icon_routes,
    with_stats_endpoint,
)
from maplestats_mcp.shared.usage import STATS

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


def build_asgi_app():
    check_hosting_config()
    inner = mcp.http_app()
    secured = with_http_security(
        inner,
        auth_token=config.get_auth_token(),
        max_concurrent_requests=config.get_max_concurrent_requests(),
        rate_limit_requests=config.get_rate_limit_requests(),
        rate_limit_window_seconds=config.get_rate_limit_window_seconds(),
        trust_proxy_headers=config.get_trust_proxy_headers(),
        trusted_proxy_hops=config.get_trusted_proxy_hops(),
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
    healthy = with_health_endpoint(iconed, version=__version__)
    if not config.get_usage_stats_enabled():
        return healthy
    return with_stats_endpoint(healthy, snapshot=STATS.snapshot)


app = build_asgi_app()
