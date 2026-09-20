from __future__ import annotations

import pytest

from maple_data_mcp.modules.ised.spectrum import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_LAYER_URL = f"{constants.SERVICE_URL}/{constants.LAYER_INDEX}"

_SAMPLE_ATTRIBUTES = {
    "OBJECTID": 1,
    "NEW_LICNO": "010287465-001",
    "LICENSEE": "TBayTel",
    "SERVICE": "CELL",
    "TRANSMIT_FREQ": 887.5,
    "PROV": "ON",
    "LATITUDE": 48.474652778,
    "LONGITUDE": -89.186441667,
}


async def test_query_licences_returns_attributes(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [{"attributes": _SAMPLE_ATTRIBUTES}], "exceededTransferLimit": False},
    )
    result = await client.query_licences()
    assert result.returned_count == 1
    assert result.rows[0]["LICENSEE"] == "TBayTel"
    assert result.exceeded_transfer_limit is False


async def test_query_licences_where_clause_passed_through(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=LICENSEE+%3D+%27TBayTel%27&outFields=%2A&f=json"
            "&resultRecordCount=5&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [], "exceededTransferLimit": False},
    )
    result = await client.query_licences(where="LICENSEE = 'TBayTel'", limit=5)
    assert result.returned_count == 0


async def test_invalid_input_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.query_licences(limit=0)
    with pytest.raises(InvalidInput):
        await client.query_licences(offset=-1)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{_LAYER_URL}/query?where=1%3D1&outFields=%2A&f=json"
                "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
            ),
            status_code=500,
        )
    with pytest.raises(UpstreamError):
        await client.query_licences()
