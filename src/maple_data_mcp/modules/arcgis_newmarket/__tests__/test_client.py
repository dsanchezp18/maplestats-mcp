from __future__ import annotations

import pytest

from maple_data_mcp.modules.arcgis_newmarket import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_COLLECTION_URL = f"https://{constants.DOMAIN}/api/search/v1/collections/dataset"

_SEARCH_FEATURE = {
    "id": "8d259d7129b94f8ba227e1878f795103",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "8d259d7129b94f8ba227e1878f795103",
        "title": "OPENNewmarket Trail Points",
        "snippet": "To visualize the details of and amenities for the Town of Newmarket trails.",
        "type": "Feature Service",
        "tags": ["Trail", "Access Point", "Newmarket"],
        "categories": [],
        "owner": "TownOfNewmarket",
        "modified": 1765747460000,
        "numViews": 3355,
    },
}

_ITEM_DETAIL_FEATURE = {
    "id": "8d259d7129b94f8ba227e1878f795103_0",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "8d259d7129b94f8ba227e1878f795103",
        "title": "OPENNewmarket Trail Points",
        "description": "To visualize the details of and amenities for the Town of Newmarket trails.",
        "type": "Feature Service",
        "tags": ["Trail", "Access Point", "Newmarket"],
        "categories": [],
        "owner": "TownOfNewmarket",
        "licenseInfo": "<p>Town of Newmarket Open Data Licence.</p>",
        "created": 1668025377000,
        "modified": 1765747460000,
        "numViews": 3355,
        "spatialReference": "102100",
        "url": "https://services3.arcgis.com/tSwsWwbYRimLwcCZ/arcgis/rest/services/Trail_Points_4_view/FeatureServer",
    },
}


async def test_search_parses_hub_search_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=10&startindex=1&q=test",
        json={"features": [_SEARCH_FEATURE], "numberMatched": 36, "numberReturned": 1},
    )
    result = await client.search_datasets("test")
    assert result.total_count == 36
    assert result.items[0].id == "8d259d7129b94f8ba227e1878f795103"
    assert result.items[0].item_type == "Feature Service"
    assert result.items[0].landing_page_url.endswith("/datasets/8d259d7129b94f8ba227e1878f795103")


async def test_search_offset_converts_to_one_based_startindex(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=5&startindex=11&tags=Open+Data&type=Feature+Service",
        json={"features": [], "numberMatched": 0, "numberReturned": 0},
    )
    result = await client.search_datasets(
        tag="Open Data", item_type="Feature Service", limit=5, offset=10
    )
    assert result.returned_count == 0


async def test_get_dataset_maps_item_detail_and_download_links(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/8d259d7129b94f8ba227e1878f795103",
        json=_ITEM_DETAIL_FEATURE,
    )
    result = await client.get_dataset("8d259d7129b94f8ba227e1878f795103")
    assert result.id == "8d259d7129b94f8ba227e1878f795103"
    assert result.service_url is not None
    assert result.service_url.endswith(("FeatureServer", "MapServer/129"))
    assert {link.format for link in result.download_urls} == {"csv", "shapefile", "geojson", "kml"}
    assert result.created_at is not None


async def test_query_feature_layer_returns_attributes(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/8d259d7129b94f8ba227e1878f795103",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services3.arcgis.com/tSwsWwbYRimLwcCZ/arcgis/rest/services/Trail_Points_4_view/FeatureServer"
    httpx_mock.add_response(url=f"{service_url}?f=json", json={"layers": [{"id": 0}], "tables": []})
    httpx_mock.add_response(
        url=(
            f"{service_url}/0/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={
            "features": [{"attributes": {"ObjectId": 1}}],
            "exceededTransferLimit": False,
        },
    )
    result = await client.query_feature_layer("8d259d7129b94f8ba227e1878f795103")
    assert result.returned_count == 1
    assert result.rows[0]["ObjectId"] == 1
    assert result.exceeded_transfer_limit is False


async def test_query_feature_layer_without_service_url_raises_invalid_input(httpx_mock):
    csv_item = {
        "id": "abc123_0",
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id": "abc123",
            "title": "A plain CSV dataset",
            "type": "CSV",
            "tags": [],
            "categories": [],
        },
    }
    httpx_mock.add_response(url=f"{_COLLECTION_URL}/items/abc123", json=csv_item)
    with pytest.raises(InvalidInput):
        await client.query_feature_layer("abc123")


async def test_feature_service_embedded_error_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/8d259d7129b94f8ba227e1878f795103",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services3.arcgis.com/tSwsWwbYRimLwcCZ/arcgis/rest/services/Trail_Points_4_view/FeatureServer"
    httpx_mock.add_response(url=f"{service_url}?f=json", json={"layers": [{"id": 0}], "tables": []})
    httpx_mock.add_response(
        url=(
            f"{service_url}/0/query?where=garbage%3D%3D&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"error": {"code": 400, "message": "Invalid query.", "details": ["bad where"]}},
    )
    with pytest.raises(InvalidInput):
        await client.query_feature_layer("8d259d7129b94f8ba227e1878f795103", where="garbage==")


async def test_default_layer_index_falls_back_to_table_id(httpx_mock):
    """A hosted table (no geometry) can sit at a non-zero id.

    Confirmed live against a Prince Edward Island item whose service
    reports an empty `layers` list and its one queryable table at id
    2 -- `layer_index=None` must resolve to that id, not assume 0.
    """
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/8d259d7129b94f8ba227e1878f795103",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services3.arcgis.com/tSwsWwbYRimLwcCZ/arcgis/rest/services/Trail_Points_4_view/FeatureServer"
    httpx_mock.add_response(
        url=f"{service_url}?f=json",
        json={"layers": [], "tables": [{"id": 2, "name": "Some_Table"}]},
    )
    httpx_mock.add_response(
        url=(
            f"{service_url}/2/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [{"attributes": {"ObjectId": 1}}], "exceededTransferLimit": False},
    )
    result = await client.query_feature_layer("8d259d7129b94f8ba227e1878f795103")
    assert result.layer_index == 2


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")
    with pytest.raises(InvalidInput):
        await client.query_feature_layer("abcd", limit=0)

    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/unknown",
        status_code=404,
        json={
            "message": "Cannot find item with recordId unknown in collection Data",
            "error": "Not Found",
            "statusCode": 404,
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")


async def test_over_limit_search_raises_invalid_input_with_list_message(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=100&startindex=1",
        status_code=400,
        json={
            "message": ["searchOptions.limit must not be greater than 20000"],
            "error": "Bad Request",
            "statusCode": 400,
        },
    )
    with pytest.raises(InvalidInput):
        await client.search_datasets(limit=100)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    # 500 is retried up to 3 attempts by shared/http.py before this client
    # sees the final failure, so the mock needs a response for each attempt.
    for _ in range(3):
        httpx_mock.add_response(
            url=f"{_COLLECTION_URL}/items/broken",
            status_code=500,
            json={"message": "internal error", "error": "Internal Server Error", "statusCode": 500},
        )
    with pytest.raises(UpstreamError):
        await client.get_dataset("broken")
