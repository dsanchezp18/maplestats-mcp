from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.census_profile import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_GEO_CODELIST_URL = f"{constants.BASE_URL}/codelist/{constants.AGENCY}/CL_GEO_PR/latest"
_CHAR_CODELIST_URL = (
    f"{constants.BASE_URL}/codelist/{constants.AGENCY}/{constants.CHARACTERISTIC_CODELIST}/latest"
)

_GEO_CODELIST_RESPONSE = {
    "data": {
        "codelists": [
            {
                "id": "CL_GEO_PR",
                "codes": [
                    {"id": "2021A000235", "name": "Ontario"},
                    {"id": "2021A000224", "name": "Quebec"},
                ],
            }
        ]
    }
}

_CHAR_CODELIST_RESPONSE = {
    "data": {
        "codelists": [
            {
                "id": "CL_CHARACTERISTIC",
                "codes": [
                    {"id": "1", "name": "Population, 2021"},
                    {"id": "4", "name": "Total private dwellings"},
                    {"id": "8", "name": "Total - Age groups of the population - 100% data"},
                    {"id": "9", "name": "0 to 14 years", "parent": "8"},
                ],
            }
        ]
    }
}

_DATA_RESPONSE = {
    "data": {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {
                        "attributes": [0, 0, 0, 0, 0, 0, None, 0, 0, 0],
                        "observations": {"0": ["14223942", 0, None, None, None]},
                    }
                }
            }
        ],
        "structures": [
            {
                "dimensions": {
                    "series": [
                        {"id": "FREQ", "values": [{"id": "A5", "name": "Every 5 years"}]},
                        {
                            "id": "REF_AREA",
                            "values": [{"id": "2021A000235", "name": "Ontario"}],
                        },
                        {"id": "GENDER", "values": [{"id": "1", "name": "Total"}]},
                        {
                            "id": "CHARACTERISTIC",
                            "values": [{"id": "1", "name": "Population, 2021"}],
                        },
                        {"id": "STATISTIC", "values": [{"id": "1", "name": "Counts"}]},
                    ]
                },
                "attributes": {
                    "series": [
                        {
                            "id": "TOPIC",
                            "values": [{"id": "1", "name": "Population and dwelling counts"}],
                        },
                        {"id": "NOTE", "values": [{"id": "1", "name": "some note"}]},
                        {"id": "RELEASE_DATE", "values": [{"value": "2022-02-09"}]},
                        {"id": "GEO_LEVEL", "values": [{"id": "2", "name": "Province"}]},
                        {"id": "ALT_GEO_CODE", "values": [{"value": "35"}]},
                        {
                            "id": "GEO_DESC",
                            "values": [{"id": "2021A000235", "name": "Ontario  [Province]"}],
                        },
                        {"id": "PROV_TERR", "values": []},
                        {"id": "DATA_QUALITY_FLAG", "values": [{"value": "20000"}]},
                        {"id": "TNR_LF", "values": [{"value": "3.8"}]},
                        {"id": "TNR_SF", "values": [{"value": "2.8"}]},
                    ],
                    "observation": [
                        {"id": "DECIMALS", "values": [{"id": "0", "name": "Zero"}]},
                        {"id": "FLAG", "values": []},
                        {"id": "CI_LOW", "values": []},
                        {"id": "CI_HIGH", "values": []},
                    ],
                },
            }
        ],
    }
}


async def test_search_geography_parses_matches(httpx_mock):
    httpx_mock.add_response(url=_GEO_CODELIST_URL, json=_GEO_CODELIST_RESPONSE)
    result = await client.search_geography("canada_provinces_territories", "onta")
    assert result.total_matched == 1
    assert result.matches[0].code == "2021A000235"
    assert result.matches[0].name == "Ontario"


async def test_search_geography_empty_query_returns_all(httpx_mock):
    httpx_mock.add_response(url=_GEO_CODELIST_URL, json=_GEO_CODELIST_RESPONSE)
    result = await client.search_geography("canada_provinces_territories", "")
    assert result.total_matched == 2


async def test_search_geography_sends_accept_language_header(httpx_mock):
    httpx_mock.add_response(url=_GEO_CODELIST_URL, json=_GEO_CODELIST_RESPONSE)
    await client.search_geography("canada_provinces_territories", "", lang="fr")
    request = httpx_mock.get_requests()[0]
    assert request.headers["accept-language"] == "fr"


async def test_search_geography_invalid_level_raises():
    with pytest.raises(InvalidInput):
        await client.search_geography("not_a_real_level", "ontario")


async def test_search_geography_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.search_geography("canada_provinces_territories", "ontario", limit=0)


async def test_search_characteristic_parses_matches(httpx_mock):
    httpx_mock.add_response(url=_CHAR_CODELIST_URL, json=_CHAR_CODELIST_RESPONSE)
    result = await client.search_characteristic("population, 2021")
    assert result.total_matched == 1
    assert result.matches[0].code == "1"
    assert result.matches[0].parent_code is None


async def test_search_characteristic_exposes_parent_hierarchy(httpx_mock):
    httpx_mock.add_response(url=_CHAR_CODELIST_URL, json=_CHAR_CODELIST_RESPONSE)
    result = await client.search_characteristic("0 to 14")
    assert result.total_matched == 1
    assert result.matches[0].code == "9"
    assert result.matches[0].parent_code == "8"


async def test_get_data_parses_values_and_attributes(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/data/{constants.AGENCY},DF_PR/A5.2021A000235.1.1.1?format=jsondata",
        json=_DATA_RESPONSE,
    )
    result = await client.get_data("canada_provinces_territories", ["2021A000235"], ["1"])
    assert result.release_date == "2022-02-09"
    assert len(result.values) == 1
    value = result.values[0]
    assert value.geography_code == "2021A000235"
    assert value.geography_name == "Ontario  [Province]"
    assert value.characteristic_name == "Population, 2021"
    assert value.topic == "Population and dwelling counts"
    assert value.gender == "Total"
    assert value.statistic == "Counts"
    assert value.value == 14223942.0
    assert value.flag is None
    assert value.confidence_interval_low is None


async def test_get_data_invalid_level_raises():
    with pytest.raises(InvalidInput):
        await client.get_data("not_a_real_level", ["2021A000235"], ["1"])


async def test_get_data_empty_geography_codes_raises():
    with pytest.raises(InvalidInput):
        await client.get_data("canada_provinces_territories", [], ["1"])


async def test_get_data_invalid_gender_raises():
    with pytest.raises(InvalidInput):
        await client.get_data(
            "canada_provinces_territories", ["2021A000235"], ["1"], gender="not_a_gender"
        )


async def test_get_data_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            url=f"{constants.BASE_URL}/data/{constants.AGENCY},DF_PR/A5.2021A000235.1.1.1?format=jsondata",
            status_code=500,
        )
    with pytest.raises(UpstreamError):
        await client.get_data("canada_provinces_territories", ["2021A000235"], ["1"])
