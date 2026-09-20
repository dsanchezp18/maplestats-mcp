from __future__ import annotations

import pytest

from maple_data_mcp.modules.ckan_regina import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_ORG = {
    "id": "47b65ce1-d18b-4b36-8499-67cefefb6f0b",
    "name": "city-of-regina",
    "title": "City of Regina",
    "description": "",
    "package_count": 1379,
    "image_display_url": "",
    "image_url": "",
}

_PACKAGE = {
    "id": "b3551bfe-874b-4abc-adab-5ba214d9a118",
    "name": "building-outline",
    "title": "Building Outline",
    "notes": "The 2024 building foot print for the City of Regina compiled from the 2024 airphotos.",
    "organization": _ORG,
    "license_id": "notspecified",
    "license_title": "Open Gov. License",
    "num_resources": 2,
    "metadata_created": "2016-11-18T16:59:26.388951",
    "metadata_modified": "2024-12-30T19:43:11.640094",
    "tags": [{"name": "buildings"}, {"name": "footprint"}],
    "groups": [{"name": "maps", "title": "Maps"}],
    "resources": [
        {
            "id": "05893ded-b37a-4671-9258-9ed1567ee18b",
            "package_id": "b3551bfe-874b-4abc-adab-5ba214d9a118",
            "name": "Building Footprint Live Map",
            "description": "Map view of the Building Footprint data set.",
            "format": "HTML",
            "url": "https://opengis.regina.ca/basicviewer/viewer.html",
            "size": None,
            "datastore_active": False,
            "created": "2016-11-18T18:00:49.207661",
            "last_modified": None,
            "metadata_modified": "2016-11-18T18:00:49.207661",
            "mimetype": None,
        }
    ],
}


def _envelope(result):
    return {
        "help": "https://openregina.ca/api/3/action/help_show",
        "success": True,
        "result": result,
    }


async def test_search_parses_package_search_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=building&rows=10&start=0",
        json=_envelope({"count": 64, "results": [_PACKAGE]}),
    )
    result = await client.search_datasets("building")
    assert result.total_count == 64
    assert result.packages[0].id == _PACKAGE["id"]
    assert result.packages[0].organization_name == "city-of-regina"
    assert result.packages[0].tags == ["buildings", "footprint"]
    assert result.packages[0].groups == ["maps"]
    assert result.packages[0].landing_page_url.endswith("/building-outline")


async def test_get_dataset_maps_package_detail(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_show?id=building-outline",
        json=_envelope(_PACKAGE),
    )
    result = await client.get_dataset("building-outline")
    assert result.organization.name == "city-of-regina"
    assert result.resources[0].format == "HTML"
    assert result.groups == ["maps"]
    assert result.metadata_created is not None


async def test_list_organizations_returns_single_org(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope([_ORG]),
    )
    result = await client.list_organizations()
    assert result.total_count == 1
    assert result.organizations[0].name == "city-of-regina"
    assert result.organizations[0].package_count == 1379


async def test_get_organization(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_show?id=city-of-regina&include_datasets=false",
        json=_envelope(_ORG),
    )
    result = await client.get_organization("city-of-regina")
    assert result.package_count == 1379
    assert result.landing_page_url.endswith("/city-of-regina")


async def test_get_resource(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}resource_show?id=05893ded-b37a-4671-9258-9ed1567ee18b",
        json=_envelope(_PACKAGE["resources"][0]),
    )
    result = await client.get_resource("05893ded-b37a-4671-9258-9ed1567ee18b")
    assert result.resource.format == "HTML"
    assert result.resource.datastore_active is False


async def test_list_licenses_coerces_real_booleans(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}license_list",
        json=_envelope(
            [
                {
                    "id": "notspecified",
                    "title": "Open Gov. License",
                    "url": "",
                    "status": "active",
                    "family": "",
                    "domain_content": False,
                    "domain_data": False,
                    "domain_software": False,
                    "is_generic": True,
                    "od_conformance": "not reviewed",
                    "osd_conformance": "not reviewed",
                }
            ]
        ),
    )
    result = await client.list_licenses()
    assert result.licenses[0].is_generic is True
    assert result.licenses[0].domain_content is False


async def test_list_tags(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["buildings", "footprint", "transit"]),
    )
    result = await client.list_tags()
    assert result.total_count == 3
    assert "transit" in result.tags


async def test_list_groups_is_public_no_facet_workaround(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [
                {"name": "maps", "title": "Maps", "package_count": 42},
                {
                    "name": "city-administration",
                    "title": "City Administration",
                    "package_count": 1073,
                },
            ]
        ),
    )
    result = await client.list_groups()
    assert result.total_count == 2
    assert result.groups[0].package_count == 42
    assert result.groups[0].landing_page_url.endswith("/maps")


async def test_get_group(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_show?id=maps&include_datasets=false",
        json=_envelope(
            {
                "id": "f93a2815-5488-4cf2-9dc3-a3c13974fd2f",
                "name": "maps",
                "title": "Maps",
                "description": "Static and interactive city maps.",
                "package_count": 42,
                "image_display_url": "",
                "image_url": "",
            }
        ),
    )
    result = await client.get_group("maps")
    assert result.package_count == 42
    assert result.landing_page_url.endswith("/maps")


async def test_invalid_input_and_not_found_are_typed(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", rows=0)
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")
    with pytest.raises(InvalidInput):
        await client.get_group(" ")

    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_show?id=__nonexistent__",
        status_code=404,
        json={
            "help": "https://openregina.ca/api/3/action/help_show",
            "error": {"__type": "Not Found Error", "message": "Not found"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("__nonexistent__")


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
