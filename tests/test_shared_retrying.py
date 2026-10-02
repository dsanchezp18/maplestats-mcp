"""The retrying GET used by modules that own their client (reference, surveys)."""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.shared import retrying
from maplestats_mcp.shared.http import new_client


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(retrying.asyncio, "sleep", fake_sleep)
    return recorded


async def test_retry_after_header_is_honoured_on_429(httpx_mock, waits):
    url = "https://www150.statcan.gc.ca/n1/page"
    httpx_mock.add_response(url=url, status_code=429, headers={"retry-after": "7"})
    httpx_mock.add_response(url=url, text="ok")
    async with new_client() as client:
        response = await retrying.get_with_retry(client, url)
    assert response.text == "ok"
    assert waits == [7.0]


async def test_backoff_without_retry_after_and_cap(httpx_mock, waits):
    url = "https://www150.statcan.gc.ca/n1/page"
    httpx_mock.add_response(url=url, status_code=503, headers={"retry-after": "9999"})
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, text="ok")
    async with new_client() as client:
        await retrying.get_with_retry(client, url)
    assert waits == [retrying.RETRY_MAX_SECONDS, 4.0]


async def test_returns_last_response_when_retries_run_out(httpx_mock, waits):
    url = "https://www150.statcan.gc.ca/n1/page"
    httpx_mock.add_response(url=url, status_code=502, is_reusable=True)
    async with new_client() as client:
        response = await retrying.get_with_retry(client, url)
    assert response.status_code == 502
    assert len(waits) == retrying.RETRY_ATTEMPTS - 1


async def test_excluded_status_is_returned_immediately(httpx_mock, waits):
    url = "https://www150.statcan.gc.ca/n1/page"
    httpx_mock.add_response(url=url, status_code=500)
    async with new_client() as client:
        response = await retrying.get_with_retry(
            client, url, retry_statuses=retrying.RETRY_STATUSES - {500}
        )
    assert response.status_code == 500
    assert waits == []


async def test_network_error_is_retried_then_raised(httpx_mock, waits):
    url = "https://www150.statcan.gc.ca/n1/page"
    for _ in range(retrying.RETRY_ATTEMPTS):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    async with new_client() as client:
        with pytest.raises(httpx.ConnectTimeout):
            await retrying.get_with_retry(client, url)
    assert len(waits) == retrying.RETRY_ATTEMPTS - 1


async def test_statcan_hosts_get_connection_close(httpx_mock):
    url = "https://www150.statcan.gc.ca/n1/page"
    httpx_mock.add_response(url=url, text="ok")
    async with new_client() as client:
        await retrying.get_with_retry(client, url)
    assert httpx_mock.get_requests()[0].headers["connection"] == "close"
