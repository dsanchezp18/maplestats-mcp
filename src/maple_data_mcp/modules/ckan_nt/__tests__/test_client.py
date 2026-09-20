"""Tests for modules/ckan_nt/client.py.

Shaped around the real quirks confirmed live against opendata.gov.nt.ca
this session (see client.py's module docstring and
scripts/smoke_test_ckan_nt.py, run before these were written), not just
the happy path: the `{"help","success","result"}` envelope, the 404/400
error shapes (identical to ckan_federal's), populated tags/groups arrays
(the opposite of ckan_federal, which has none), the absence of any
bilingual _translated/_fra field, and organization_show's image_url
being a dead bare filename rather than a usable URL (unlike image_display_url).
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_nt import client, constants
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
        "help": "https://opendata.gov.nt.ca/api/3/action/help_show",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "83b99604-aabd-4149-b12e-022cc3ecefea",
    "name": "households",
    "title": "Households",
    "notes": "Households",
    "description": "Households",
    "isopen": False,
    "license_id": "GNWT",
    "license_title": "Open Government Licence Northwest Territories",
    "license_url": "https://www.gov.nt.ca/en/open-government-licence-northwest-territories",
    "topic": "Home and Community",
    "update_frequency": "every5years",
    "source": "Statistics Canada, 2016 Census",
    "geographic_range": "NWT",
    "organization": {
        "id": "ca5e54a2-a161-4ae2-8dac-4d9c25381a99",
        "name": "bureau-of-statistics",
        "title": "Bureau of Statistics",
    },
    "metadata_created": "2022-12-21T21:54:44.236818",
    "metadata_modified": "2023-01-13T00:34:08.902555",
    "num_resources": 1,
    "resources": [
        {
            "id": "efa3e431-481e-4113-90d7-41e9e2a36236",
            "package_id": "83b99604-aabd-4149-b12e-022cc3ecefea",
            "name": "Households",
            "description": None,
            "format": "HTML",
            "url": "https://www.statsnwt.ca/census/2016/",
            "size": None,
            "created": "2022-12-21T21:54:58.488684",
            "last_modified": None,
            "metadata_modified": "2022-12-21T21:54:58.674762",
            "mimetype": None,
        }
    ],
    "tags": [
        {
            "id": "6ed93ef4-5db3-4b46-a1d5-65495195da17",
            "name": "Home and Community",
            "display_name": "Home and Community",
            "state": "active",
            "vocabulary_id": None,
        },
        {
            "id": "54ac78af-a787-4763-927d-092c95fa1d63",
            "name": "housing",
            "display_name": "housing",
            "state": "active",
            "vocabulary_id": None,
        },
    ],
    "groups": [
        {
            "id": "1241b677-a938-4dac-8975-c40fce91a520",
            "name": "home-and-community",
            "title": "Home and Community",
            "description": "Life events, children, family, individuals, property, land, housing",
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=household&rows=10&start=0",
        json=_envelope({"count": 24, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("household")
    assert result.total_count == 24
    assert result.returned_count == 1
    assert result.packages[0].id == "83b99604-aabd-4149-b12e-022cc3ecefea"
    assert result.packages[0].organization_name == "bureau-of-statistics"
    assert result.packages[0].topic == "Home and Community"
    assert result.packages[0].resource_formats == ["HTML"]


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
            "&fq=organization%3Abureau-of-statistics&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="organization:bureau-of-statistics", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a
    {"error": {"__type": "Search Query Error", ...}} body for a bad
    `sort` field -- identical shape to the federal portal."""
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
    for an unknown id -- identical shape to the federal portal."""
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


async def test_get_dataset_parses_tags_as_plain_names(httpx_mock):
    """Confirmed live: unlike ckan_federal (empty tags/groups on every
    package), this portal's packages carry populated tag objects that
    must be reduced to plain names for PackageDetail.tags."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.tags == ["Home and Community", "housing"]


