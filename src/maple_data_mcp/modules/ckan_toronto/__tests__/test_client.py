"""Tests for modules/ckan_toronto/client.py.

Shaped around the real quirks confirmed live against
ckan0.cf.opendata.inter.prod-toronto.ca this session (see client.py's
module docstring and the throwaway smoke script -- scripts/
smoke_test_ckan_toronto.py -- run before these were written), not just
the happy path: the `{"help","success","result"}` envelope, package_show
returning an HTML (not JSON) body on a 404, package_search's 400 JSON
error shape, license_list's "True"/"False" string booleans, tags as a
list of dicts (flattened to plain names), resources with no
description/language fields but with datastore_active/record_count,
and organization_list carrying exactly one organization.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_toronto import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clear_shared_cache():
    """shared/cache.py's TTLCache buckets are module-level singletons, so
    a cache hit from an earlier test would otherwise silently reuse a
    stale mocked response instead of exercising the next mock."""
    cache_module._caches.clear()
    yield


def _envelope(result: object) -> dict[str, object]:
    return {
        "help": f"{constants.BASE_URL}help_show",
        "success": True,
        "result": result,
    }


_NOT_FOUND_HTML = "<html><head><title>403/404 Error</title></head><body>Not Found</body></html>"

_PACKAGE_OBJ = {
    "id": "abbe5ee3-e249-4f86-a219-f0022eaddcc9",
    "name": "cycling-network",
    "title": "Cycling Network",
    "notes": "This dataset shares the mapping details of Toronto's existing cycling network.",
    "excerpt": "This dataset shares the mapping details of Toronto's existing cycling network.",
    "organization": {
        "id": "6ed95875-f7d6-4200-964c-91024cc49cba",
        "name": "city-of-toronto",
        "title": "City of Toronto",
    },
    "license_id": None,
    "license_title": None,
    "dataset_category": "Map",
    "is_retired": False,
    "information_url": None,
    "limitations": "",
    "civic_issues": ["Mobility"],
    "tags": [
        {
            "id": "b012e018-d96c-447d-be57-b24dad27e4d7",
            "name": "bike lane",
            "display_name": "bike lane",
            "vocabulary_id": None,
        },
        {
            "id": "6019b691-260e-4f03-b554-22226f13182f",
            "name": "bicycle route",
            "display_name": "bicycle route",
            "vocabulary_id": None,
        },
    ],
    "topics": ["Locations and mapping", "Transportation"],
    "refresh_rate": "Semi-annually",
    "formats": ["CSV", "GEOJSON"],
    "metadata_created": "2019-07-23T16:59:49.300570",
    "metadata_modified": "2026-09-14T19:14:43.338902",
    "num_resources": 2,
    "num_tags": 2,
    "groups": [],
    "resources": [
        {
            "id": "71fdb11f-99df-4f7b-8af1-d7240dae69b3",
            "package_id": "abbe5ee3-e249-4f86-a219-f0022eaddcc9",
            "name": "cycling-network",
            "format": "GeoJSON",
            "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/71fdb11f-99df-4f7b-8af1-d7240dae69b3",
            "size": None,
            "datastore_active": True,
            "record_count": 1581,
            "created": "2025-06-30T20:28:13.343173",
            "last_modified": None,
            "metadata_modified": "2026-09-14T19:14:42.911288",
            "mimetype": None,
        },
        {
            "id": "d294f885-e3a6-4b66-ba9c-d38e7ac29cae",
            "package_id": "abbe5ee3-e249-4f86-a219-f0022eaddcc9",
            "name": "cycling-network-shp",
            "format": "SHP",
            "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/abbe5ee3-e249-4f86-a219-f0022eaddcc9/resource/d294f885-e3a6-4b66-ba9c-d38e7ac29cae/download/cycling-network.zip",
            "size": 175738,
            "datastore_active": False,
            "record_count": None,
            "created": "2019-07-23T16:59:49.300570",
            "last_modified": "2019-07-23T16:59:49.255587",
            "metadata_modified": "2022-03-25T15:05:24.750578",
            "mimetype": "application/zip",
        },
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=cycling&rows=10&start=0",
        json=_envelope({"count": 27, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("cycling")
    assert result.total_count == 27
    assert result.returned_count == 1
    assert result.packages[0].id == "abbe5ee3-e249-4f86-a219-f0022eaddcc9"
    assert result.packages[0].organization_name == "city-of-toronto"
    assert result.packages[0].formats == ["CSV", "GEOJSON"]
    assert result.packages[0].tags == ["bike lane", "bicycle route"]
    assert result.packages[0].topics == ["Locations and mapping", "Transportation"]


async def test_search_datasets_uses_provided_excerpt_not_notes(httpx_mock):
    """Confirmed live: package_search already carries a curated `excerpt`
    field -- must use it directly, not re-truncate `notes` the way the
    federal module does (it has no `excerpt` field to use)."""
    obj = {
        **_PACKAGE_OBJ,
        "excerpt": "Short curated excerpt.",
        "notes": "A completely different, longer notes field.",
    }
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=x&rows=10&start=0",
        json=_envelope({"count": 1, "results": [obj]}),
    )
    result = await client.search_datasets("x")
    assert result.packages[0].excerpt == "Short curated excerpt."


async def test_search_datasets_rejects_rows_out_of_bounds():
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", rows=0)
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", rows=constants.SEARCH_ROWS_MAX + 1)


async def test_search_datasets_rejects_negative_start():
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", start=-1)


async def test_search_datasets_sends_fq_and_sort(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}package_search?q=&rows=5&start=0"
            "&fq=tags%3Acycling&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="tags:cycling", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a proper CKAN
    JSON error body for a bad `sort` field, same shape as the federal
    portal (unlike package_show's 404, which is plain HTML here)."""
    httpx_mock.add_response(
        status_code=400,
        json={
            "help": "help",
            "error": {"__type": "Search Query Error", "message": 'Invalid "sort" parameter'},
            "success": False,
        },
    )
    with pytest.raises(InvalidInput, match="Invalid"):
        await client.search_datasets("x", sort="bogus_field")


