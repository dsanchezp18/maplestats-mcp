"""The Indicators feed numbers geographies 0-13 (BC is 10), not SGC codes;
geo_code=48 used to return an empty list with no explanation (live,
2026-10-02)."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.indicators import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


def _indicator(geo_code: int, title: str) -> dict:
    return {
        "registry_number": 1,
        "indicator_number": geo_code,
        "geo_code": geo_code,
        "title": {"en": title, "fr": title},
        "value": {"en": "1", "fr": "1"},
    }


_FEED = {
    "results": {
        "geo": [
            {"geo_code": str(code), "label": {"en": name, "fr": name}}
            for code, name in enumerate(
                ["Canada", "NL", "PEI", "NS", "NB", "QC", "ON", "MB", "SK", "AB", "BC", "YT"]
            )
        ],
        "indicators": [
            _indicator(0, "Canada rate"),
            _indicator(9, "AB rate"),
            _indicator(10, "BC rate"),
        ],
    }
}


async def test_feed_code_is_used_as_is(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_FEED)
    result = await client.get_indicators(geo_code=10)
    assert [i.title for i in result.indicators] == ["BC rate"]
    assert result.provenance.limits is None


async def test_sgc_province_code_is_mapped_and_noted(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_FEED)
    result = await client.get_indicators(geo_code=48)
    assert [i.title for i in result.indicators] == ["AB rate"]
    assert "mapped to feed code 9" in (result.provenance.limits or "")


async def test_unknown_code_lists_the_valid_ones(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_FEED)
    with pytest.raises(InvalidInput, match="9=AB"):
        await client.get_indicators(geo_code=99)
