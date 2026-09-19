"""Fixtures below are shaped after live responses confirmed 2026-09-19
against data.edmonton.ca (dataset 24uj-dj8v, "General Building Permits")."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.socrata_edmonton import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound

_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SEARCH_RESULT = {
    "resource": {
        "id": "24uj-dj8v",
        "name": "General Building Permits",
        "description": "Building permits issued by the City of Edmonton.",
        "lens_view_type": "tabular",
        "updatedAt": "2026-09-19T11:00:00.000Z",
        "download_count": 12045,
    },
    "classification": {
        "domain_category": "Urban Planning and Landuse",
        "domain_tags": ["permits", "building"],
    },
    "permalink": "https://data.edmonton.ca/d/24uj-dj8v",
    "link": "https://data.edmonton.ca/Urban-Planning-and-Landuse/General-Building-Permits/24uj-dj8v",
}

_VIEW = {
    "id": "24uj-dj8v",
    "name": "General Building Permits",
    "description": "Building permits issued by the City of Edmonton.",
    "category": "Urban Planning and Landuse",
    "attribution": "City of Edmonton",
    "license": {"name": "See Terms of Use", "termsLink": "https://data.edmonton.ca/terms"},
    "tags": ["permits", "building"],
    "columns": [
        {"name": "ROW ID", "fieldName": "row_id", "dataTypeName": "text", "description": ""},
    ],
    "createdAt": 1500000000,
    "rowsUpdatedAt": 1788607873,
    "publicationDate": 1500000000,
    "downloadCount": 12045,
    "viewCount": 150000,
}


async def test_search_parses_socrata_catalog_fields(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}?domains={constants.DOMAIN}&search_context={constants.DOMAIN}"
            "&only=datasets&limit=10&offset=0&q=building+permit"
        ),
        json={"results": [_SEARCH_RESULT], "resultSetSize": 1},
    )
    result = await client.search_datasets("building permit")
    assert result.total_count == 1
    assert result.datasets[0].id == "24uj-dj8v"
    assert result.datasets[0].category == "Urban Planning and Landuse"
    assert result.datasets[0].landing_page_url.endswith("General-Building-Permits/24uj-dj8v")


async def test_get_dataset_maps_view_metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/24uj-dj8v.json",
        json=_VIEW,
    )
    result = await client.get_dataset("24uj-dj8v")
    assert result.license_name == "See Terms of Use"
    assert result.columns[0].field_name == "row_id"
    assert result.rows_updated_at is not None
    assert result.csv_download_url.endswith("/rows.csv?accessType=DOWNLOAD")


async def test_query_dataset_rows_passes_soql_params(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"https://{constants.DOMAIN}/resource/24uj-dj8v.json"
            "?%24select=permit_number&%24where=year%3D2026&%24limit=5&%24offset=0"
        ),
        json=[{"permit_number": "BP123456"}],
    )
    result = await client.query_dataset_rows(
        "24uj-dj8v", select="permit_number", where="year=2026", limit=5
    )
    assert result.returned_count == 1
    assert result.rows[0]["permit_number"] == "BP123456"


async def test_list_categories_and_tags(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_categories?domains={constants.DOMAIN}",
        json={"results": [{"domain_category": "Surveys", "count": 463}]},
    )
    categories = await client.list_categories()
    assert categories.categories[0].dataset_count == 463

    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_tags?domains={constants.DOMAIN}",
        json={"results": [{"domain_tag": "speed check sign", "count": 326}]},
    )
    tags = await client.list_tags()
    assert tags.tags[0].tag == "speed check sign"


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")
    with pytest.raises(InvalidInput):
        await client.query_dataset_rows("abcd-1234", limit=0)

    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/unknown.json",
        status_code=404,
        json={"code": "dataset.missing", "error": True, "message": "Not found", "data": {}},
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")
