from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.geo import client, constants
from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

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


async def test_get_layer_detail_tolerates_null_fields(httpx_mock):
    # A present-but-null list must coalesce to [] (AGENTS.md, list_or_empty).
    httpx_mock.add_response(url=f"{_BASE}/9?f=json", json={**_LAYER_JSON, "fields": None})
    result = await client.get_layer_detail("2021", "Cartographic_boundary_files", 9)
    assert result.fields == []


async def test_query_layer_features_tolerates_null_features(httpx_mock):
    httpx_mock.add_response(json={**_QUERY_GEOJSON, "features": None})
    result = await client.query_layer_features("2021", "Cartographic_boundary_files", 9)
    assert result.features == []


async def test_errors_are_explained_in_french():
    use_lang("fr")
    with pytest.raises(InvalidInput, match="layer_id doit être >= 0, reçu -1"):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", -1)
    with pytest.raises(InvalidInput, match="pas les deux"):
        client.spatial_query_params(43.65, -79.38, "-79.4,43.6,-79.3,43.7", None)
    use_lang("en")
    with pytest.raises(InvalidInput, match="layer_id must be >= 0, got -1"):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", -1)


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


_SERVICE_JSON = {"layers": [{"id": 9, "name": "CSD - lcsd000b21s_e"}]}
_BOGUS_BASE = f"{constants.BASE_URL}/2021/Not_A_Real_Service/MapServer"


async def test_500_for_unlisted_service_becomes_not_found(httpx_mock):
    # Live 2026-09-27: an unknown service now answers HTTP 500, not an
    # embedded 404, so the listing decides whether the caller is wrong.
    httpx_mock.add_response(url=f"{_BOGUS_BASE}/9?f=json", status_code=500, is_reusable=True)
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=_SERVICES_JSON)
    with pytest.raises(NotFound, match="Not_A_Real_Service"):
        await client.get_layer_detail("2021", "Not_A_Real_Service", 9)


async def test_500_for_unlisted_layer_becomes_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}/999?f=json", status_code=500, is_reusable=True)
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=_SERVICES_JSON)
    httpx_mock.add_response(url=f"{_BASE}?f=json", json=_SERVICE_JSON)
    with pytest.raises(NotFound, match="no layer 999"):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", 999)


async def test_500_for_listed_layer_stays_upstream_error(httpx_mock):
    # The service and layer exist, so the 500 is a real outage.
    httpx_mock.add_response(url=f"{_BASE}/9?f=json", status_code=500, is_reusable=True)
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=_SERVICES_JSON)
    httpx_mock.add_response(url=f"{_BASE}?f=json", json=_SERVICE_JSON)
    with pytest.raises(UpstreamError, match="get_layer_detail"):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", 9)


async def test_500_with_listings_down_keeps_original_error(httpx_mock):
    httpx_mock.add_response(status_code=500, is_reusable=True)
    with pytest.raises(UpstreamError, match="get_layer_detail"):
        await client.get_layer_detail("2021", "Cartographic_boundary_files", 9)


async def test_query_500_for_unlisted_service_becomes_not_found(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_BOGUS_BASE}/9/query?where=1%3D1&outFields=%2A&f=geojson"
            "&resultRecordCount=100&resultOffset=0&returnGeometry=false"
        ),
        status_code=500,
        is_reusable=True,
    )
    httpx_mock.add_response(url=f"{constants.BASE_URL}/2021?f=json", json=_SERVICES_JSON)
    with pytest.raises(NotFound):
        await client.query_layer_features("2021", "Not_A_Real_Service", 9)


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


async def test_every_request_opens_a_fresh_connection(httpx_mock):
    # One broken backend pinned per connection made all retries fail together
    # (live 2026-09-26); Connection: close spreads them across backends.
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/2021?f=json",
        match_headers={"Connection": "close"},
        json=_SERVICES_JSON,
    )
    await client.list_services("2021")


# --- spatial filter on the census-boundary query ------------------------------


def test_spatial_query_params_point_bbox_and_none():
    params, spatial = client.spatial_query_params(43.65, -79.38, None, None)
    assert params is not None and spatial is not None
    # x (longitude) comes first in an ArcGIS point.
    assert params["geometry"] == "-79.38,43.65"
    assert params["geometryType"] == "esriGeometryPoint"
    assert params["inSR"] == 4326
    assert spatial.kind == "point"
    params, spatial = client.spatial_query_params(43.65, -79.38, None, 300)
    assert params is not None and params["distance"] == 300
    assert params["units"] == "esriSRUnit_Meter"
    params, spatial = client.spatial_query_params(None, None, "-79.4,43.6,-79.3,43.7", None)
    assert params is not None and spatial is not None
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert spatial.bbox == [-79.4, 43.6, -79.3, 43.7]
    assert client.spatial_query_params(None, None, None, None) == (None, None)


