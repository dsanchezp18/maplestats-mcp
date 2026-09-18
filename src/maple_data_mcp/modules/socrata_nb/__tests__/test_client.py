from __future__ import annotations

import pytest

from maple_data_mcp.modules.socrata_nb import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"

_SEARCH_RESULT = {
    "resource": {
        "id": "y2uk-apy8",
        "name": "Senior Executive Expenses 2020-21 Q4 / Frais de déplacement 2020-2021 T4",
        "description": "Quarterly senior executive expenses / Dépenses trimestrielles des cadres.",
        "lens_view_type": "tabular",
        "updatedAt": "2021-06-01T00:00:00.000Z",
        "download_count": 42,
    },
    "classification": {
        "domain_category": "Quarterly Datasets",
        "domain_tags": ["senior executive expenses", "frais de subsistance"],
    },
    "permalink": "https://gnb.socrata.com/d/y2uk-apy8",
    "link": "https://gnb.socrata.com/stories/s/y2uk-apy8",
}

_VIEW = {
    "id": "y2uk-apy8",
    "name": "Senior Executive Expenses 2020-21 Q4 / Frais de déplacement 2020-2021 T4",
    "description": "Quarterly senior executive expenses / Dépenses trimestrielles des cadres.",
    "category": "Quarterly Datasets",
    "attribution": "Finance and Treasury Board / Finances et Conseil du Trésor",
    "license": {"name": "New Brunswick Open Government Licence", "termsLink": None},
    "tags": ["senior executive expenses", "frais de subsistance"],
    "columns": [
        {
            "name": "Department / Département",
            "fieldName": "department_department",
            "dataTypeName": "text",
            "description": "",
        },
    ],
    "createdAt": 1610000000,
    "rowsUpdatedAt": 1622505600,
    "publicationDate": 1610000000,
    "downloadCount": 42,
    "viewCount": 500,
}


async def test_search_keeps_bilingual_fields_intact(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}?domains={constants.DOMAIN}&search_context={constants.DOMAIN}"
            "&only=datasets&limit=10&offset=0&q=expenses"
        ),
        json={"results": [_SEARCH_RESULT], "resultSetSize": 1},
    )
    result = await client.search_datasets("expenses")
    assert result.datasets[0].id == "y2uk-apy8"
    assert "Frais de d" in result.datasets[0].name
    assert "senior executive expenses" in result.datasets[0].tags


async def test_get_dataset_maps_bilingual_view_metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/y2uk-apy8.json",
        json=_VIEW,
    )
    result = await client.get_dataset("y2uk-apy8")
    assert result.license_name == "New Brunswick Open Government Licence"
    assert result.columns[0].field_name == "department_department"
    assert result.attribution is not None and "Conseil du Tr" in result.attribution


async def test_query_dataset_rows_returns_bilingual_values(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/resource/y2uk-apy8.json?%24limit=1&%24offset=0",
        json=[{"department_department": "Aboriginal Affairs / Affaires autochtones"}],
    )
    result = await client.query_dataset_rows("y2uk-apy8", limit=1)
    assert result.rows[0]["department_department"].startswith("Aboriginal Affairs")


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")

    httpx_mock.add_response(
        url=f"https://{constants.DOMAIN}/api/views/unknown.json",
        status_code=404,
        json={"code": "dataset.missing", "error": True, "message": "Not found", "data": {}},
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")
