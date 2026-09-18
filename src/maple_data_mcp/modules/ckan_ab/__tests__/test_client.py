from __future__ import annotations

import pytest

from maple_data_mcp.modules.ckan_ab import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _envelope(result: object) -> dict[str, object]:
    return {"help": "help", "success": True, "result": result}


_PACKAGE = {
    "id": "ab-package",
    "name": "ab-package",
    "title": "Alberta housing data",
    "notes": "Housing notes",
    "isopen": True,
    "organization": {"id": "org-id", "name": "housing", "title": "Housing Alberta"},
    "license_id": "OGLA",
    "license_title": "Open Government Licence - Alberta",
    "metadata_modified": "2026-09-11T22:05:22",
    "num_resources": 1,
    "tags": [{"name": "housing", "display_name": "housing"}],
    "resources": [
        {
            "id": "resource-id",
            "package_id": "ab-package",
            "name": "housing.csv",
            "description": "A CSV",
            "format": "CSV",
            "url": "https://open.alberta.ca/housing.csv",
            "size": 10,
            "datastore_active": False,
            "created": "2026-09-01T00:00:00",
            "metadata_modified": "2026-09-01T00:00:00",
            "mimetype": "text/csv",
        }
    ],
}


async def test_search_parses_alberta_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=housing&rows=10&start=0",
        json=_envelope({"count": 1, "results": [_PACKAGE]}),
    )
    result = await client.search_datasets("housing")
    assert result.total_count == 1
    assert result.packages[0].is_open is True
    assert result.packages[0].tags == ["housing"]
    assert result.packages[0].resource_formats == ["CSV"]


async def test_detail_maps_alberta_metadata(httpx_mock):
    package = {
        **_PACKAGE,
        "creator": ["Alberta Treasury Board"],
        "contact": "Open Data",
        "contact_email": "data@example.ca",
        "createdate": "2020-01-02",
        "issuedate": "2020-01-03",
        "updatefrequency": "Monthly",
        "language": ["en-CA [default]"],
        "subject": ["Housing"],
        "subject2": "Economy",
    }
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_show?id=ab-package",
        json=_envelope(package),
    )
    result = await client.get_dataset("ab-package")
    assert result.creator == ["Alberta Treasury Board"]
    assert result.update_frequency == "Monthly"
    assert result.subjects == ["Housing", "Economy"]
    assert result.resources[0].datastore_active is False


async def test_lists_organizations_licenses_and_tags(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [{"id": "org-id", "name": "housing", "title": "Housing Alberta", "package_count": 2}]
        ),
    )
    organizations = await client.list_organizations()
    assert organizations.organizations[0].package_count == 2

    httpx_mock.add_response(
        url=f"{constants.BASE_URL}license_list",
        json=_envelope(
            [
                {
                    "id": "OGLA",
                    "title": "Open Government Licence - Alberta",
                    "url": "https://open.alberta.ca/licence",
                    "status": "active",
                    "is_okd_compliant": True,
                    "is_osi_compliant": False,
                }
            ]
        ),
    )
    licenses = await client.list_licenses()
    assert licenses.licenses[0].is_okd_compliant is True

    monkeypatch.setattr(constants, "TAG_LIST_MAX", 1)
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["housing", "economy"]),
    )
    tags = await client.list_tags()
    assert tags.tags == ["housing"]
    assert tags.total_count == 2
    assert tags.truncated is True


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", rows=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")

    httpx_mock.add_response(
        status_code=404, json={"success": False, "error": {"message": "Not found"}}
    )
    with pytest.raises(NotFound):
        await client.get_dataset("unknown")