@pytest.mark.parametrize(
    "args",
    [
        (43.65, None, None, None),
        (None, -79.38, None, None),
        (43.65, -79.38, "-79.4,43.6,-79.3,43.7", None),
        (None, None, None, 100.0),
        (143.65, -79.38, None, None),
        (43.65, -79.38, None, 0.0),
        (43.65, -79.38, None, 10_000_000.0),
        (None, None, "not,a,box", None),
        (None, None, "-79.3,43.6,-79.4,43.7", None),
    ],
)
def test_spatial_query_params_rejects_bad_input(args):
    with pytest.raises(InvalidInput):
        client.spatial_query_params(*args)


async def test_query_layer_features_sends_point_filter(httpx_mock):
    httpx_mock.add_response(json=_QUERY_GEOJSON)
    result = await client.query_layer_features(
        "2021", "Cartographic_boundary_files", 12, lat=43.65, lon=-79.38, out_fields="DAUID"
    )
    sent = httpx_mock.get_requests()[0].url.params
    assert sent["geometry"] == "-79.38,43.65"
    assert sent["geometryType"] == "esriGeometryPoint"
    assert sent["inSR"] == "4326"
    assert sent["outFields"] == "DAUID"
    assert result.spatial_filter is not None and result.spatial_filter.kind == "point"


# --- geoanalytics MapServers and the National Road Network --------------------

_PROXY = (
    "https://geoanalytics.cloud.statcan.ca/portal/sharing/servers/"
    "90580fcf99974daca12da731967ba58d/rest/services/Geomatics_Services/infc_v2_prod/MapServer"
)
_CONFIG = {
    "mapserver": [
        {"id": "hna_ms", "url": _PROXY.replace("infc_v2_prod", "hna_prod")},
        {"id": "infc_ms", "url": _PROXY},
        {"id": "qol_ms", "url": _PROXY.replace("infc_v2_prod", "qol_prod_2")},
    ],
    "placename": "https://example.invalid/ignored",
}
# Shape confirmed live 2026-10-02: group layers carry subLayerIds, children
# carry parentLayerId, and a top-level layer has parentLayerId -1.
_INFC_SERVICE = {
    "capabilities": "Map,Query,Data",
    "maxRecordCount": 50000,
    "layers": [
        {
            "id": 3,
            "name": "Canadian Index of Multiple Deprivation 2021",
            "parentLayerId": -1,
            "subLayerIds": None,
            "geometryType": "esriGeometryPolygon",
        },
        {
            "id": 14,
            "name": "LODE Infrastructure",
            "parentLayerId": -1,
            "subLayerIds": [15],
            "geometryType": None,
        },
        {
            "id": 15,
            "name": "public_transit_stops",
            "parentLayerId": 14,
            "subLayerIds": None,
            "geometryType": "esriGeometryPoint",
        },
    ],
}
_NRN = constants.NRN_SERVICE_URL
_NRN_SERVICE = {
    "maxRecordCount": 2000,
    "layers": [
        {
            "id": 75,
            "name": "Local roads / Routes locales",
            "parentLayerId": 32,
            "subLayerIds": [84, 85],
        },
        {
            "id": 84,
            "name": "ON - Local roads / Routes locales",
            "parentLayerId": 75,
            "subLayerIds": None,
            "geometryType": "esriGeometryPolyline",
        },
        {
            "id": 85,
            "name": "PE - Local roads / Routes locales",
            "parentLayerId": 75,
            "subLayerIds": None,
            "geometryType": "esriGeometryPolyline",
        },
        {
            "id": 16,
            "name": "ON - Toll point / Poste de péage",
            "parentLayerId": 11,
            "subLayerIds": None,
            "geometryType": "esriGeometryPoint",
        },
    ],
}


def _mock_config(httpx_mock, config=None):
    httpx_mock.add_response(url=f"{constants.ANALYTICS_CONFIG_URL}?f=json", json=config or _CONFIG)


