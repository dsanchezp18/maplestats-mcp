"""Compose the hosted ASGI app: health check -> security middleware -> FastMCP's app.

`FastMCP.http_app()` (confirmed this session, fastmcp==4.0.3) returns a
Starlette ASGI app exposing the MCP endpoint at /mcp — exactly the
callable shared/security.py's middleware was designed to wrap.
"""

from __future__ import annotations

from pathlib import Path

from maplestats_mcp import __version__, config
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.security import (
    with_health_endpoint,
    with_http_security,
    with_icon_routes,
)

ASSETS_DIR = Path(__file__).parent / "assets"


def build_asgi_app():
    inner = mcp.http_app()
    secured = with_http_security(
        inner,
        auth_token=config.get_auth_token(),
        max_concurrent_requests=config.get_max_concurrent_requests(),
        rate_limit_requests=config.get_rate_limit_requests(),
        rate_limit_window_seconds=config.get_rate_limit_window_seconds(),
        trust_proxy_headers=config.get_trust_proxy_headers(),
    )
    png = (ASSETS_DIR / "favicon.png").read_bytes()
    svg = (ASSETS_DIR / "mark.svg").read_bytes()
    iconed = with_icon_routes(
        secured,
        icons={
            "/favicon.ico": (png, "image/png"),
            "/favicon.png": (png, "image/png"),
            "/favicon.svg": (svg, "image/svg+xml"),
        },
    )
    return with_health_endpoint(iconed, version=__version__)


app = build_asgi_app()
