from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.statcan.delta import client
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable


async def test_get_file_link_existing_file(httpx_mock):
    httpx_mock.add_response(
        method="HEAD",
        url="https://www150.statcan.gc.ca/delta/20260918.zip",
        headers={"Content-Length": "4688355"},
    )
    result = await client.get_file_link("2026-09-18")
    assert result.exists is True
    assert result.size_bytes == 4688355
    assert result.url == "https://www150.statcan.gc.ca/delta/20260918.zip"


async def test_get_file_link_missing_file(httpx_mock):
    httpx_mock.add_response(
        method="HEAD", url="https://www150.statcan.gc.ca/delta/20260920.zip", status_code=404
    )
    result = await client.get_file_link("2026-09-20")
    assert result.exists is False
    assert result.size_bytes is None


async def test_head_is_retried_after_a_timeout(httpx_mock):
    """Live 2026-10-02: one HEAD timed out after 15.5 s, the next answered in 0.3 s."""
    url = "https://www150.statcan.gc.ca/delta/20261001.zip"
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"), method="HEAD", url=url)
    httpx_mock.add_response(
        method="HEAD", url=url, headers={"Content-Length": "3874723643"}, status_code=200
    )
    result = await client.get_file_link("2026-10-01")
    assert result.exists is True
    assert result.size_bytes == 3_874_723_643


async def test_head_is_retried_on_503_and_sends_connection_close(httpx_mock):
    url = "https://www150.statcan.gc.ca/delta/20260918.zip"
    httpx_mock.add_response(method="HEAD", url=url, status_code=503, headers={"Retry-After": "1"})
    httpx_mock.add_response(method="HEAD", url=url, headers={"Content-Length": "10"})
    result = await client.get_file_link("2026-09-18")
    assert result.exists is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].headers["connection"] == "close"


async def test_head_that_never_answers_is_unavailable(httpx_mock):
    url = "https://www150.statcan.gc.ca/delta/20260918.zip"
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"), method="HEAD", url=url)
    with pytest.raises(UpstreamUnavailable):
        await client.get_file_link("2026-09-18")


async def test_get_file_link_invalid_date_raises():
    with pytest.raises(InvalidInput):
        await client.get_file_link("not-a-date")