async def test_analytics_url_is_read_from_config_at_runtime(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    result = await client.list_spatial_layers("infc")
    assert result.service_url == _PROXY
    assert result.max_record_count == 50000
    by_id = {layer.layer_id: layer for layer in result.layers}
    assert by_id[14].is_group and not by_id[15].is_group
    assert by_id[15].parent_layer_id == 14 and by_id[3].parent_layer_id is None
    assert "undocumented" in (result.provenance.limits or "").lower()


async def test_changed_config_raises_clear_error(httpx_mock):
    # The proxy ids are undocumented; a config without the entry must fail
    # loudly rather than query a guessed address.
    _mock_config(httpx_mock, {"mapserver": [{"id": "hna_ms", "url": _PROXY}]})
    with pytest.raises(UpstreamError, match="no longer lists"):
        await client.list_spatial_layers("infc")


async def test_config_pointing_off_host_is_refused(httpx_mock):
    off = {
        "mapserver": [{"id": "infc_ms", "url": "https://other.example/rest/services/x/MapServer"}]
    }
    _mock_config(httpx_mock, off)
    with pytest.raises(UpstreamError, match="no longer lists"):
        await client.list_spatial_layers("infc")


async def test_service_without_layers_raises(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json={"layers": None})
    with pytest.raises(UpstreamError, match="layer list"):
        await client.list_spatial_layers("infc")


async def test_query_point_in_da_layer(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    httpx_mock.add_response(
        json={
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None, "properties": {"dauid": "1"}}],
        }
    )
    result = await client.query_spatial_layer("infc", 3, lat=43.65, lon=-79.38, out_fields="dauid")
    assert result.returned_count == 1
    assert result.layer_name == "Canadian Index of Multiple Deprivation 2021"
    request = httpx_mock.get_requests()[-1]
    assert request.url.path.endswith("/3/query")
    assert request.url.params["geometry"] == "-79.38,43.65"
    assert request.url.params["f"] == "geojson"
    assert result.spatial_filter is not None and result.spatial_filter.lat == 43.65


async def test_query_group_layer_is_invalid_input(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    with pytest.raises(InvalidInput, match="group"):
        await client.query_spatial_layer("infc", 14)


async def test_query_unknown_layer_is_not_found(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    with pytest.raises(NotFound, match="no layer 99"):
        await client.get_spatial_layer_detail("infc", 99)


async def test_unknown_dataset_is_invalid_input():
    with pytest.raises(InvalidInput, match="dataset"):
        await client.list_spatial_layers("bogus")


async def test_spatial_layer_detail_reads_fields(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    httpx_mock.add_response(
        url=f"{_PROXY}/3?f=json",
        json={
            "name": "Canadian Index of Multiple Deprivation 2021",
            "geometryType": "esriGeometryPolygon",
            "maxRecordCount": 50000,
            "extent": {"spatialReference": {"wkid": 102100, "latestWkid": 3857}},
            "fields": [{"name": "dauid", "type": "esriFieldTypeString", "alias": "dauid"}],
        },
    )
    detail = await client.get_spatial_layer_detail("infc", 3)
    assert detail.max_record_count == 50000
    assert detail.spatial_reference_wkid == 102100
    assert [f.name for f in detail.fields] == ["dauid"]


async def test_nrn_list_filters_by_province_and_class(httpx_mock):
    httpx_mock.add_response(url=f"{_NRN}?f=json", json=_NRN_SERVICE)
    result = await client.list_spatial_layers("nrn", province="on", road_class="local")
    assert [(layer.layer_id, layer.province) for layer in result.layers] == [(84, "ON")]
    assert result.layers[0].road_class == "Local roads"
    assert "Open Licence" in (result.provenance.limits or "")


async def test_province_filter_is_nrn_only(httpx_mock):
    _mock_config(httpx_mock)
    httpx_mock.add_response(url=f"{_PROXY}?f=json", json=_INFC_SERVICE)
    with pytest.raises(InvalidInput, match="nrn"):
        await client.list_spatial_layers("infc", province="ON")


async def test_resolve_nrn_layer_and_missing_class(httpx_mock):
    httpx_mock.add_response(url=f"{_NRN}?f=json", json=_NRN_SERVICE)
    assert await client.resolve_nrn_layer("ON", "Local roads") == 84
    with pytest.raises(NotFound, match="No NRN layer"):
        await client.resolve_nrn_layer("PE", "Toll point")


async def test_nrn_query_retries_a_500_then_succeeds(httpx_mock):
    # Live: geo.statcan.gc.ca answers HTTP 500 on some valid requests.
    httpx_mock.add_response(url=f"{_NRN}?f=json", json=_NRN_SERVICE)
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(json=_QUERY_GEOJSON)
    result = await client.query_spatial_layer("nrn", 84, bbox="-79.4,43.6,-79.3,43.7")
    assert result.returned_count == 1
    assert result.provenance.source == constants.RATE_LIMIT_SOURCE
    last = httpx_mock.get_requests()[-1]
    assert last.url.params["geometryType"] == "esriGeometryEnvelope"