async def test_get_dataset_maps_html_404_to_not_found(httpx_mock):
    """Confirmed live: unlike the federal portal's JSON error envelope,
    this deployment's package_show returns a plain HTML "403/404 Error"
    page on an unknown id. shared/ckan.py's error handling must still
    raise NotFound from the non-JSON body."""
    httpx_mock.add_response(status_code=404, text=_NOT_FOUND_HTML)
    with pytest.raises(NotFound):
        await client.get_dataset("does-not-exist")


async def test_get_dataset_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_dataset("   ")


async def test_get_dataset_parses_civic_issues_topics_and_limitations(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.civic_issues == ["Mobility"]
    assert result.topics == ["Locations and mapping", "Transportation"]
    assert result.limitations is None  # empty string normalized to None
    assert result.tags == ["bike lane", "bicycle route"]
    assert result.dataset_category == "Map"


async def test_get_dataset_resource_has_no_description_or_language_fields(httpx_mock):
    """Confirmed live: Toronto resources never carry `description` or
    `language` keys at all -- ResourceInfo has no such fields, unlike
    ckan_federal's ResourceInfo which models both."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert not hasattr(result.resources[0], "description")
    assert not hasattr(result.resources[0], "language")


async def test_get_dataset_resource_exposes_datastore_fields(httpx_mock):
    """Confirmed live: a datastore-backed resource carries
    datastore_active=true and a record_count; a plain file resource
    carries datastore_active=false, record_count=None, and a real
    `size` instead."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    datastore_res = result.resources[0]
    file_res = result.resources[1]
    assert datastore_res.datastore_active is True
    assert datastore_res.record_count == 1581
    assert datastore_res.size is None
    assert file_res.datastore_active is False
    assert file_res.record_count is None
    assert file_res.size == 175738


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 2
    assert len(result.resources) == 2
    assert result.organization.name == "city-of-toronto"
    assert result.landing_page_url == f"https://open.toronto.ca/dataset/{_PACKAGE_OBJ['name']}/"


async def test_list_organizations_returns_single_organization(httpx_mock):
    """Confirmed live: this portal publishes through exactly one
    organization, unlike the federal portal's ~350 departments."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "6ed95875-f7d6-4200-964c-91024cc49cba",
                    "name": "city-of-toronto",
                    "title": "City of Toronto",
                    "package_count": 557,
                }
            ]
        ),
    )
    result = await client.list_organizations()
    assert result.total_count == 1
    assert result.organizations[0].name == "city-of-toronto"
    assert result.organizations[0].package_count == 557


async def test_get_organization_builds_catalogue_landing_url(httpx_mock):
    """Confirmed live: this portal has no /organization/<name>/ page --
    the working landing URL is the catalogue page filtered by
    organization, unlike ckan_federal's dedicated organization page."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "6ed95875-f7d6-4200-964c-91024cc49cba",
                "name": "city-of-toronto",
                "title": "City of Toronto",
                "description": "",
                "package_count": 557,
                "image_url": "",
            }
        )
    )
    result = await client.get_organization("city-of-toronto")
    assert result.title == "City of Toronto"
    assert result.description is None
    assert result.image_url is None
    assert (
        result.landing_page_url == "https://open.toronto.ca/catalogue/?organization=city-of-toronto"
    )


