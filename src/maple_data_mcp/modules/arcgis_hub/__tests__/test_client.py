from __future__ import annotations

from typing import get_args

import pytest

from maple_data_mcp.modules.arcgis_hub import client, constants
from maple_data_mcp.modules.arcgis_hub.schemas import PortalKey
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


PORTAL = "ottawa"
_COLLECTION_URL = f"https://{constants.PORTALS[PORTAL].domain}/api/search/v1/collections/dataset"

_SEARCH_FEATURE = {
    "id": "14cca5b087f74d2d9eadc018c261d1b3",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "14cca5b087f74d2d9eadc018c261d1b3",
        "title": "2025 Contracts Awarded greater than 25,000 Jan - Jun",
        "snippet": "Contracts Equal To or Greater Than $25,000 Awarded Under Delegation of Authority.",
        "type": "Feature Service",
        "tags": ["Contracts", "Ottawa"],
        "categories": [],
        "owner": "open.ouvert@ottawa.ca",
        "modified": 1788275291000,
        "numViews": 76,
    },
}

_ITEM_DETAIL_FEATURE = {
    "id": "14cca5b087f74d2d9eadc018c261d1b3_0",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "id": "14cca5b087f74d2d9eadc018c261d1b3",
        "title": "2025 Contracts Awarded greater than 25,000 Jan - Jun",
        "description": "Contracts Equal To or Greater Than $25,000 Awarded Under Delegation of Authority.",
        "type": "Feature Service",
        "tags": ["Contracts", "Ottawa"],
        "categories": [],
        "owner": "open.ouvert@ottawa.ca",
        "licenseInfo": "<p><a href='https://ottawa.ca/en/city-hall/open-data'>Ottawa Open Data</a></p>",
        "created": 1788191722000,
        "modified": 1788275291000,
        "numViews": 76,
        "spatialReference": "102100",
        "url": "https://services.arcgis.com/G6F8XLCl5KtAlZ2G/arcgis/rest/services/2025_Contracts_Awarded_greater_than_25000_Jan_-_Jun/FeatureServer",
    },
}


async def test_search_parses_hub_search_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=10&startindex=1&q=test",
        json={"features": [_SEARCH_FEATURE], "numberMatched": 36, "numberReturned": 1},
    )
    result = await client.search_datasets(PORTAL, "test")
    assert result.total_count == 36
    assert result.items[0].id == "14cca5b087f74d2d9eadc018c261d1b3"
    assert result.items[0].item_type == "Feature Service"
    assert result.items[0].landing_page_url.endswith("/datasets/14cca5b087f74d2d9eadc018c261d1b3")


async def test_search_offset_converts_to_one_based_startindex(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items?limit=5&startindex=11&tags=Open+Data&type=Feature+Service",
        json={"features": [], "numberMatched": 0, "numberReturned": 0},
    )
    result = await client.search_datasets(
        PORTAL, tag="Open Data", item_type="Feature Service", limit=5, offset=10
    )
    assert result.returned_count == 0


async def test_get_dataset_maps_item_detail_and_download_links(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/14cca5b087f74d2d9eadc018c261d1b3",
        json=_ITEM_DETAIL_FEATURE,
    )
    result = await client.get_dataset(PORTAL, "14cca5b087f74d2d9eadc018c261d1b3")
    assert result.id == "14cca5b087f74d2d9eadc018c261d1b3"
    assert result.service_url is not None
    assert result.service_url.endswith(("FeatureServer", "MapServer/129"))
    assert {link.format for link in result.download_urls} == {"csv", "shapefile", "geojson", "kml"}
    assert result.created_at is not None


