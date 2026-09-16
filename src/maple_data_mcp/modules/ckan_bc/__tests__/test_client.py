"""Tests for modules/ckan_bc/client.py.

Shaped around the real quirks confirmed live against
catalogue.data.gov.bc.ca this session (see client.py's module docstring
and scripts/smoke_test_ckan_bc.py, run before these were written), not
just the happy path: the `{"help","success","result"}` envelope, the
404/400 error shapes, this portal's real tags/groups arrays (unlike
ckan_federal, which has none), the `organization_list(all_fields=True)`
25-item cap worked around via package_search's `organization` facet,
`group_list(all_fields=True)`'s auth wall worked around via the
`groups` facet, the literal-string-"null" resource-field quirk, and
`datastore_active`'s inconsistent bool/string typing across sibling
resources.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_bc import client, constants
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
        "help": "https://catalogue.data.gov.bc.ca/api/3/action/help_show",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "d318a079-d1e1-4695-9dc6-7f134f7f7c42",
    "name": "census-profiles-for-bc-census-subdivisions-2016-census",
    "title": "Census Profiles for BC Census Subdivisions - 2016 Census",
    "notes": "Comprehensive set of census profile attributes for census subdivisions.",
    "organization": {
        "id": "68bcff90-c51d-4df9-9ecd-fd0bc507e74e",
        "name": "bc-stats",
        "title": "BC Stats",
    },
    "license_id": "21",
    "license_title": "Statistics Canada Open Licence",
    "license_url": "https://www.statcan.gc.ca/eng/reference/licence",
    "metadata_created": "2021-04-08T12:29:20.537401",
    "metadata_modified": "2023-07-20T01:53:20.049449",
    "num_resources": 1,
    "tags": [
        {
            "display_name": "census profiles",
            "id": "28c9f629-ef8f-4a67-8c09-71ddcb132e15",
            "name": "census profiles",
            "state": "active",
            "vocabulary_id": None,
        },
        {
            "display_name": "census subdivision",
            "id": "909d247a-06cd-486c-9c4a-a55171e4f630",
            "name": "census subdivision",
            "state": "active",
            "vocabulary_id": None,
        },
    ],
    "groups": [
        {
            "description": "Census Profiles present information from the census.",
            "display_name": "Census Profiles",
            "id": "af397aae-9da7-4ba5-8801-f9d7cd816454",
            "image_display_url": "https://catalogue.data.gov.bc.ca/uploads/group/x.png",
            "name": "census-profiles",
            "title": "Census Profiles",
        }
    ],
    "resources": [
        {
            "id": "b3b986e5-33bf-46c2-82a7-0b7023d9f9fa",
            "package_id": "d318a079-d1e1-4695-9dc6-7f134f7f7c42",
            "name": "BC Geographic Warehouse Custom Download",
            "description": "The Distribution Service allows for data to be downloaded.",
            "format": "multiple",
            "url": "",
            "size": None,
            "resource_type": "data",
            "resource_storage_location": "bc geographic warehouse",
            "object_name": "WHSE_HUMAN_CULTURAL_ECONOMIC.CEN_PROF_DTL_CSD_ATTRS_2016_SV",
            "datastore_active": "false",
            "created": "2021-04-08T12:29:40.209000",
            "last_modified": None,
            "metadata_modified": "2021-04-08T12:29:40.209000",
            "mimetype": "null",
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=census&rows=10&start=0",
        json=_envelope({"count": 30, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("census")
    assert result.total_count == 30
    assert result.returned_count == 1
    assert result.packages[0].id == "d318a079-d1e1-4695-9dc6-7f134f7f7c42"
    assert result.packages[0].organization_name == "bc-stats"
    assert result.packages[0].resource_formats == ["multiple"]


async def test_search_datasets_notes_excerpt_is_truncated(httpx_mock):
    long_notes = "x" * (constants.NOTES_EXCERPT_LENGTH + 50)
    obj = {**_PACKAGE_OBJ, "notes": long_notes}
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=x&rows=10&start=0",
        json=_envelope({"count": 1, "results": [obj]}),
    )
    result = await client.search_datasets("x")
    excerpt = result.packages[0].notes_excerpt
    assert len(excerpt) == constants.NOTES_EXCERPT_LENGTH + 1  # +1 for the ellipsis character
    assert excerpt.endswith("…")


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
            "&fq=organization%3Abc-stats&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="organization:bc-stats", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a
    {"error": {"__type": "Search Query Error", ...}} body for a bad
    `sort` field -- the same shape as ckan_federal."""
    httpx_mock.add_response(
        status_code=400,
        json={
            "help": "help",
            "error": {
                "__type": "Search Query Error",
                "message": "Search Query is invalid: 'Invalid \"sort\" parameter'",
            },
            "success": False,
        },
    )
    with pytest.raises(InvalidInput, match="Invalid"):
        await client.search_datasets("x", sort="bogus_field")