async def test_get_dataset_parses_groups_as_group_refs(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert len(result.groups) == 1
    assert result.groups[0].name == "home-and-community"
    assert result.groups[0].title == "Home and Community"


async def test_get_dataset_surfaces_nt_specific_fields(httpx_mock):
    """topic/update_frequency/source/geographic_range have no
    ckan_federal equivalent -- confirmed live and populated on real
    packages, so PackageDetail carries them through."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.topic == "Home and Community"
    assert result.update_frequency == "every5years"
    assert result.source == "Statistics Canada, 2016 Census"
    assert result.geographic_range == "NWT"
    assert result.is_open is False


async def test_get_dataset_lang_has_no_effect(httpx_mock):
    """Confirmed live: no package record here carries a `_translated`
    dict -- title/notes must be identical regardless of `lang`, unlike
    ckan_federal."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result_en = await client.get_dataset(_PACKAGE_OBJ["id"], lang="en")
    cache_module._caches.clear()
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result_fr = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result_en.title == result_fr.title == "Households"
    assert result_en.notes == result_fr.notes == "Households"


async def test_get_dataset_resource_description_falls_back_to_none_when_empty(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.resources[0].description is None
    assert result.resources[0].size is None
    assert result.resources[0].last_modified is None


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 1
    assert len(result.resources) == 1
    assert result.organization is not None
    assert result.organization.name == "bureau-of-statistics"


async def test_get_dataset_handles_null_organization(httpx_mock):
    """A package can outlive its organization (deleted/purged) - a null
    "organization" must not crash the detail path the way a bare
    obj["organization"] indexing would."""
    obj = {**_PACKAGE_OBJ, "organization": None}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.organization is None


async def test_get_dataset_handles_missing_groups_key(httpx_mock):
    """Some sampled packages omit `groups` entirely rather than sending
    an empty list -- confirmed live on at least one real record -- must
    not raise a KeyError."""
    obj = {k: v for k, v in _PACKAGE_OBJ.items() if k != "groups"}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.groups == []


async def test_list_organizations_uses_plain_title(httpx_mock):
    """Unlike ckan_federal's combined "English | French" organization
    title, this portal's title is a single plain string regardless of
    `lang` -- confirmed live, this portal has no bilingual content."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "ca5e54a2-a161-4ae2-8dac-4d9c25381a99",
                    "name": "bureau-of-statistics",
                    "title": "Bureau of Statistics",
                    "package_count": 290,
                }
            ]
        ),
    )
    result = await client.list_organizations(lang="fr")
    assert result.total_count == 1
    assert result.organizations[0].title == "Bureau of Statistics"


async def test_get_organization_uses_image_display_url_not_image_url(httpx_mock):
    """Confirmed live: organization_show's own `image_url` field is a
    bare uploaded filename ("2022-...StatsBureau.png"), not a usable
    URL -- the absolute, clickable URL is in `image_display_url`
    instead. Getting this wrong would hand an agent a dead link."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "ca5e54a2-a161-4ae2-8dac-4d9c25381a99",
                "name": "bureau-of-statistics",
                "title": "Bureau of Statistics",
                "description": "",
                "package_count": 290,
                "image_url": "2022-12-17-221301.774223StatsBureau.png",
                "image_display_url": (
                    "https://opendata.gov.nt.ca/uploads/group/"
                    "2022-12-17-221301.774223StatsBureau.png"
                ),
            }
        )
    )
    result = await client.get_organization("bureau-of-statistics")
    assert result.image_url == (
        "https://opendata.gov.nt.ca/uploads/group/2022-12-17-221301.774223StatsBureau.png"
    )
    assert result.description is None


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


async def test_list_groups_returns_real_populated_groups(httpx_mock):
    """Confirmed live: unlike ckan_federal (no group concept at all),
    this portal's group_list(all_fields=true) returns real topic
    categories with descriptions and package counts."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "1241b677-a938-4dac-8975-c40fce91a520",
                    "name": "home-and-community",
                    "title": "Home and Community",
                    "description": "Life events, children, family, individuals, property, land, housing",
                    "package_count": 82,
                }
            ]
        ),
    )
    result = await client.list_groups()
    assert result.total_count == 1
    assert result.groups[0].name == "home-and-community"
    assert result.groups[0].package_count == 82
    assert (
        result.groups[0].landing_page_url == "https://opendata.gov.nt.ca/group/home-and-community"
    )


async def test_list_tags_returns_plain_names(httpx_mock):
    """Confirmed live: unlike ckan_federal (empty tag_list), this
    portal's tag_list returns 151 real tag name strings."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["housing", "births", "air quality"]),
    )
    result = await client.list_tags()
    assert result.total_count == 3
    assert result.tags == ["housing", "births", "air quality"]


async def test_get_resource_wraps_in_resource_detail(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ["resources"][0]))
    result = await client.get_resource("efa3e431-481e-4113-90d7-41e9e2a36236")
    assert result.resource.id == "efa3e431-481e-4113-90d7-41e9e2a36236"
    assert result.resource.format == "HTML"
    assert result.provenance.source == "ckan-nt"


async def test_list_licenses_no_fra_suffix_lang_has_no_effect(httpx_mock):
    """Confirmed live: unlike ckan_federal's license_list, no license
    record here carries a `title_fra`/`url_fra` pair -- `lang` must not
    change the result."""
    license_obj = {
        "id": "GNWT",
        "title": "Open Government Licence -  Northwest Territories",
        "url": "https://www.gov.nt.ca/en/open-government-licence-northwest-territories",
        "status": "active",
        "is_okd_compliant": False,
        "is_osi_compliant": False,
    }
    httpx_mock.add_response(json=_envelope([license_obj]))
    result_en = await client.list_licenses(lang="en")
    cache_module._caches.clear()
    httpx_mock.add_response(json=_envelope([license_obj]))
    result_fr = await client.list_licenses(lang="fr")
    assert result_en.licenses[0].title == result_fr.licenses[0].title


async def test_unsuccessful_envelope_with_200_status_raises_upstream_error(httpx_mock):
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
