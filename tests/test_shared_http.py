from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.shared.http import api_get, get_raw, is_retryable, new_client


async def test_api_get_decodes_json(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/ok", json={"hello": "world"})
    result = await api_get("https://example.invalid/ok")
    assert result == {"hello": "world"}
    assert httpx_mock.get_requests()[0].headers["user-agent"] == "maplestats-mcp/0.1"


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


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.PoolTimeout("pool exhausted"),
        httpx.WriteTimeout("slow write"),
        httpx.ConnectError("refused"),
    ],
)
def test_transient_transport_errors_are_retryable(exc):
    assert is_retryable(exc)


def test_non_transient_errors_are_not_retryable():
    assert not is_retryable(httpx.UnsupportedProtocol("ftp://"))
    assert not is_retryable(ValueError("bad"))


async def test_new_client_sends_project_user_agent(httpx_mock):
    httpx_mock.add_response(url="https://example.test/x", text="ok")
    client = new_client(http2=False, follow_redirects=True)
    try:
        await client.get("https://example.test/x")
    finally:
        await client.aclose()
    assert httpx_mock.get_requests()[0].headers["User-Agent"] == "maplestats-mcp/0.1"