async def test_query_feature_layer_returns_attributes(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/14cca5b087f74d2d9eadc018c261d1b3",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services.arcgis.com/G6F8XLCl5KtAlZ2G/arcgis/rest/services/2025_Contracts_Awarded_greater_than_25000_Jan_-_Jun/FeatureServer"
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
    result = await client.query_feature_layer(PORTAL, "14cca5b087f74d2d9eadc018c261d1b3")
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
        await client.query_feature_layer(PORTAL, "abc123")


async def test_feature_service_embedded_error_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/14cca5b087f74d2d9eadc018c261d1b3",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services.arcgis.com/G6F8XLCl5KtAlZ2G/arcgis/rest/services/2025_Contracts_Awarded_greater_than_25000_Jan_-_Jun/FeatureServer"
    httpx_mock.add_response(url=f"{service_url}?f=json", json={"layers": [{"id": 0}], "tables": []})
    httpx_mock.add_response(
        url=(
            f"{service_url}/0/query?where=garbage%3D%3D&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"error": {"code": 400, "message": "Invalid query.", "details": ["bad where"]}},
    )
    with pytest.raises(InvalidInput):
        await client.query_feature_layer(
            PORTAL, "14cca5b087f74d2d9eadc018c261d1b3", where="garbage=="
        )


async def test_default_layer_index_falls_back_to_table_id(httpx_mock):
    """A hosted table (no geometry) can sit at a non-zero id.

    Confirmed live against a Prince Edward Island item whose service
    reports an empty `layers` list and its one queryable table at id
    2 -- `layer_index=None` must resolve to that id, not assume 0.
    """
    httpx_mock.add_response(
        url=f"{_COLLECTION_URL}/items/14cca5b087f74d2d9eadc018c261d1b3",
        json=_ITEM_DETAIL_FEATURE,
    )
    service_url = "https://services.arcgis.com/G6F8XLCl5KtAlZ2G/arcgis/rest/services/2025_Contracts_Awarded_greater_than_25000_Jan_-_Jun/FeatureServer"
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
    result = await client.query_feature_layer(PORTAL, "14cca5b087f74d2d9eadc018c261d1b3")
    assert result.layer_index == 2


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets(PORTAL, "x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(PORTAL, " ")
    with pytest.raises(InvalidInput):
        await client.query_feature_layer(PORTAL, "abcd", limit=0)

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
        await client.get_dataset(PORTAL, "unknown")


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
        await client.search_datasets(PORTAL, limit=100)


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
        await client.get_dataset(PORTAL, "broken")


def test_portal_key_literal_matches_registry():
    assert set(get_args(PortalKey)) == set(constants.PORTALS)
    assert len(constants.PORTALS) == 28


async def test_unknown_portal_raises_invalid_input():
    with pytest.raises(InvalidInput):
        await client.search_datasets("atlantis")


def test_list_portals_localizes_names():
    en = client.list_portals("en")
    fr = client.list_portals("fr")
    assert len(en.portals) == len(constants.PORTALS)
    ottawa_fr = next(p for p in fr.portals if p.portal == "ottawa")
    assert ottawa_fr.name == "Données ouvertes de la Ville d'Ottawa"


@pytest.mark.parametrize("portal", sorted(constants.PORTALS))
async def test_every_portal_searches_its_own_domain(httpx_mock, portal):
    domain = constants.PORTALS[portal].domain
    httpx_mock.add_response(
        url=f"https://{domain}/api/search/v1/collections/dataset/items?limit=10&startindex=1",
        json={"features": [_SEARCH_FEATURE], "numberMatched": 1},
    )
    result = await client.search_datasets(portal)
    assert result.portal == portal
    assert result.provenance.source == constants.rate_limit_source(portal)
    assert result.items[0].landing_page_url.startswith(f"https://{domain}/datasets/")


async def test_default_layer_index_uses_service_urls_own_trailing_layer_id(httpx_mock):
    """Durham's catalogue items point at one specific layer of one large,
    200+-layer shared MapServer (Durham_OpenData) rather than at a
    single-purpose service. Confirmed live 2026-09-19: the item's
    `properties.url` already ends in `/129`, and layer 0 of that same
    service is an unrelated dataset. No `?f=json` mock is registered on
    purpose: if `default_layer_index` ever regresses to listing the root
    again, this test fails on an unmatched request instead of silently
    querying the wrong layer.
    """
    domain = constants.PORTALS["durham"].domain
    layer_url = (
        "https://maps.durham.ca/arcgis/rest/services/Open_Data/Durham_OpenData/MapServer/129"
    )
    item = {
        "id": "f56de642442e4b41985557b54254a70c_129",
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id": "f56de642442e4b41985557b54254a70c",
            "title": "Forcemain",
            "type": "Feature Service",
            "url": layer_url,
        },
    }
    httpx_mock.add_response(
        url=f"https://{domain}/api/search/v1/collections/dataset/items/f56de642442e4b41985557b54254a70c",
        json=item,
    )
    base = layer_url.rsplit("/", 1)[0]
    httpx_mock.add_response(
        url=(
            f"{base}/129/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={
            "features": [{"attributes": {"ObjectId": 1, "AssetType": "Forcemain"}}],
            "exceededTransferLimit": False,
        },
    )
    result = await client.query_feature_layer("durham", "f56de642442e4b41985557b54254a70c")
    assert result.layer_index == 129
    assert result.rows[0]["AssetType"] == "Forcemain"
