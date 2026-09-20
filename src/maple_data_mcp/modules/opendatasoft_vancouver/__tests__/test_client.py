from __future__ import annotations

import pytest

from maple_data_mcp.modules.opendatasoft_vancouver import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_CATALOG_URL = f"https://{constants.DOMAIN}/api/v2/catalog"
_DATASET_ID = "olympic-city-sites"

_DATASET_META = {
    "title": "Olympic City sites",
    "description": "Locations of Olympic City sites from the 2010 Winter Games.",
    "theme": ["Parks, recreation, and pets"],
    "keyword": ["2010 Winter Games"],
    "license": "Open Government Licence - Vancouver",
    "license_url": "https://opendata.vancouver.ca/pages/licence/",
    "publisher": "City of Vancouver",
    "records_count": 5,
    "modified": "2019-06-21T16:42:24+00:00",
    "update_frequency": None,
}

_DATASET_FIELDS = [
    {"name": "site", "label": "Site", "type": "text", "description": "Site name"},
    {"name": "url_link", "label": "URL", "type": "text", "description": None},
    {"name": "geom", "label": "Geometry", "type": "geo_shape", "description": None},
]

_SEARCH_ENTRY = {
    "links": [],
    "dataset": {
        "dataset_id": _DATASET_ID,
        "fields": _DATASET_FIELDS,
        "metas": {"default": _DATASET_META},
    },
}

_DATASET_DETAIL = {
    "links": [],
    "dataset": {
        "dataset_id": _DATASET_ID,
        "fields": _DATASET_FIELDS,
        "metas": {"default": _DATASET_META},
    },
}

_RECORD_ENTRY = {
    "links": [],
    "record": {
        "id": "e9bca8a44088c91d0dac9f70cb61bf97f881bc3b",
        "timestamp": "2019-06-21T16:59:42.902Z",
        "size": 208,
        "fields": {
            "site": "LiveCity Downtown 150 Dunsmuir St",
            "url_link": "http://olympichostcity.vancouver.ca/events/livecity/georgiastreet.htm",
            "geom": {
                "type": "Feature",
                "geometry": {"coordinates": [-123.111, 49.279], "type": "Point"},
                "properties": {},
            },
        },
    },
}


async def test_search_parses_catalog_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets?limit=10&offset=0&where=search%28%2A%2C+%27olympic%27%29",
        json={"total_count": 1, "datasets": [_SEARCH_ENTRY]},
    )
    result = await client.search_datasets("olympic")
    assert result.total_count == 1
    assert result.datasets[0].id == _DATASET_ID
    assert result.datasets[0].theme == ["Parks, recreation, and pets"]
    assert result.datasets[0].records_count == 5
    assert result.datasets[0].landing_page_url.endswith(f"/explore/dataset/{_DATASET_ID}/")


async def test_search_without_query_omits_where_clause(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets?limit=5&offset=10",
        json={"total_count": 0, "datasets": []},
    )
    result = await client.search_datasets(limit=5, offset=10)
    assert result.returned_count == 0


async def test_get_dataset_maps_metadata_and_download_links(httpx_mock):
    httpx_mock.add_response(url=f"{_CATALOG_URL}/datasets/{_DATASET_ID}", json=_DATASET_DETAIL)
    result = await client.get_dataset(_DATASET_ID)
    assert result.id == _DATASET_ID
    assert result.license_name == "Open Government Licence - Vancouver"
    assert result.publisher == "City of Vancouver"
    assert len(result.fields) == 3
    assert result.fields[0].name == "site"
    assert {link.format for link in result.download_urls} == {"csv", "json", "geojson"}
    assert result.download_urls[0].url.endswith(f"/datasets/{_DATASET_ID}/exports/csv")
    assert result.modified is not None


async def test_query_records_returns_row_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets/{_DATASET_ID}/records?limit=10&offset=0",
        json={"total_count": 5, "records": [_RECORD_ENTRY]},
    )
    result = await client.query_records(_DATASET_ID)
    assert result.returned_count == 1
    assert result.total_count == 5
    assert result.rows[0]["site"] == "LiveCity Downtown 150 Dunsmuir St"


async def test_query_records_where_clause_passed_through(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}/datasets/{_DATASET_ID}/records?limit=5&offset=0"
            "&where=site+%3D+%27x%27&order_by=site"
        ),
        json={"total_count": 0, "records": []},
    )
    result = await client.query_records(_DATASET_ID, where="site = 'x'", order_by="site", limit=5)
    assert result.returned_count == 0


async def test_query_records_query_param_builds_search_clause_when_no_where(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{_CATALOG_URL}/datasets/{_DATASET_ID}/records?limit=10&offset=0"
            "&where=search%28%2A%2C+%27olympic%27%29"
        ),
        json={"total_count": 0, "records": []},
    )
    result = await client.query_records(_DATASET_ID, query="olympic")
    assert result.returned_count == 0


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")
    with pytest.raises(InvalidInput):
        await client.query_records("abcd", limit=0)

    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets/unknown",
        status_code=404,
        json={
            "error_code": "NotFoundResource",
            "message": "The requested dataset unknown does not exist.",
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")


async def test_over_limit_search_raises_invalid_input_with_error_code(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets?limit=100&offset=0",
        status_code=400,
        json={
            "error_code": "InvalidRESTParameterError",
            "message": "Invalid value for limit API parameter: 999 was found but -1 <= limit <= 100 is expected.",
        },
    )
    with pytest.raises(InvalidInput):
        await client.search_datasets(limit=100)


async def test_malformed_where_clause_raises_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=f"{_CATALOG_URL}/datasets/{_DATASET_ID}/records?limit=10&offset=0&where=garbage%3D%3D",
        status_code=400,
        json={
            "error_code": "ODSQLSyntaxError",
            "message": "ODSQL syntax exception: unexpected = at position 8 in garbage==.",
        },
    )
    with pytest.raises(InvalidInput):
        await client.query_records(_DATASET_ID, where="garbage==")


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    # 500 is retried up to 3 attempts by shared/http.py before this client
    # sees the final failure, so the mock needs a response for each attempt.
    for _ in range(3):
        httpx_mock.add_response(
            url=f"{_CATALOG_URL}/datasets/broken",
            status_code=500,
            json={"error_code": "InternalServerError", "message": "internal error"},
        )
    with pytest.raises(UpstreamError):
        await client.get_dataset("broken")
