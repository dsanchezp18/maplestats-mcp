"""The hosted app serves the server icon where MCP clients look for it."""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.asgi import app


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/favicon.ico", "image/png"),
        ("/favicon.png", "image/png"),
        ("/favicon.svg", "image/svg+xml"),
    ],
)
async def test_icon_routes_serve_the_mark(path: str, content_type: str):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content


async def test_server_advertises_an_icon():
    from maplestats_mcp.server import mcp

    assert mcp.icons
    assert mcp.icons[0].src.startswith("data:image/png;base64,")
