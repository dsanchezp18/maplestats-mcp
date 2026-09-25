from __future__ import annotations

import pytest

from maplestats_mcp.modules.nrcan_nbac import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_FEATURE = {
    "type": "Feature",
    "id": "nbac.6024",
    "geometry": None,
    "properties": {
        "year": 2021,
        "nfireid": 1233,
        "basrc": "MAFiMS",
        "firecaus": "Natural",
        "hs_sdate": "2021-07-10Z",
        "hs_edate": "2021-08-01Z",
        "ag_sdate": None,
        "ag_edate": None,
        "capdate": "2021-09-01Z",
        "poly_ha": 16628.434568,
        "adj_ha": 16628.434568,
        "adj_flag": None,
        "admin_area": "BC",
        "natpark": None,
        "prescribed": None,
        "version": "20220101",
    },
}

_FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_FEATURE],
    "totalFeatures": 431,
    "numberMatched": 431,
    "numberReturned": 1,
}


async def test_query_fires_parses_records(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            f"&count=20&startIndex=0&propertyName={constants.ATTRIBUTE_FIELDS}"
            f"&srsName={constants.DEFAULT_SRS}"
        ),
        json=_FEATURE_COLLECTION,
    )
    result = await client.query_fires()
    assert result.returned_count == 1
    assert result.total_matched == 431
    fire = result.fires[0]
    assert fire.year == 2021
    assert fire.fire_id == 1233
    assert fire.admin_area == "BC"
    assert fire.adjusted_area_ha == 16628.434568
    assert fire.hotspot_start_date is not None
    assert fire.hotspot_start_date.isoformat() == "2021-07-10"
    assert fire.agency_start_date is None
    assert fire.geometry is None


async def test_query_fires_with_cql_filter_passes_it_through(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            "&count=20&startIndex=0"
            f"&propertyName={constants.ATTRIBUTE_FIELDS}&srsName={constants.DEFAULT_SRS}"
            "&CQL_FILTER=admin_area+%3D+%27BC%27+AND+year+%3E%3D+2017"
        ),
        json={"features": [], "totalFeatures": 0, "numberMatched": 0},
    )
    result = await client.query_fires(cql_filter="admin_area = 'BC' AND year >= 2017")
    assert result.returned_count == 0
    assert result.cql_filter == "admin_area = 'BC' AND year >= 2017"


async def test_query_fires_include_geometry_omits_property_name(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            f"&count=20&startIndex=0&srsName={constants.DEFAULT_SRS}"
        ),
        json=_FEATURE_COLLECTION,
    )
    result = await client.query_fires(include_geometry=True)
    assert result.returned_count == 1


async def test_malformed_cql_filter_raises_invalid_input(httpx_mock):
    """Confirmed live: a malformed CQL_FILTER returns HTTP 400 with an
    OGC ows:ExceptionReport in XML, not JSON, regardless of the
    requested outputFormat."""
    httpx_mock.add_response(
        status_code=400,
        content=(
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">'
            b'<ows:Exception exceptionCode="NoApplicableCode">'
            b"<ows:ExceptionText>Could not parse CQL filter list.</ows:ExceptionText>"
            b"</ows:Exception></ows:ExceptionReport>"
        ),
        headers={"Content-Type": "application/xml"},
    )
    with pytest.raises(InvalidInput, match="Could not parse CQL filter list"):
        await client.query_fires(cql_filter="garbage===")


async def test_invalid_input_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.query_fires(limit=0)
    with pytest.raises(InvalidInput):
        await client.query_fires(offset=-1)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=500, content=b"<html>Internal Server Error</html>")
    with pytest.raises(UpstreamError):
        await client.query_fires()
