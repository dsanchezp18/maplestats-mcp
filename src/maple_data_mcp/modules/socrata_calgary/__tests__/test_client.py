"""Fixtures below are shaped after live responses confirmed 2026-09-19
against data.calgary.ca (dataset 35ra-9556, "Traffic Incidents")."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.socrata_calgary import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound

_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SEARCH_RESULT = {
    "resource": {
        "id": "35ra-9556",
        "name": "Traffic Incidents",
        "description": "Traffic incidents recorded by the Calgary Traffic Management Centre.",
        "lens_view_type": "tabular",
        "updatedAt": "2026-09-19T11:00:00.000Z",
        "download_count": 5231,
    },
    "classification": {
        "domain_category": "Transportation/Transit",
        "domain_tags": ["traffic", "incidents"],
    },
    "permalink": "https://data.calgary.ca/d/35ra-9556",
    "link": "https://data.calgary.ca/Transportation-Transit/Traffic-Incidents/35ra-9556",
}

_VIEW = {
    "id": "35ra-9556",
    "name": "Traffic Incidents",
    "description": "Traffic incidents recorded by the Calgary Traffic Management Centre.",
    "category": "Transportation/Transit",
    "attribution": "The City of Calgary",
    "license": {"name": "See Terms of Use", "termsLink": "https://data.calgary.ca/terms"},
    "tags": ["traffic", "incidents"],
    "columns": [
        {
            "name": "INCIDENT INFO",
            "fieldName": "incident_info",
            "dataTypeName": "text",
            "description": "",
        },
    ],
    "createdAt": 1500000000,
    "rowsUpdatedAt": 1788607873,
    "publicationDate": 1500000000,
    "downloadCount": 5231,
    "viewCount": 98000,
}


async def test_search_parses_socrata_catalog_fields(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}?domains={constants.DOMAIN}&search_context={constants.DOMAIN}"
            "&only=datasets&limit=10&offset=0&q=traffic"
        ),
        json={"results": [_SEARCH_RESULT], "resultSetSize": 1},
    )
    result = await client.search_datasets("traffic")
    assert result.total_count == 1
    assert result.datasets[0].id == "35ra-9556"
    assert result.datasets[0].category == "Transportation/Transit"
    assert result.datasets[0].landing_page_url.endswith("Traffic-Incidents/35ra-9556")


async def test_get_dataset_maps_view_metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/35ra-9556.json",
        json=_VIEW,
    )
    result = await client.get_dataset("35ra-9556")
    assert result.license_name == "See Terms of Use"
    assert result.columns[0].field_name == "incident_info"
    assert result.rows_updated_at is not None
    assert result.csv_download_url.endswith("/rows.csv?accessType=DOWNLOAD")


async def test_query_dataset_rows_passes_soql_params(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"https://{constants.DOMAIN}/resource/35ra-9556.json"
            "?%24select=quadrant&%24where=quadrant%3D%27NE%27&%24limit=5&%24offset=0"
        ),
        json=[{"quadrant": "NE"}],
    )
    result = await client.query_dataset_rows(
        "35ra-9556", select="quadrant", where="quadrant='NE'", limit=5
    )
    assert result.returned_count == 1
    assert result.rows[0]["quadrant"] == "NE"


async def test_list_categories_and_tags(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_categories?domains={constants.DOMAIN}",
        json={"results": [{"domain_category": "Transportation/Transit", "count": 153}]},
    )
    categories = await client.list_categories()
    assert categories.categories[0].dataset_count == 153

    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_tags?domains={constants.DOMAIN}",
        json={"results": [{"domain_tag": "census", "count": 50}]},
    )
    tags = await client.list_tags()
    assert tags.tags[0].tag == "census"


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
