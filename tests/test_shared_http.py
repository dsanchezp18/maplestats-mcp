from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.shared.http import api_get, get_raw


async def test_api_get_decodes_json(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/ok", json={"hello": "world"})
    result = await api_get("https://example.invalid/ok")
    assert result == {"hello": "world"}
    assert httpx_mock.get_requests()[0].headers["user-agent"] == "maple-data-mcp/0.1"


async def test_api_get_preserves_custom_headers(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/headers", json={"ok": True})
    await api_get("https://example.invalid/headers", headers={"User-Agent": "custom-client"})
    assert httpx_mock.get_requests()[0].headers["user-agent"] == "custom-client"


async def test_api_get_retries_on_500_then_succeeds(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/flaky", status_code=500)
    httpx_mock.add_response(url="https://example.invalid/flaky", json={"ok": True})
    result = await api_get("https://example.invalid/flaky")
    assert result == {"ok": True}


async def test_api_get_does_not_retry_on_404(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/missing", status_code=404)
    with pytest.raises(httpx.HTTPStatusError):
        await api_get("https://example.invalid/missing")
    # exactly one request — no retry attempted for a non-retryable status
    assert len(httpx_mock.get_requests()) == 1


async def test_get_raw_passes_through_409_without_raising(httpx_mock):
    httpx_mock.add_response(
        url="https://example.invalid/locked", status_code=409, content=b"locked"
    )
    response = await get_raw("https://example.invalid/locked")
    assert response.status_code == 409


async def test_get_raw_passes_through_406_without_raising(httpx_mock):
    httpx_mock.add_response(
        url="https://example.invalid/rejected", status_code=406, content=b"nope"
    )
    response = await get_raw("https://example.invalid/rejected")
    assert response.status_code == 406


async def test_get_raw_still_raises_on_404(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/notfound", status_code=404)
    with pytest.raises(httpx.HTTPStatusError):
        await get_raw("https://example.invalid/notfound")
