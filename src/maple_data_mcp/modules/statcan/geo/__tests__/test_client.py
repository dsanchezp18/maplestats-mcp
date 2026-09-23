from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.geo import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_BASE = f"{constants.BASE_URL}/2021/Cartographic_boundary_files/MapServer"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SERVICES_JSON = {
    "currentVersion": 11.5,
    "folders": [],
    "services": [
        {"name": "2021/Cartographic_boundary_files", "type": "MapServer"},
        {"name": "2021/Digital_boundary_files", "type": "MapServer"},
    ],
}

_LAYER_JSON = {
    "name": "CSD - lcsd000b21s_e",
    "geometryType": "esriGeometryPolygon",
    "maxRecordCount": 6000,
    "spatialReference": {"wkid": 3347, "latestWkid": 3347},
    "fields": [
        {"name": "CSDUID", "type": "esriFieldTypeString", "alias": "CSDUID"},
        {"name": "DGUID", "type": "esriFieldTypeString", "alias": "DGUID"},
        {"name": "CSDNAME", "type": "esriFieldTypeString", "alias": "CSDNAME"},
    ],
}

_QUERY_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": None,
            "properties": {"CSDUID": "3520005", "DGUID": "2021A00053520005", "CSDNAME": "Toronto"},
        }
    ],
    "exceededTransferLimit": False,
}


async def test_list_services_parses_entries(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=_SERVICES_JSON)
    result = await client.list_services("2021")
    assert result.year == "2021"
    assert len(result.services) == 2
    assert result.services[0].name == "2021/Cartographic_boundary_files"
    assert result.services[0].service_type == "MapServer"


async def test_list_services_rejects_invalid_year():
    with pytest.raises(InvalidInput):
        await client.list_services("2021; DROP TABLE")


async def test_get_layer_detail_parses_fields(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}/9?f=json", json=_LAYER_JSON)
    result = await client.get_layer_detail("2021", "Cartographic_boundary_files", 9)
    assert result.name == "CSD - lcsd000b21s_e"
    assert result.geometry_type == "esriGeometryPolygon"
    assert result.max_record_count == 6000
    assert result.spatial_reference_wkid == 3347
    assert len(result.fields) == 3
    assert result.fields[0].name == "CSDUID"


async def test_get_layer_detail_rejects_negative_layer_id():
    with pytest.raises(InvalidInput):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", -1)


async def test_get_layer_detail_rejects_invalid_service():
    with pytest.raises(InvalidInput):
        await client.get_layer_detail("2021", "bad/service", 9)


async def test_query_layer_features_parses_features(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_BASE}/9/query?where=CSDNAME%3D%27Toronto%27&outFields=%2A&f=geojson"
            "&resultRecordCount=100&resultOffset=0&returnGeometry=false"
        ),
        json=_QUERY_GEOJSON,
    )
    result = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 9, where="CSDNAME='Toronto'"
    )
    assert result.returned_count == 1
    assert result.exceeded_transfer_limit is False
    feature = result.features[0]
    assert feature.attributes["CSDNAME"] == "Toronto"
    assert feature.geometry is None


async def test_query_layer_features_with_geometry_includes_out_sr(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_BASE}/9/query?where=1%3D1&outFields=%2A&f=geojson"
            "&resultRecordCount=100&resultOffset=0&returnGeometry=true&outSR=4326"
        ),
        json=_QUERY_GEOJSON,
    )
    result = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 9, return_geometry=True
    )
    assert result.returned_count == 1


async def test_query_layer_features_exceeded_transfer_limit_flag(httpx_mock):
    body = {**_QUERY_GEOJSON, "exceededTransferLimit": True}
    httpx_mock.add_response(
        url=(
            f"{_BASE}/12/query?where=PRUID%3D%2735%27&outFields=%2A&f=geojson"
            "&resultRecordCount=100&resultOffset=0&returnGeometry=false"
        ),
        json=body,
    )
    result = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 12, where="PRUID='35'"
    )
    assert result.exceeded_transfer_limit is True


async def test_query_layer_features_rejects_bad_record_count():
    with pytest.raises(InvalidInput):
        await client.query_layer_features(
            "2021", "Cartographic_boundary_files", 9, result_record_count=0
        )
    with pytest.raises(InvalidInput):
        await client.query_layer_features(
            "2021", "Cartographic_boundary_files", 9, result_record_count=100000
        )


async def test_query_layer_features_rejects_negative_offset():
    with pytest.raises(InvalidInput):
        await client.query_layer_features(
            "2021", "Cartographic_boundary_files", 9, result_offset=-1
        )


async def test_embedded_error_404_becomes_not_found(httpx_mock):
    """Confirmed live: ArcGIS REST errors (unknown folder/service/layer)
    return HTTP 200 with a JSON {"error": {...}} body, not a non-2xx
    status."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/2021/Not_A_Real_Service/MapServer/9?f=json",
        json={"error": {"code": 404, "message": "Service not found", "details": []}},
    )
    with pytest.raises(NotFound):
        await client.get_layer_detail("2021", "Not_A_Real_Service", 9)


async def test_embedded_error_400_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_BASE}/9/query?where=NOTAFIELD%3D%27x%27&outFields=%2A&f=geojson"
            "&resultRecordCount=100&resultOffset=0&returnGeometry=false"
        ),
        json={"error": {"code": 400, "message": "Failed to execute query.", "details": []}},
    )
    with pytest.raises(InvalidInput):
        await client.query_layer_features(
            "2021", "Cartographic_boundary_files", 9, where="NOTAFIELD='x'"
        )


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=500)
    with pytest.raises(UpstreamError):
        await client.list_services("2021")


async def test_list_services_filters_by_language(httpx_mock):
    services = {
        "services": [
            {"name": "2021/Cartographic_boundary_files", "type": "MapServer"},
            {"name": "2021/Fichiers_des_limites_cartographiques", "type": "MapServer"},
            {"name": "2019/lcsd000a19r_e", "type": "MapServer"},
            {"name": "2019/lsdr000a19r_f", "type": "MapServer"},
        ]
    }
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=services)
    french = await client.list_services("2021", "fr")
    assert [s.name for s in french.services] == [
        "2021/Fichiers_des_limites_cartographiques",
        "2019/lsdr000a19r_f",
    ]
    everything = await client.list_services("2021")
    assert [s.language for s in everything.services] == ["en", "fr", "en", "fr"]
