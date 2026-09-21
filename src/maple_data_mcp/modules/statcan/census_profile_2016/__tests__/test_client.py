from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.census_profile_2016 import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_GEO_RESPONSE = {
    "COLUMNS": [
        "GEO_UID",
        "PROV_TERR_ID_CODE",
        "PROV_TERR_NAME_NOM",
        "GEO_ID_CODE",
        "GEO_NAME_NOM",
        "GEO_TYPE",
        "GEO_GNR_SF",
        "GEO_GNR_LF",
        "GEO_DQ",
    ],
    "DATA": [
        ["2016A000011124", "01", "Canada", "01", "Canada", None, 4.0, 5.1, "20000"],
        ["2016A000235", "35", "Ontario", "35", "Ontario", None, 3.7, 4.6, "20000"],
    ],
}

_DATA_RESPONSE = {
    "COLUMNS": [
        "PROV_TERR_ID",
        "PROV_TERR_NAME_NOM",
        "GEO_UID",
        "GEO_ID",
        "GEO_NAME_NOM",
        "GEO_TYPE",
        "TOPIC_THEME",
        "TEXT_ID",
        "HIER_ID",
        "INDENT_ID",
        "TEXT_NAME_NOM",
        "NOTE_ID",
        "NOTE",
        "T_DATA_DONNEE",
        "T_SYM",
        "M_DATA_DONNEE",
        "M_SYM",
        "F_DATA_DONNEE",
        "F_SYM",
    ],
    "DATA": [
        [
            "01",
            "Canada",
            "2016A000011124",
            "01",
            "Canada",
            None,
            "Population",
            1000,
            "1.1.1",
            0,
            "Population, 2016",
            1,
            None,
            35151728.0,
            None,
            None,
            "...",
            None,
            "...",
        ]
    ],
}


async def test_list_geographies_parses_rows(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/CR2016Geo.json?lang=E&geos=PR&cpt=00", json=_GEO_RESPONSE
    )
    result = await client.list_geographies("canada_provinces_territories")
    assert result.returned_count == 2
    ontario = result.geographies[1]
    assert ontario.geo_uid == "2016A000235"
    assert ontario.geo_name == "Ontario"
    assert ontario.non_response_rate_short_form == 3.7


async def test_list_geographies_invalid_level_raises():
    with pytest.raises(InvalidInput):
        await client.list_geographies("not_a_real_level")


async def test_list_geographies_invalid_province_raises():
    with pytest.raises(InvalidInput):
        await client.list_geographies("canada_provinces_territories", province_territory="mars")


async def test_get_data_parses_values(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/CPR2016.json?lang=E&dguid=2016A000011124&topic=0&notes=0&stat=0"
        ),
        json=_DATA_RESPONSE,
    )
    result = await client.get_data("2016A000011124")
    assert result.returned_count == 1
    value = result.values[0]
    assert value.label == "Population, 2016"
    assert value.total_value == 35151728.0
    assert value.male_symbol == "..."


async def test_get_data_empty_dguid_raises():
    with pytest.raises(InvalidInput):
        await client.get_data("")


async def test_get_data_invalid_topic_raises():
    with pytest.raises(InvalidInput):
        await client.get_data("2016A000011124", topic="not_a_topic")


async def test_get_data_invalid_statistic_raises():
    with pytest.raises(InvalidInput):
        await client.get_data("2016A000011124", statistic="not_a_stat")


async def test_get_data_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{constants.BASE_URL}/CPR2016.json?lang=E&dguid=2016A000011124"
                f"&topic=0&notes=0&stat=0"
            ),
            status_code=500,
        )
    with pytest.raises(UpstreamError):
        await client.get_data("2016A000011124")
