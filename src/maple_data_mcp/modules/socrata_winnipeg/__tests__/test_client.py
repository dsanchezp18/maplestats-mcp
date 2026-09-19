"""Fixtures below are shaped after live responses confirmed 2026-09-19
against data.winnipeg.ca (dataset d4mq-wa44, "Assessment Parcels")."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.socrata_winnipeg import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound

_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SEARCH_RESULT = {
    "resource": {
        "id": "d4mq-wa44",
        "name": "Assessment Parcels",
        "description": "Property assessment parcels within the City of Winnipeg.",
        "lens_view_type": "tabular",
        "updatedAt": "2026-09-19T11:00:00.000Z",
        "download_count": 3120,
    },
    "classification": {
        "domain_category": "Assessment and Taxation",
        "domain_tags": ["assessment", "property"],
    },
    "permalink": "https://data.winnipeg.ca/d/d4mq-wa44",
    "link": "https://data.winnipeg.ca/Assessment-and-Taxation/Assessment-Parcels/d4mq-wa44",
}

_VIEW = {
    "id": "d4mq-wa44",
    "name": "Assessment Parcels",
    "description": "Property assessment parcels within the City of Winnipeg.",
    "category": "Assessment and Taxation",
    "attribution": "City of Winnipeg",
    "license": {
        "name": "Canada Open Government Licence",
        "termsLink": "https://open.canada.ca/en/open-government-licence-canada",
    },
    "tags": ["assessment", "property"],
    "columns": [
        {
            "name": "ROLL NUMBER",
            "fieldName": "roll_number",
            "dataTypeName": "text",
            "description": "",
        },
    ],
    "createdAt": 1500000000,
    "rowsUpdatedAt": 1788607873,
    "publicationDate": 1500000000,
    "downloadCount": 3120,
    "viewCount": 42000,
}


async def test_search_parses_socrata_catalog_fields(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}?domains={constants.DOMAIN}&search_context={constants.DOMAIN}"
            "&only=datasets&limit=10&offset=0&q=assessment"
        ),
        json={"results": [_SEARCH_RESULT], "resultSetSize": 1},
    )
    result = await client.search_datasets("assessment")
    assert result.total_count == 1
    assert result.datasets[0].id == "d4mq-wa44"
    assert result.datasets[0].category == "Assessment and Taxation"
    assert result.datasets[0].landing_page_url.endswith("Assessment-Parcels/d4mq-wa44")


async def test_get_dataset_maps_view_metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/d4mq-wa44.json",
        json=_VIEW,
    )
    result = await client.get_dataset("d4mq-wa44")
    assert result.license_name == "Canada Open Government Licence"
    assert result.columns[0].field_name == "roll_number"
    assert result.rows_updated_at is not None
    assert result.csv_download_url.endswith("/rows.csv?accessType=DOWNLOAD")


async def test_query_dataset_rows_passes_soql_params(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"https://{constants.DOMAIN}/resource/d4mq-wa44.json"
            "?%24select=street_name&%24where=street_number%3D100&%24limit=5&%24offset=0"
        ),
        json=[{"street_name": "Main St"}],
    )
    result = await client.query_dataset_rows(
        "d4mq-wa44", select="street_name", where="street_number=100", limit=5
    )
    assert result.returned_count == 1
    assert result.rows[0]["street_name"] == "Main St"


async def test_list_categories_and_tags(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_categories?domains={constants.DOMAIN}",
        json={"results": [{"domain_category": "Council Services", "count": 179}]},
    )
    categories = await client.list_categories()
    assert categories.categories[0].dataset_count == 179

    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_tags?domains={constants.DOMAIN}",
        json={"results": [{"domain_tag": "meeting", "count": 113}]},
    )
    tags = await client.list_tags()
    assert tags.tags[0].tag == "meeting"


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