async def test_get_organization_maps_html_404_to_not_found(httpx_mock):
    httpx_mock.add_response(status_code=404, text=_NOT_FOUND_HTML)
    with pytest.raises(NotFound):
        await client.get_organization("not-a-real-org")


async def test_get_resource_wraps_in_resource_detail(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ["resources"][0]))
    result = await client.get_resource("71fdb11f-99df-4f7b-8af1-d7240dae69b3")
    assert result.resource.id == "71fdb11f-99df-4f7b-8af1-d7240dae69b3"
    assert result.resource.format == "GeoJSON"
    assert result.resource.datastore_active is True
    assert result.provenance.source == "ckan-toronto"


async def test_list_licenses_coerces_string_booleans(httpx_mock):
    """Confirmed live: this portal's license_list is CKAN's stock shape,
    sending domain_content/domain_data/domain_software/is_generic as
    the JSON strings "True"/"False" rather than real booleans -- unlike
    both the federal portal's is_okd_compliant/is_osi_compliant flags
    and every other boolean field elsewhere in this same API."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "cc-zero",
                    "title": "Creative Commons CCZero",
                    "url": "http://www.opendefinition.org/licenses/cc-zero",
                    "status": "active",
                    "family": "",
                    "domain_content": "True",
                    "domain_data": "True",
                    "domain_software": "False",
                    "is_generic": "False",
                    "od_conformance": "approved",
                    "osd_conformance": "not reviewed",
                }
            ]
        )
    )
    result = await client.list_licenses()
    lic = result.licenses[0]
    assert lic.domain_content is True
    assert lic.domain_data is True
    assert lic.domain_software is False
    assert lic.is_generic is False
    assert lic.od_conformance == "approved"


async def test_list_tags_returns_plain_name_list(httpx_mock):
    """Confirmed live: tag_list (without all_fields) returns a plain
    list of tag-name strings -- this portal genuinely uses CKAN tags,
    unlike the federal portal, which has no tag/group tools at all."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["bicycle", "cycling", "transportation"]),
    )
    result = await client.list_tags()
    assert result.total_count == 3
    assert result.tags == ["bicycle", "cycling", "transportation"]


async def test_unsuccessful_envelope_with_200_status_raises_upstream_error(httpx_mock):
    """Defensive: even though every confirmed-live error case ships a
    non-2xx HTTP status alongside success=false, guard the case where a
    200 response nonetheless carries success=false rather than trusting
    the envelope blindly."""
    httpx_mock.add_response(json={"help": "help", "success": False, "result": None})
    with pytest.raises(UpstreamError):
        await client.list_licenses()


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.list_licenses()


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


async def test_datastore_search_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=500, json={"success": False})
    with pytest.raises(UpstreamError):
        await client.datastore_search("abc")
