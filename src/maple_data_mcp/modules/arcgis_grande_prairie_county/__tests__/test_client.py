from __future__ import annotations

import pytest

from maple_data_mcp.modules.arcgis_grande_prairie_county import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_COLLECTION_URL = f"https://{constants.DOMAIN}/api/search/v1/collections/dataset"

_QUERY_URL = (
    "https://opendataservices.countygp.ab.ca/arcgis/rest/services/boundaries/FeatureServer/0"
)

_SEARCH_FEATURE = {
    "id": "e7668c0d4e3c4fc8a1b2d5a47266ee59",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "e7668c0d4e3c4fc8a1b2d5a47266ee59",
        "title": "Councillor Electoral Districts",
        "snippet": "Councillor electoral district boundaries for the County of Grande Prairie.",
        "type": "Feature Service",
        "tags": ["boundaries", "Grande Prairie County"],
        "categories": [],
        "owner": "countygp",
        "modified": 1772037813000,
        "numViews": 120,
    },
}

_ITEM_DETAIL_FEATURE = {
    "id": "e7668c0d4e3c4fc8a1b2d5a47266ee59_0",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "e7668c0d4e3c4fc8a1b2d5a47266ee59",
        "title": "Councillor Electoral Districts",
        "description": "Councillor electoral district boundaries for the County of Grande Prairie.",
        "type": "Feature Service",
        "tags": ["boundaries", "Grande Prairie County"],
        "categories": [],
        "owner": "countygp",
        "licenseInfo": "",
        "created": 1772037813000,
        "modified": 1772037813000,
        "numViews": 120,
        "spatialReference": "102100",
        "url": "https://opendataservices.countygp.ab.ca/arcgis/rest/services/boundaries/FeatureServer/0",
    },
}


async def test_search_parses_hub_search_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=10&startindex=1&q=test",
        json={"features": [_SEARCH_FEATURE], "numberMatched": 36, "numberReturned": 1},
    )
    result = await client.search_datasets("test")
    assert result.total_count == 36
    assert result.items[0].id == "e7668c0d4e3c4fc8a1b2d5a47266ee59"
    assert result.items[0].item_type == "Feature Service"
    assert result.items[0].landing_page_url.endswith("/datasets/e7668c0d4e3c4fc8a1b2d5a47266ee59")


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
        url=f"{_COLLECTION_URL}/items/e7668c0d4e3c4fc8a1b2d5a47266ee59",
        json=_ITEM_DETAIL_FEATURE,
    )
    result = await client.get_dataset("e7668c0d4e3c4fc8a1b2d5a47266ee59")
    assert result.id == "e7668c0d4e3c4fc8a1b2d5a47266ee59"
    assert result.service_url is not None
    assert {link.format for link in result.download_urls} == {"csv", "shapefile", "geojson", "kml"}
    assert result.created_at is not None


async def test_query_feature_layer_returns_attributes(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/e7668c0d4e3c4fc8a1b2d5a47266ee59",
        json=_ITEM_DETAIL_FEATURE,
    )
    httpx_mock.add_response(
        url=(
            f"{_QUERY_URL}/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={
            "features": [{"attributes": {"ObjectId": 1}}],
            "exceededTransferLimit": False,
        },
    )
    result = await client.query_feature_layer("e7668c0d4e3c4fc8a1b2d5a47266ee59")
    assert result.returned_count == 1
    assert result.rows[0]["ObjectId"] == 1
    assert result.exceeded_transfer_limit is False
    assert result.layer_index == 0


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
        url=f"{_COLLECTION_URL}/items/e7668c0d4e3c4fc8a1b2d5a47266ee59",
        json=_ITEM_DETAIL_FEATURE,
    )
    httpx_mock.add_response(
        url=(
            f"{_QUERY_URL}/query?where=garbage%3D%3D&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"error": {"code": 400, "message": "Invalid query.", "details": ["bad where"]}},
    )
    with pytest.raises(InvalidInput):
        await client.query_feature_layer("e7668c0d4e3c4fc8a1b2d5a47266ee59", where="garbage==")


async def test_default_layer_index_falls_back_to_table_id(httpx_mock):
    """A hosted table (no geometry) can sit at a non-zero id.

    Confirmed live against a Prince Edward Island item whose service
    reports an empty `layers` list and its one queryable table at id
    2 -- `layer_index=None` must resolve to that id, not assume 0. Uses
    a separate synthetic item (rather than this portal's own, whose
    service url already ends in a digit and so exercises the different
    trailing-layer-id path tested above).
    """
    other_item = {
        "id": "other-item_0",
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id": "other-item",
            "title": "Some other table-backed dataset",
            "type": "Table",
            "tags": [],
            "categories": [],
            "url": "https://services.arcgis.com/example/arcgis/rest/services/SomeTable/FeatureServer",
        },
    }
    httpx_mock.add_response(url=f"{_COLLECTION_URL}/items/other-item", json=other_item)
    service_url = "https://services.arcgis.com/example/arcgis/rest/services/SomeTable/FeatureServer"
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
    result = await client.query_feature_layer("other-item")
    assert result.layer_index == 2


async def test_default_layer_index_uses_service_urls_own_trailing_layer_id(httpx_mock):
    """This portal's catalogue item already names a specific layer in its
    `properties.url` (ending in `/0`). No `?f=json` mock is
    registered on purpose: if `default_layer_index` ever regresses to
    listing the service root instead of using the url's own trailing
    digit, this test fails on an unmatched request rather than silently
    resolving a different layer.
    """
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/e7668c0d4e3c4fc8a1b2d5a47266ee59",
        json=_ITEM_DETAIL_FEATURE,
    )
    httpx_mock.add_response(
        url=(
            f"{_QUERY_URL}/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={
            "features": [{"attributes": {"ObjectId": 1}}],
            "exceededTransferLimit": False,
        },
    )
    result = await client.query_feature_layer("e7668c0d4e3c4fc8a1b2d5a47266ee59")
    assert result.layer_index == 0


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
