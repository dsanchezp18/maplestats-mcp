"""Compose the hosted ASGI app: health check -> security middleware -> FastMCP's app.

`FastMCP.http_app()` (confirmed this session, fastmcp==4.0.3) returns a
Starlette ASGI app exposing the MCP endpoint at /mcp — exactly the
callable shared/security.py's middleware was designed to wrap.
"""

from __future__ import annotations

from maplestats_mcp import __version__, config
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.security import with_health_endpoint, with_http_security


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
    return with_health_endpoint(secured, version=__version__)


app = build_asgi_app()
