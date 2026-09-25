from __future__ import annotations

from typing import get_args

import pytest

from maplestats_mcp.modules.socrata import client, constants
from maplestats_mcp.modules.socrata.schemas import PortalKey
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
PORTAL = "ns"
DOMAIN = constants.PORTALS[PORTAL].domain

_SEARCH_RESULT = {
    "resource": {
        "id": "3nka-59nz",
        "name": "Crown Land",
        "description": "A spatial dataset of all Crown lands in Nova Scotia.",
        "lens_view_type": "tabular",
        "updatedAt": "2026-09-05T11:31:13.000Z",
        "download_count": 9011,
    },
    "classification": {
        "domain_category": "Lands, Forests and Wildlife",
        "domain_tags": ["crown land", "natural resources"],
    },
    "permalink": "https://data.novascotia.ca/d/3nka-59nz",
    "link": "https://data.novascotia.ca/Lands-Forests-and-Wildlife/Crown-Land/3nka-59nz",
}

_VIEW = {
    "id": "3nka-59nz",
    "name": "Crown Land",
    "description": "A spatial dataset of all Crown lands in Nova Scotia.",
    "category": "Lands, Forests and Wildlife",
    "attribution": None,
    "license": {
        "name": "Nova Scotia Open Government Licence",
        "termsLink": "http://novascotia.ca/opendata/licence.asp",
    },
    "tags": ["crown land", "natural resources"],
    "columns": [
        {"name": "DNR_ID", "fieldName": "dnr_id", "dataTypeName": "number", "description": ""},
    ],
    "createdAt": 1670000000,
    "rowsUpdatedAt": 1788607873,
    "publicationDate": 1673028953,
    "downloadCount": 9011,
    "viewCount": 216790,
}


async def test_search_parses_socrata_catalog_fields(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}?domains={DOMAIN}&search_context={DOMAIN}"
            "&only=datasets&limit=10&offset=0&q=crown"
        ),
        json={"results": [_SEARCH_RESULT], "resultSetSize": 1},
    )
    result = await client.search_datasets(PORTAL, "crown")
    assert result.total_count == 1
    assert result.datasets[0].id == "3nka-59nz"
    assert result.datasets[0].category == "Lands, Forests and Wildlife"
    assert result.datasets[0].tags == ["crown land", "natural resources"]
    assert result.datasets[0].landing_page_url.endswith("Crown-Land/3nka-59nz")


async def test_get_dataset_maps_view_metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"https://{DOMAIN}/api/views/3nka-59nz.json",
        json=_VIEW,
    )
    result = await client.get_dataset(PORTAL, "3nka-59nz")
    assert result.license_name == "Nova Scotia Open Government Licence"
    assert result.columns[0].field_name == "dnr_id"
    assert result.rows_updated_at is not None
    assert result.rows_updated_at.year == 2026
    assert result.csv_download_url.endswith("/rows.csv?accessType=DOWNLOAD")


async def test_query_dataset_rows_passes_soql_params(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"https://{DOMAIN}/resource/44ah-ugrd.json"
            "?%24select=region%2Cyear&%24where=year%3D%272023-24%27&%24limit=5&%24offset=0"
        ),
        json=[{"region": "CBRM", "year": "2023-24"}],
    )
    result = await client.query_dataset_rows(
        PORTAL, "44ah-ugrd", select="region,year", where="year='2023-24'", limit=5
    )
    assert result.returned_count == 1
    assert result.rows[0]["region"] == "CBRM"


async def test_list_categories_and_tags(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_categories?domains={DOMAIN}",
        json={"results": [{"domain_category": "Health and Wellness", "count": 194}]},
    )
    categories = await client.list_categories(PORTAL)
    assert categories.categories[0].dataset_count == 194

    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/domain_tags?domains={DOMAIN}",
        json={"results": [{"domain_tag": "air quality", "count": 102}]},
    )
    tags = await client.list_tags(PORTAL)
    assert tags.tags[0].tag == "air quality"


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets(PORTAL, "x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(PORTAL, " ")
    with pytest.raises(InvalidInput):
        await client.query_dataset_rows(PORTAL, "abcd-1234", limit=0)

    httpx_mock.add_response(
        url=f"https://{DOMAIN}/api/views/unknown.json",
        status_code=404,
        json={"code": "dataset.missing", "error": True, "message": "Not found", "data": {}},
    )
    with pytest.raises(NotFound):
        await client.get_dataset(PORTAL, "unknown")


def test_portal_key_literal_matches_registry():
    assert set(get_args(PortalKey)) == set(constants.PORTALS)


async def test_unknown_portal_raises_invalid_input():
    with pytest.raises(InvalidInput):
        await client.list_tags("atlantis")


@pytest.mark.parametrize("portal", sorted(constants.PORTALS))
async def test_every_portal_queries_its_own_domain(httpx_mock, portal):
    domain = constants.PORTALS[portal].domain
    httpx_mock.add_response(
        url=f"https://{domain}/resource/abcd-1234.json?%24limit=10&%24offset=0",
        json=[{"a": 1}],
    )
    result = await client.query_dataset_rows(portal, "abcd-1234")
    assert result.portal == portal
    assert result.provenance.source == f"socrata-{portal}"
