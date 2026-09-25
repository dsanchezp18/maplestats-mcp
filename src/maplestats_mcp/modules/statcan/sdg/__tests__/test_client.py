from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.sdg import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_CANADA_BASE = constants.FRAMEWORK_BASE_URLS["canada"]
_GLOBAL_BASE = constants.FRAMEWORK_BASE_URLS["global"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_INDEX_JSON = {
    "12-1-1": {
        "goal_number": "12",
        "target_number": "12.1",
        "indicator_name": "Proportion of new light duty vehicle registrations that are zero-emission",
        "reporting_status": "complete",
    },
    "8-3-1": {
        "goal_number": "8",
        "target_number": "8.3",
        "indicator_name": "Proportion of informal employment",
        "reporting_status": "complete",
    },
}

_META_JSON = {
    "goal_number": "12",
    "target_number": "12.1",
    "indicator_name": "Proportion of new light duty vehicle registrations that are zero-emission",
    "national_indicator_description": "Measures zero-emission vehicle registrations.",
    "computation_units": "Percentage",
    "reporting_status": "complete",
    "published": True,
    "source_url_1": "https://doi.org/10.25318/2010002101-eng",
    "source_organisation_1": "Statistics Canada",
    "source_url_text_1": "Table 20-10-0021-01",
    "source_periodicity_1": "Annual",
}

_GLOBAL_META_JSON = {
    "goal_number": "1",
    "target_number": "1.a",
    "indicator_name": "Total official support for sustainable development",
    "STAT_CONC_DEF": "Defined by OECD/DAC.",
    "reporting_status": "complete",
    "source_url_1": "https://example.org/source",
}

_DATA_JSON = {
    "Year": [2021, 2022],
    "Geography": [None, "Ontario"],
    "Value": [0.37, 0.63],
}


async def test_search_indicators_lists_all_with_empty_query(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/meta/all.json", json=_INDEX_JSON)
    result = await client.search_indicators("canada")
    assert result.total_matched == 2
    assert result.returned_count == 2


async def test_search_indicators_filters_by_name(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/meta/all.json", json=_INDEX_JSON)
    result = await client.search_indicators("canada", "informal")
    assert result.total_matched == 1
    assert result.indicators[0].code == "8-3-1"


async def test_search_indicators_rejects_bad_framework():
    with pytest.raises(InvalidInput):
        await client.search_indicators("bogus")


async def test_search_indicators_rejects_bad_lang():
    with pytest.raises(InvalidInput):
        await client.search_indicators("canada", lang="de")


async def test_search_indicators_rejects_bad_limit():
    with pytest.raises(InvalidInput):
        await client.search_indicators("canada", limit=0)


async def test_search_indicators_global_uses_global_base_url(httpx_mock):
    httpx_mock.add_response(url=f"{_GLOBAL_BASE}/en/meta/all.json", json=_INDEX_JSON)
    result = await client.search_indicators("global")
    assert result.framework == "global"


async def test_get_indicator_metadata_parses_canadian_fields(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/meta/12-1-1.json", json=_META_JSON)
    result = await client.get_indicator_metadata("canada", "12-1-1")
    assert result.description == "Measures zero-emission vehicle registrations."
    assert result.published is True
    assert len(result.sources) == 1
    assert result.sources[0].organisation == "Statistics Canada"


async def test_get_indicator_metadata_falls_back_to_global_description_field(httpx_mock):
    httpx_mock.add_response(url=f"{_GLOBAL_BASE}/en/meta/1-a-1.json", json=_GLOBAL_META_JSON)
    result = await client.get_indicator_metadata("global", "1-a-1")
    assert result.description == "Defined by OECD/DAC."
    assert result.published is None
    assert len(result.sources) == 1


async def test_get_indicator_metadata_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/meta/99-9-9.json", status_code=404)
    with pytest.raises(NotFound):
        await client.get_indicator_metadata("canada", "99-9-9")


async def test_get_indicator_metadata_rejects_bad_code():
    with pytest.raises(InvalidInput):
        await client.get_indicator_metadata("canada", "12-1-1; drop table")


async def test_get_indicator_data_reshapes_columns_to_observations(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/12-1-1.json", json=_DATA_JSON)
    result = await client.get_indicator_data("canada", "12-1-1")
    assert result.returned_count == 2
    first, second = result.observations
    assert first.year == 2021
    assert first.value == 0.37
    assert first.disaggregations == {}
    assert second.disaggregations == {"Geography": "Ontario"}


async def test_get_indicator_data_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{_CANADA_BASE}/en/data/99-9-9.json", status_code=404)
    with pytest.raises(NotFound):
        await client.get_indicator_data("canada", "99-9-9")
