from __future__ import annotations

import pytest

from maple_data_mcp.modules.ckan_on import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _envelope(result: object) -> dict[str, object]:
    return {"help": "help", "success": True, "result": result}


_PACKAGE = {
    "id": "on-package",
    "name": "on-package",
    "title": "Ontario housing supply",
    "title_translated": {"en": "Ontario housing supply", "fr": "Offre de logements en Ontario"},
    "notes": "Housing notes",
    "notes_translated": {"en": "Housing notes", "fr": "Notes sur le logement"},
    "isopen": True,
    "keywords": {"en": ["Housing"], "fr": ["Habitation"]},
    "organization": {"id": "org-id", "name": "housing", "title": "Housing"},
    "license_id": "OGL-ON-1.0",
    "license_title": "Open Government Licence - Ontario",
    "metadata_created": "2024-01-01T00:00:00",
    "metadata_modified": "2026-09-11T00:00:00",
    "num_resources": 1,
    "tags": [{"name": "Housing"}],
    "groups": [{"name": "housing", "title": "Housing"}],
    "resources": [
        {
            "id": "resource-id",
            "package_id": "on-package",
            "name": "housing.csv",
            "name_translated": {"en": "Housing CSV", "fr": "CSV du logement"},
            "description": "English description",
            "description_translated": {"en": "English description", "fr": "Description française"},
            "format": "CSV",
            "url": "https://data.ontario.ca/housing.csv",
            "size": 10,
            "datastore_active": True,
            "data_last_updated": "2025-12-15",
            "data_range_start": "2024-01-01",
            "data_range_end": "2024-12-31",
            "created": "2024-01-01T00:00:00",
            "metadata_modified": "2025-12-15T00:00:00",
            "mimetype": "text/csv",
        }
    ],
}


async def test_search_uses_requested_translation(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=housing&rows=10&start=0",
        json=_envelope({"count": 1, "results": [_PACKAGE]}),
    )
    result = await client.search_datasets("housing", lang="fr")
    assert result.packages[0].title == "Offre de logements en Ontario"
    assert result.packages[0].landing_page_url.endswith("/fr/dataset/on-package")


async def test_detail_maps_bilingual_metadata_and_resources(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_show?id=on-package",
        json=_envelope(
            {
                **_PACKAGE,
                "author": "Planning Policy Branch",
                "maintainer_translated": {"en": "Planning", "fr": "Planification"},
                "maintainer_email": "data@example.ca",
                "access_level": "open",
                "current_as_of": "2025-12-15",
                "geographic_coverage_translated": {"en": "Ontario", "fr": "Ontario"},
                "geographic_granularity": "municipality",
                "update_frequency": "monthly",
            }
        ),
    )
    result = await client.get_dataset("on-package", lang="fr")
    assert result.title == "Offre de logements en Ontario"
    assert result.notes == "Notes sur le logement"
    assert result.maintainer == "Planification"
    assert result.keywords == ["Habitation"]
    assert result.resources[0].name == "CSV du logement"
    assert result.resources[0].datastore_active is True


async def test_lists_licenses_and_groups(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}license_list",
        json=_envelope(
            [
                {
                    "id": "OGL-ON-1.0",
                    "title": "Open Government Licence - Ontario",
                    "title_translated": {
                        "en": "Open Government Licence - Ontario",
                        "fr": "Licence Ontario",
                    },
                    "url": "https://www.ontario.ca/page/open-government-licence-ontario",
                    "url_translated": {"fr": "https://www.ontario.ca/fr/page/licence"},
                    "status": "active",
                    "domain_data": True,
                    "is_generic": False,
                }
            ]
        ),
    )
    licenses = await client.list_licenses(lang="fr")
    assert licenses.licenses[0].title == "Licence Ontario"
    assert licenses.licenses[0].domain_data is True

    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [{"id": "group-id", "name": "housing", "title": "Housing", "package_count": 3}]
        ),
    )
    groups = await client.list_groups(lang="fr")
    assert groups.groups[0].package_count == 3
    assert groups.groups[0].landing_page_url.endswith("/fr/group/housing")


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", rows=0)
    with pytest.raises(InvalidInput):
        await client.get_resource(" ")

    httpx_mock.add_response(
        status_code=404, json={"success": False, "error": {"message": "Not found"}}
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")


async def test_datastore_search_parses_records_and_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}datastore_search?resource_id=abc&limit=20&offset=0",
        json={
            "help": "help",
            "success": True,
            "result": {
                "total": 100,
                "records": [{"_id": 1, "sample_field": "sample_value"}],
                "fields": [{"id": "_id", "type": "int"}, {"id": "sample_field", "type": "text"}],
            },
        },
    )
    result = await client.datastore_search("abc")
    assert result.total_count == 100
    assert result.returned_count == 1
    assert result.records[0]["sample_field"] == "sample_value"
    assert result.fields[0].id == "_id"


async def test_datastore_search_encodes_filters_as_json(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}datastore_search?resource_id=abc&limit=20&offset=0"
            "&filters=%7B%22key%22%3A+%22value%22%7D"
        ),
        json={"help": "help", "success": True, "result": {"total": 1, "records": [], "fields": []}},
    )
    result = await client.datastore_search("abc", filters={"key": "value"})
    assert result.filters == {"key": "value"}


async def test_datastore_search_unknown_resource_raises_not_found(httpx_mock):
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "success": False,
            "error": {"__type": "Not Found Error", "message": 'Resource "x" was not found.'},
        },
    )
    with pytest.raises(NotFound):
        await client.datastore_search("x")


async def test_datastore_search_invalid_input_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.datastore_search("abc", limit=0)
    with pytest.raises(InvalidInput):
        await client.datastore_search("abc", offset=-1)
    with pytest.raises(InvalidInput):
        await client.datastore_search(" ")