async def test_get_dataset_maps_404_to_not_found(httpx_mock):
    """Confirmed live: package_show returns HTTP 404 with
    {"success": false, "error": {"__type": "Not Found Error", ...}}
    for an unknown id -- the same shape as ckan_federal."""
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Not found"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("does-not-exist")


async def test_get_dataset_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_dataset("   ")


async def test_get_dataset_parses_tags_and_groups(httpx_mock):
    """Real value-add over ckan_federal: this portal's packages carry
    populated tags (list of dicts, keyed by `name`) and groups (also
    list of dicts, keyed by `name`) -- confirmed live."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.tags == ["census profiles", "census subdivision"]
    assert result.groups == ["census-profiles"]


async def test_get_dataset_handles_missing_tags_and_groups(httpx_mock):
    """Confirmed live (e.g. the internal-only CWPP-locations dataset):
    a real package can have an empty `groups` array while still
    carrying populated `tags` -- both arrays are independently optional,
    not a package-level bilingual pairing the way ckan_federal's
    `keywords` dict is."""
    obj = {**_PACKAGE_OBJ, "groups": []}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.tags == ["census profiles", "census subdivision"]
    assert result.groups == []


async def test_get_dataset_normalizes_literal_null_string_and_string_bool(httpx_mock):
    """Confirmed live via resource_show: `mimetype` is sometimes the
    literal JSON string "null" rather than a real null, and
    `datastore_active` is sometimes the JSON string "false" rather than
    a real boolean, on resources embedded in the same package."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    resource = result.resources[0]
    assert resource.mimetype is None
    assert resource.datastore_active is False
    assert resource.url is None  # empty string normalized to None
    assert resource.object_name == "WHSE_HUMAN_CULTURAL_ECONOMIC.CEN_PROF_DTL_CSD_ATTRS_2016_SV"


async def test_get_dataset_resource_datastore_active_real_bool(httpx_mock):
    """The same field as a real JSON boolean (confirmed live on sibling
    resources of other packages) must also parse correctly."""
    obj = {
        **_PACKAGE_OBJ,
        "resources": [{**_PACKAGE_OBJ["resources"][0], "datastore_active": True}],
    }
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.resources[0].datastore_active is True


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 1
    assert len(result.resources) == 1
    assert result.organization.name == "bc-stats"
    assert (
        result.landing_page_url == f"https://catalogue.data.gov.bc.ca/dataset/{_PACKAGE_OBJ['id']}"
    )


async def test_list_organizations_uses_package_search_organization_facet(httpx_mock):
    """Confirmed live: organization_list(all_fields=True) is silently
    capped at 25 results on this deployment regardless of limit/rows,
    unlike ckan_federal -- list_organizations() must use
    package_search's `organization` facet instead, which is uncapped."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "count": 0,
                "results": [],
                "search_facets": {
                    "organization": {
                        "title": "organization",
                        "items": [
                            {"name": "bc-stats", "display_name": "BC Stats", "count": 96},
                            {
                                "name": "bc-wildfire-service",
                                "display_name": "BC Wildfire Service",
                                "count": 42,
                            },
                        ],
                    }
                },
            }
        )
    )
    result = await client.list_organizations()
    assert result.total_count == 2
    assert result.organizations[0].name == "bc-stats"
    assert result.organizations[0].package_count == 96


async def test_get_organization_uses_image_display_url_not_image_url(httpx_mock):
    """Confirmed live: `image_url` is a bare uploaded filename fragment
    on this deployment, not a usable URL -- `image_display_url` is the
    real absolute URL and must be what populates OrganizationDetail's
    image_url output field. `url` (the org's own external website) is a
    field ckan_federal's organizations do not carry."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "68bcff90-c51d-4df9-9ecd-fd0bc507e74e",
                "name": "bc-stats",
                "title": "BC Stats",
                "description": "BC Stats is the provincial government's statistical leader.",
                "package_count": 96,
                "image_url": "2018-10-26-000525.036919bc-stats-gov-wordmark.png",
                "image_display_url": "https://catalogue.data.gov.bc.ca/uploads/group/x.png",
                "url": "https://www2.gov.bc.ca/gov/content?id=6A488933DEC8411EBC659A5CD4AA92EF",
            }
        )
    )
    result = await client.get_organization("bc-stats")
    assert result.image_url == "https://catalogue.data.gov.bc.ca/uploads/group/x.png"
    assert (
        result.website_url
        == "https://www2.gov.bc.ca/gov/content?id=6A488933DEC8411EBC659A5CD4AA92EF"
    )


async def test_get_organization_maps_404_to_not_found(httpx_mock):
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Not found"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_organization("not-a-real-org")


