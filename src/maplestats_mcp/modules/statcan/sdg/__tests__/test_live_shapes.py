"""SDG data cases shaped like the live files (probed 2026-10-02): a Global
indicator with no data is the JSON array `[]`, and Canada 1-1-1 has 6,041
rows, far more than a tool response should carry."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.sdg import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

_CANADA_BASE = constants.FRAMEWORK_BASE_URLS["canada"]
_GLOBAL_BASE = constants.FRAMEWORK_BASE_URLS["global"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


def _wide_body(n: int) -> dict:
    return {
        "Year": [2015 + i % 10 for i in range(n)],
        "Geography": ["Alberta" if i % 2 else "Ontario" for i in range(n)],
        "Value": [float(i) for i in range(n)],
    }


async def test_global_indicator_with_empty_list_body_has_zero_observations(httpx_mock):
    httpx_mock.add_response(url=f"{_GLOBAL_BASE}/en/data/1-1-1.json", json=[])
    result = await client.get_indicator_data("global", "1-1-1")
    assert result.returned_count == 0
    assert result.observations == []
    assert "no observations" in (result.provenance.limits or "")


async def test_data_is_capped_and_says_so(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/1-1-1.json", json=_wide_body(500))
    result = await client.get_indicator_data("canada", "1-1-1", limit=50)
    assert result.returned_count == 50
    assert result.total_matched == 500
    assert "50 of 500" in (result.provenance.limits or "")


async def test_data_offset_pages_forward(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/1-1-1.json", json=_wide_body(30))
    result = await client.get_indicator_data("canada", "1-1-1", limit=10, offset=25)
    assert result.returned_count == 5
    assert result.observations[0].value == 25.0


async def test_year_and_dimension_filters_apply_before_the_cap(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/1-1-1.json", json=_wide_body(100))
    result = await client.get_indicator_data(
        "canada", "1-1-1", start_year=2020, filters={"Geography": "Alberta"}
    )
    assert result.total_matched == 30
    assert {o.disaggregations["Geography"] for o in result.observations} == {"Alberta"}
    assert min(o.year for o in result.observations) >= 2020


async def test_unknown_filter_column_is_invalid_input(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/1-1-1.json", json=_wide_body(5))
    with pytest.raises(InvalidInput, match="Province"):
        await client.get_indicator_data("canada", "1-1-1", filters={"Province": "Alberta"})


async def test_ragged_columns_do_not_crash(httpx_mock):
    body = {"Year": [2020, 2021], "Geography": ["Alberta"], "Value": [1.0]}
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/2-2-2.json", json=body)
    result = await client.get_indicator_data("canada", "2-2-2")
    assert result.returned_count == 2
    assert result.observations[1].value is None
