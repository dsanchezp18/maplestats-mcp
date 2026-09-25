from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.delta import client
from maplestats_mcp.shared.errors import InvalidInput


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


async def test_get_file_link_invalid_date_raises():
    with pytest.raises(InvalidInput):
        await client.get_file_link("not-a-date")