async def test_get_resource_wraps_in_resource_detail(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ["resources"][0]))
    result = await client.get_resource("b3b986e5-33bf-46c2-82a7-0b7023d9f9fa")
    assert result.resource.id == "b3b986e5-33bf-46c2-82a7-0b7023d9f9fa"
    assert result.resource.format == "multiple"
    assert result.provenance.source == "ckan-bc"


async def test_list_licenses_has_no_bilingual_counterpart(httpx_mock):
    """Confirmed live: unlike ckan_federal's license_list (which uses
    `title_fra`/`url_fra`), this portal's license_list has no bilingual
    field at all -- `title`/`url` are used as-is. `is_open` is this
    portal's own top-level openness flag, absent from ckan_federal's
    LicenseInfo."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "2",
                    "title": "Open Government Licence - British Columbia",
                    "url": "https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61",
                    "status": "active",
                    "is_open": False,
                    "is_okd_compliant": False,
                    "is_osi_compliant": False,
                }
            ]
        )
    )
    result = await client.list_licenses()
    assert result.licenses[0].title == "Open Government Licence - British Columbia"
    assert result.licenses[0].is_open is False


async def test_list_tags_caps_unfiltered_call(httpx_mock):
    """Confirmed live: tag_list has no server-side rows/limit parameter,
    so an unfiltered call returns the full ~7,087-tag vocabulary --
    must be capped client-side at TAG_LIST_MAX."""
    tags_raw = [
        {"id": str(i), "name": f"tag-{i}", "display_name": f"tag-{i}", "vocabulary_id": None}
        for i in range(constants.TAG_LIST_MAX + 50)
    ]
    httpx_mock.add_response(json=_envelope(tags_raw))
    result = await client.list_tags()
    assert result.total_count == constants.TAG_LIST_MAX + 50
    assert result.truncated is True
    assert len(result.tags) == constants.TAG_LIST_MAX


async def test_list_tags_with_query_is_not_truncated(httpx_mock):
    """tag_list's own `query` substring-match parameter (confirmed live)
    is the intended way to search a specific term -- a filtered result
    under TAG_LIST_MAX must not be marked truncated."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list?all_fields=true&query=wildfire",
        json=_envelope(
            [{"id": "1", "name": "wildfire", "display_name": "wildfire", "vocabulary_id": None}]
        ),
    )
    result = await client.list_tags(query="wildfire")
    assert result.total_count == 1
    assert result.truncated is False
    assert result.tags[0].name == "wildfire"


async def test_list_groups_uses_package_search_groups_facet(httpx_mock):
    """Confirmed live: group_list(all_fields=True) returns HTTP 403 for
    an anonymous request on this deployment (unlike
    organization_list(all_fields=True), which has no such wall) --
    list_groups() must never call group_list(all_fields=True) at all,
    using package_search's `groups` facet instead (public, uncapped)."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "count": 0,
                "results": [],
                "search_facets": {
                    "groups": {
                        "title": "groups",
                        "items": [
                            {
                                "name": "census-profiles",
                                "display_name": "Census Profiles",
                                "count": 30,
                            },
                            {
                                "name": "wildfire-current",
                                "display_name": "Wildfire - Current Season",
                                "count": 2,
                            },
                        ],
                    }
                },
            }
        )
    )
    result = await client.list_groups()
    assert result.total_count == 2
    assert result.groups[0].name == "census-profiles"
    assert result.groups[0].dataset_count == 30
    assert (
        result.groups[0].landing_page_url
        == "https://catalogue.data.gov.bc.ca/group/census-profiles"
    )


async def test_get_group_uses_image_display_url(httpx_mock):
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "af397aae-9da7-4ba5-8801-f9d7cd816454",
                "name": "census-profiles",
                "title": "Census Profiles",
                "description": "Census Profiles present information from the census.",
                "package_count": 30,
                "image_url": "2020-11-26-011225.284217BCGov.png",
                "image_display_url": "https://catalogue.data.gov.bc.ca/uploads/group/x.png",
            }
        )
    )
    result = await client.get_group("census-profiles")
    assert result.image_url == "https://catalogue.data.gov.bc.ca/uploads/group/x.png"
    assert result.package_count == 30


async def test_get_group_maps_404_to_not_found(httpx_mock):
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Not found"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_group("not-a-real-group")


async def test_get_group_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_group("   ")


async def test_unsuccessful_envelope_with_200_status_raises_upstream_error(httpx_mock):
    """Defensive: even though every confirmed-live error case on this
    portal ships a non-2xx HTTP status alongside success=false (same as
    ckan_federal), guard the case where a 200 response nonetheless
    carries success=false rather than trusting the envelope blindly."""
    httpx_mock.add_response(json={"help": "help", "success": False, "result": None})
    with pytest.raises(UpstreamError):
        await client.list_licenses()


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.list_licenses()
