"""Tests for modules/ckan_yt/client.py.

Shaped around the real quirks confirmed live against open.yukon.ca this
session (see client.py's module docstring and the throwaway smoke
script at scripts/smoke_test_ckan_yt.py, run before these were
written), not just the happy path: the `{"help","success","result"}`
envelope, the 404/400 error shapes (identical to the federal portal's),
embedded tag/group objects (not bare strings), the DKAN-legacy package
fields (custodian/update_frequency/homepage_url/isopen), the absence of
any bilingual field anywhere, and license_list's different openness
taxonomy.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_yt import client, constants
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
        "help": "https://open.yukon.ca/api/3/action/help_show",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "d6fe61d1-71c4-4325-a280-4757fb6c9b8d",
    "name": "mining-districts-1m",
    "title": "Mining districts - 1M",
    "notes": "Mining District Boundaries for the Yukon as defined by the Yukon Placer Mining Act.",
    "custodian": "Mining - Government of Yukon",
    "update_frequency": "ad_hoc",
    "homepage_url": "https://yukon.maps.arcgis.com/home/item.html?id=7bbcd017ffdc45b194ec4bb491aa95aa",
    "isopen": False,
    "language": "",
    "organization": {
        "id": "f8301d90-0290-4456-ad98-df79d33b1bd6",
        "name": "geomatics-yukon",
        "title": "Geomatics Yukon",
    },
    "owner_org": "f8301d90-0290-4456-ad98-df79d33b1bd6",
    "license_id": "OGL-Yukon-2.0",
    "license_title": "Open Government Licence - Yukon",
    "license_url": "https://yukon.ca/en/your-government/open-government/open-government-licence-yukon",
    "metadata_created": "2016-06-15T19:25:01",
    "metadata_modified": "2021-01-03T16:51:24",
    "num_resources": 1,
    "num_tags": 3,
    "groups": [
        {
            "description": "",
            "display_name": "Economics and industry",
            "id": "778ce5c0-fa5b-4d97-9342-e006535772d7",
            "image_display_url": "",
            "name": "economics-and-industry",
            "title": "Economics and industry",
        }
    ],
    "tags": [
        {
            "display_name": "mining",
            "id": "ddf09eca-544c-4cb4-b15e-b9572530a938",
            "name": "mining",
            "state": "active",
            "vocabulary_id": None,
        },
        {
            "display_name": "claims",
            "id": "0af640c1-1ab3-44e0-a0d3-a534c9c62f63",
            "name": "claims",
            "state": "active",
            "vocabulary_id": None,
        },
    ],
    "resources": [
        {
            "cache_last_updated": None,
            "cache_url": None,
            "created": "2016-06-15T19:25:01",
            "description": "",
            "format": "HTML",
            "hash": "",
            "id": "7d7f8c02-0f54-3139-95dd-c27b90077c5f",
            "last_modified": "2021-01-03T16:51:24",
            "metadata_modified": "2021-01-03T16:51:24",
            "mimetype": "text/html",
            "mimetype_inner": None,
            "name": "ArcGIS Online layers",
            "package_id": "d6fe61d1-71c4-4325-a280-4757fb6c9b8d",
            "position": 0,
            "resource_type": None,
            "schema_type": "data",
            "size": None,
            "state": "active",
            "url": "https://yukon.maps.arcgis.com/home/item.html?id=7bbcd017ffdc45b194ec4bb491aa95aa",
            "url_type": "",
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=mining&rows=10&start=0",
        json=_envelope({"count": 562, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("mining")
    assert result.total_count == 562
    assert result.returned_count == 1
    assert result.packages[0].id == "d6fe61d1-71c4-4325-a280-4757fb6c9b8d"
    assert result.packages[0].organization_name == "geomatics-yukon"
    assert result.packages[0].resource_formats == ["HTML"]


async def test_search_datasets_flattens_tag_and_group_objects_to_names(httpx_mock):
    """Confirmed live: a package's `tags`/`groups` arrays hold full
    objects (id/name/display_name/...), not bare strings -- unlike the
    federal portal, which never populates these fields at all."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=x&rows=10&start=0",
        json=_envelope({"count": 1, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("x")
    assert result.packages[0].tags == ["mining", "claims"]
    assert result.packages[0].groups == ["economics-and-industry"]


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
            "&fq=tags%3Amining&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="tags:mining", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a
    {"error": {"__type": "Search Query Error", ...}} body for a bad
    `sort` field -- identical shape to the federal portal's."""
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
    for an unknown id -- identical shape to the federal portal's."""
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


async def test_get_dataset_lang_has_no_effect_on_content_but_changes_landing_url(httpx_mock):
    """Confirmed live: no package record on this deployment carries a
    `_translated`/`_fra` field -- title/notes are identical regardless
    of `lang`. Only `landing_page_url`'s {lang} prefix changes, since
    the site's own UI chrome (not the dataset content) is bilingual.

    Only one mock response is registered: get_dataset's cache key is
    not lang-specific (matching ckan_federal's own convention), so the
    second call below is served from cache -- lang-dependent
    post-processing (here, just landing_page_url) still runs per call
    on the cached raw payload.
    """
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result_en = await client.get_dataset(_PACKAGE_OBJ["id"], lang="en")
    result_fr = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result_en.title == result_fr.title == "Mining districts - 1M"
    assert result_en.landing_page_url == f"https://open.yukon.ca/en/dataset/{_PACKAGE_OBJ['id']}"
    assert result_fr.landing_page_url == f"https://open.yukon.ca/fr/dataset/{_PACKAGE_OBJ['id']}"


async def test_get_dataset_surfaces_dkan_legacy_fields(httpx_mock):
    """Confirmed live: this deployment's package schema carries
    custodian/update_frequency/homepage_url/isopen fields the federal
    portal's package records do not have at all."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.custodian == "Mining - Government of Yukon"
    assert result.update_frequency == "ad_hoc"
    assert result.homepage_url == _PACKAGE_OBJ["homepage_url"]
    assert result.isopen is False


async def test_get_dataset_normalizes_empty_update_frequency_to_none(httpx_mock):
    """Confirmed live: `update_frequency` is frequently an empty string
    rather than null or absent on real records -- normalize to None
    rather than surfacing a meaningless empty string."""
    obj = {**_PACKAGE_OBJ, "update_frequency": ""}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.update_frequency is None


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 1
    assert len(result.resources) == 1
    assert result.resources[0].size is None  # ArcGIS-hosted resource, no file size
    assert result.organization.name == "geomatics-yukon"


async def test_list_organizations_parses_all_fields(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "f8301d90-0290-4456-ad98-df79d33b1bd6",
                    "name": "geomatics-yukon",
                    "title": "Geomatics Yukon",
                    "package_count": 420,
                }
            ]
        ),
    )
    result = await client.list_organizations()
    assert result.total_count == 1
    assert result.organizations[0].title == "Geomatics Yukon"
    assert result.organizations[0].package_count == 420


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
    result = await client.get_resource("7d7f8c02-0f54-3139-95dd-c27b90077c5f")
    assert result.resource.id == "7d7f8c02-0f54-3139-95dd-c27b90077c5f"
    assert result.resource.format == "HTML"
    assert result.provenance.source == "ckan-yt"


async def test_list_licenses_uses_openness_taxonomy_not_okd_osi_flags(httpx_mock):
    """Confirmed live: this deployment's license_list records carry
    family/maintainer/domain_*/od_conformance/osd_conformance fields,
    not the federal portal's is_okd_compliant/is_osi_compliant
    booleans, and no _fra-suffixed field either."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "OGL-Yukon-2.0",
                    "title": "Open Government Licence - Yukon",
                    "url": "https://yukon.ca/en/your-government/open-government/open-government-licence-yukon",
                    "status": "active",
                    "family": "",
                    "maintainer": "Government of Yukon",
                    "domain_content": True,
                    "domain_data": True,
                    "domain_software": False,
                    "od_conformance": "not reviewed",
                    "osd_conformance": "not reviewed",
                }
            ]
        )
    )
    result = await client.list_licenses()
    lic = result.licenses[0]
    assert lic.title == "Open Government Licence - Yukon"
    assert lic.family is None
    assert lic.maintainer == "Government of Yukon"
    assert lic.domain_content is True
    assert lic.domain_software is False
    assert lic.od_conformance == "not reviewed"


async def test_list_tags_returns_plain_name_list(httpx_mock):
    """Confirmed live: this deployment's tag_list is genuinely
    populated (914 names) -- the federal portal's equivalent call
    always returns []."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["mining", "claims", "geoyukon"]),
    )
    result = await client.list_tags()
    assert result.total_count == 3
    assert result.tags == ["mining", "claims", "geoyukon"]


async def test_list_groups_parses_all_fields(httpx_mock):
    """Confirmed live: this deployment defines 17 subject-category
    groups -- the federal portal has none at all."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "778ce5c0-fa5b-4d97-9342-e006535772d7",
                    "name": "economics-and-industry",
                    "title": "Economics and industry",
                    "description": "",
                    "package_count": 102,
                }
            ]
        ),
    )
    result = await client.list_groups()
    assert result.total_count == 1
    assert result.groups[0].name == "economics-and-industry"
    assert result.groups[0].description is None
    assert result.groups[0].package_count == 102


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
