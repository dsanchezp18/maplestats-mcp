from __future__ import annotations

import inspect
from concurrent.futures import Future

import httpx
import pytest
from tenacity import RetryCallState

from maplestats_mcp import __version__
from maplestats_mcp.shared import http as http_module
from maplestats_mcp.shared.errors import CloudflareChallenge, UpstreamUnavailable
from maplestats_mcp.shared.http import (
    api_get,
    api_post,
    get_raw,
    is_cloudflare_challenge,
    is_retryable,
    new_client,
    post_form_raw,
    send_with_retry,
    wait_honouring_retry_after,
)


async def test_api_get_decodes_json(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/ok", json={"hello": "world"})
    result = await api_get("https://example.invalid/ok")
    assert result == {"hello": "world"}
    assert httpx_mock.get_requests()[0].headers["user-agent"] == f"maplestats-mcp/{__version__}"


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
    assert httpx_mock.get_requests()[0].headers["User-Agent"] == f"maplestats-mcp/{__version__}"


async def test_statcan_requests_open_a_fresh_connection(httpx_mock):
    # StatCan pins a connection to one backend (probed 2026-09-27), so a
    # retry on the same connection repeats the same failure.
    url = "https://www12.statcan.gc.ca/rest/census-recensement/CR2016Geo.json"
    httpx_mock.add_response(url=url, json={})
    await api_get(url)
    assert httpx_mock.get_requests()[0].headers["Connection"] == "close"


async def test_other_hosts_keep_the_connection(httpx_mock):
    httpx_mock.add_response(url="https://example.invalid/data", json={})
    await api_get("https://example.invalid/data")
    assert httpx_mock.get_requests()[0].headers.get("Connection") != "close"


async def test_cloudflare_challenge_is_unavailable_not_a_403(httpx_mock, cloudflare_challenge):
    """www12.statcan.gc.ca, live 2026-10-02: 403 + Cf-Mitigated: challenge."""
    httpx_mock.add_response(url="https://www12.statcan.gc.ca/x", **cloudflare_challenge)
    with pytest.raises(CloudflareChallenge, match="does not try to bypass") as raised:
        await api_get("https://www12.statcan.gc.ca/x")
    assert isinstance(raised.value, UpstreamUnavailable)
    assert len(httpx_mock.get_requests()) == 1


async def test_cloudflare_challenge_is_recognised_on_every_request_helper(
    httpx_mock, cloudflare_challenge
):
    httpx_mock.add_response(is_reusable=True, **cloudflare_challenge)
    with pytest.raises(CloudflareChallenge):
        await get_raw("https://www12.statcan.gc.ca/a")
    with pytest.raises(CloudflareChallenge):
        await api_post("https://www12.statcan.gc.ca/b", json_body={})


def test_a_plain_403_is_not_a_challenge():
    plain = httpx.Response(403, request=httpx.Request("GET", "https://example.invalid/"))
    assert not is_cloudflare_challenge(plain)
    by_title = httpx.Response(
        403,
        content=b"<title>Just a moment...</title>",
        request=httpx.Request("GET", "https://example.invalid/"),
    )
    assert is_cloudflare_challenge(by_title)


async def test_send_with_retry_retries_503_and_returns_404(httpx_mock):
    url = "https://www150.statcan.gc.ca/delta/x.zip"
    httpx_mock.add_response(method="HEAD", url=url, status_code=503, headers={"Retry-After": "2"})
    httpx_mock.add_response(method="HEAD", url=url, status_code=404)
    async with new_client() as client:
        response = await send_with_retry(client, "HEAD", url)
    assert response.status_code == 404  # not raised: the caller decides what 404 means
    assert len(httpx_mock.get_requests()) == 2


def _retry_state(response_headers: dict[str, str], status: int = 429) -> RetryCallState:
    request = httpx.Request("GET", "https://www150.statcan.gc.ca/x")
    response = httpx.Response(status, headers=response_headers, request=request)
    error = httpx.HTTPStatusError("busy", request=request, response=response)
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})  # type: ignore[arg-type]
    state.attempt_number = 1
    future: Future[None] = Future()
    future.set_exception(error)
    state.outcome = future  # type: ignore[assignment]
    return state


def test_retry_after_is_honoured_and_capped():
    assert wait_honouring_retry_after(_retry_state({"retry-after": "7"})) == 7.0
    assert wait_honouring_retry_after(_retry_state({"retry-after": "9999"}, 503)) == 30.0
    # No header, or an HTTP-date form: plain exponential backoff (1s on attempt 1).
    assert wait_honouring_retry_after(_retry_state({})) == 1.0
    assert wait_honouring_retry_after(_retry_state({"retry-after": "Wed, 21 Oct 2026"})) == 1.0


def test_every_main_path_helper_uses_the_retry_after_wait():
    # conftest swaps each decorated function's wait for wait_none, so the
    # wiring is checked on the source: api_get, get_raw, post_form_raw,
    # api_post and send_with_retry, with no plain exponential wait left.
    source = inspect.getsource(http_module)
    assert source.count("wait=_wait_honouring_retry_after,") == 5
    assert "wait=wait_exponential(" not in source


async def test_get_raw_retries_429_with_retry_after(httpx_mock):
    url = "https://www150.statcan.gc.ca/n1/x"
    httpx_mock.add_response(url=url, status_code=429, headers={"Retry-After": "3"})
    httpx_mock.add_response(url=url, text="ok")
    assert (await get_raw(url)).text == "ok"
    assert len(httpx_mock.get_requests()) == 2


async def test_every_main_path_helper_sends_connection_close_to_www150(httpx_mock):
    url = "https://www150.statcan.gc.ca/n1/x"
    httpx_mock.add_response(url=url, json={}, is_reusable=True)
    await api_get(url)
    await get_raw(url)
    await api_post(url, json_body={})
    await post_form_raw(url, data={"a": "b"})
    async with new_client() as client:
        await send_with_retry(client, "GET", url)
    sent = httpx_mock.get_requests()
    assert len(sent) == 5
    assert all(request.headers["Connection"] == "close" for request in sent)


def test_retry_after_ignores_non_ascii_digits():
    from maplestats_mcp.shared.http import retry_after_seconds

    assert retry_after_seconds("²") is None
    assert retry_after_seconds("12") == 12.0
