from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.indicators import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_RESPONSE = {
    "results": {
        "geo": [
            {"geo_code": "0", "label": {"en": "Canada", "fr": "Canada"}},
            {"geo_code": "1", "label": {"en": "Newfoundland and Labrador", "fr": "Terre-Neuve"}},
        ],
        "indicators": [
            {
                "registry_number": 4098,
                "indicator_number": 1,
                "geo_code": 0,
                "title": {"en": "Quarterly population estimate", "fr": "Estimation trimestrielle"},
                "value": {"en": "41,417,056", "fr": "41 417 056"},
                "refper": {"en": "April 1, 2026", "fr": "1er avril 2026"},
                "daily_url": {
                    "en": "/daily-quotidien/260617/dq260617a-eng.htm",
                    "fr": "/daily-quotidien/260617/dq260617a-fra.htm",
                },
                "daily_title": {"en": "Canada's population estimates", "fr": "Estimations"},
                "source": "17100009",
                "release_date": "2026-06-17",
                "growth_rate": {
                    "growth": {"en": "-0.1%", "fr": "-0,1 %"},
                    "arrow_direction": 2,
                    "details": {"en": "(quarterly change)", "fr": "(variation trimestrielle)"},
                },
            },
            {
                "registry_number": 4099,
                "indicator_number": 2,
                "geo_code": 1,
                "title": {"en": "Unemployment rate", "fr": "Taux de chômage"},
                "value": {"en": "10.2%", "fr": "10,2 %"},
                "refper": {"en": "August 2026", "fr": "Août 2026"},
                "daily_url": {"en": "", "fr": ""},
                "daily_title": {"en": "", "fr": ""},
                "source": "14100287",
                "release_date": "2026-09-05",
            },
        ],
    }
}


async def test_get_indicators_parses_entries(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_RESPONSE)
    result = await client.get_indicators("all")
    assert result.total_matched == 2
    first = result.indicators[0]
    assert first.title == "Quarterly population estimate"
    assert first.value == "41,417,056"
    assert first.geo_name == "Canada"
    assert first.growth == "-0.1%"
    assert first.daily_url == "https://www.statcan.gc.ca/daily-quotidien/260617/dq260617a-eng.htm"


async def test_get_indicators_filters_by_query(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_RESPONSE)
    result = await client.get_indicators("all", "unemployment")
    assert result.total_matched == 1
    assert result.indicators[0].geo_name == "Newfoundland and Labrador"


async def test_get_indicators_filters_by_geo_code(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_RESPONSE)
    result = await client.get_indicators("all", geo_code=0)
    assert result.total_matched == 1
    assert result.indicators[0].title == "Quarterly population estimate"


async def test_get_indicators_lang_fr(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_RESPONSE)
    result = await client.get_indicators("all", lang="fr")
    assert result.indicators[0].title == "Estimation trimestrielle"


async def test_get_indicators_invalid_dataset_raises():
    with pytest.raises(InvalidInput):
        await client.get_indicators("not_a_real_dataset")


async def test_get_indicators_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.get_indicators("all", limit=0)


async def test_get_indicators_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=constants.DATASET_URLS["all"], status_code=500)
    with pytest.raises(UpstreamError):
        await client.get_indicators("all")
