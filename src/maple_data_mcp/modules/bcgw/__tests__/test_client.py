"""Tests for bcgw/client.py, shaped around real BCGW field shapes and
CQL-building confirmed live 2026-09-22 (see client.py's module
docstring for the GML-date "Z"-suffix quirk).
"""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.bcgw import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_WILDFIRE_FEATURE = {
    "type": "Feature",
    "id": "prot.1",
    "geometry": None,
    "properties": {
        "FIRE_NUMBER": "C20851",
        "FIRE_YEAR": 2026,
        "FIRE_SIZE_HECTARES": 8.9,
        "SOURCE": "Non-corrected ground GPS",
        "TRACK_DATE": "2026-07-16Z",
        "LOAD_DATE": "2026-07-17Z",
        "FIRE_STATUS": "Out",
        "FIRE_URL": "https://wildfiresituation.nrs.gov.bc.ca/incidents?fireYear=2026&incidentNumber=C20851",
    },
}
_WILDFIRE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_WILDFIRE_FEATURE],
    "totalFeatures": 304,
    "numberMatched": 304,
}

_TENURE_FEATURE = {
    "type": "Feature",
    "id": "mta.1",
    "geometry": None,
    "properties": {
        "TENURE_NUMBER_ID": 217457,
        "CLAIM_NAME": "NORSE #6",
        "TENURE_TYPE_CODE": "M",
        "TENURE_TYPE_DESCRIPTION": "Mineral",
        "TENURE_SUB_TYPE_DESCRIPTION": "CLAIM",
        "TITLE_TYPE_DESCRIPTION": "Four Post Claim",
        "ISSUE_DATE": "1985-06-27Z",
        "GOOD_TO_DATE": "2035-12-30Z",
        "AREA_IN_HECTARES": 300,
        "OWNER_NAME": "TECK HIGHLAND VALLEY COPPER CORPORATION",
        "PERCENT_OWNERSHIP": 100,
        "NUMBER_OF_OWNERS": 1,
        "STATEMENT_OF_WORK_EVENT_COUNT": 19,
        "TERMINATION_DATE": None,
    },
}
_TENURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_TENURE_FEATURE],
    "totalFeatures": 42282,
    "numberMatched": 42282,
}


async def test_get_active_wildfires_parses_records(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    result = await client.get_active_wildfires()
    assert result.returned_count == 1
    assert result.total_matched == 304
    fire = result.wildfires[0]
    assert fire.fire_number == "C20851"
    assert fire.fire_year == 2026
    assert fire.status == "Out"
    assert fire.track_date is not None
    assert fire.track_date.isoformat() == "2026-07-16"
    assert fire.geometry is None

    request = httpx_mock.get_requests()[0]
    assert request.url.params["typeName"] == constants.WILDFIRE_TYPE_NAME
    assert request.url.params["propertyName"] == constants.WILDFIRE_ATTRIBUTE_FIELDS
    assert "CQL_FILTER" not in request.url.params


async def test_get_active_wildfires_builds_cql_from_filters(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    await client.get_active_wildfires(status="Out of Control", fire_year=2026, min_size_hectares=10)
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "FIRE_STATUS='Out of Control'" in cql
    assert "FIRE_YEAR=2026" in cql
    assert "FIRE_SIZE_HECTARES>=10" in cql


async def test_get_active_wildfires_include_geometry_omits_property_name(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    await client.get_active_wildfires(include_geometry=True)
    request = httpx_mock.get_requests()[0]
    assert "propertyName" not in request.url.params
    assert request.url.params["srsName"] == constants.DEFAULT_SRS


async def test_get_active_wildfires_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.get_active_wildfires(limit=0)
    with pytest.raises(InvalidInput):
        await client.get_active_wildfires(offset=-1)


async def test_get_mining_tenure_parses_records(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    result = await client.get_mining_tenure()
    assert result.returned_count == 1
    assert result.total_matched == 42282
    tenure = result.tenures[0]
    assert tenure.tenure_number_id == 217457
    assert tenure.claim_name == "NORSE #6"
    assert tenure.owner_name == "TECK HIGHLAND VALLEY COPPER CORPORATION"
    assert tenure.issue_date is not None
    assert tenure.issue_date.isoformat() == "1985-06-27"
    assert tenure.termination_date is None


async def test_get_mining_tenure_builds_cql_and_uppercases_owner(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.get_mining_tenure(tenure_type="mineral", owner_name="teck", min_area_hectares=100)
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "TENURE_TYPE_CODE='M'" in cql
    assert "OWNER_NAME LIKE '%TECK%'" in cql
    assert "AREA_IN_HECTARES>=100" in cql


async def test_get_mining_tenure_invalid_tenure_type_raises():
    with pytest.raises(InvalidInput):
        await client.get_mining_tenure(tenure_type="not-a-type")


async def test_get_mining_tenure_escapes_single_quotes_in_owner_name(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.get_mining_tenure(owner_name="o'brien")
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "O''BRIEN" in cql


async def test_query_layer_generic_layer(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    result = await client.query_layer(constants.MINING_TENURE_TYPE_NAME)
    assert result.type_name == constants.MINING_TENURE_TYPE_NAME
    assert result.returned_count == 1
    assert result.records[0]["TENURE_NUMBER_ID"] == 217457
    request = httpx_mock.get_requests()[0]
    assert "propertyName" not in request.url.params
    assert "srsName" not in request.url.params


async def test_query_layer_include_geometry_reprojects(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.query_layer(constants.MINING_TENURE_TYPE_NAME, include_geometry=True)
    request = httpx_mock.get_requests()[0]
    assert request.url.params["srsName"] == constants.DEFAULT_SRS


async def test_query_layer_empty_type_name_raises():
    with pytest.raises(InvalidInput):
        await client.query_layer("  ")


async def test_query_layer_passes_through_cql_and_sort(httpx_mock):
    httpx_mock.add_response(json={"features": [], "totalFeatures": 0, "numberMatched": 0})
    await client.query_layer("WHSE_FOO.BAR", cql_filter="X > 1", property_names="X,Y", sort_by="X")
    request = httpx_mock.get_requests()[0]
    assert request.url.params["CQL_FILTER"] == "X > 1"
    assert request.url.params["propertyName"] == "X,Y"
    assert request.url.params["sortBy"] == "X"
