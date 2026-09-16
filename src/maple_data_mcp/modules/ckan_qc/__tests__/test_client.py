"""Tests for modules/ckan_qc/client.py.

Shaped around the real quirks confirmed live against donneesquebec.ca
this session (see client.py's module docstring and the throwaway
smoke script run before these were written, scripts/smoke_test_ckan_qc.py),
not just the happy path: the `{"help","success","result"}` envelope,
the 404/400 error shapes (French `message` text), the absence of any
`_translated`/`_fra` bilingual field anywhere (unlike ckan_federal),
real populated tags/groups (also unlike ckan_federal), the
`image_url`-vs-`image_display_url` trap, the flat "Oui"/"Non"
`spatial_data` field, and license records missing their compliance
flags entirely rather than carrying `false`.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_qc import client, constants
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
        "help": "https://www.donneesquebec.ca/recherche/api/3/action/help_show",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "d2d92b84-4361-42f0-81eb-3c395bc54597",
    "name": "transport-collectif",
    "title": "Transport collectif",
    "notes": "Localisation des arrêts de transport collectif de la Ville de Rimouski.",
    "organization": {
        "id": "6383c687-38a2-4916-a1b9-ff043a3e8a54",
        "name": "ville-de-rimouski",
        "title": "Ville de Rimouski",
    },
    "license_id": "cc-by",
    "license_title": "Attribution (CC-BY 4.0)",
    "license_url": "https://www.donneesquebec.ca/licence/#cc-by",
    "tags": [
        {"id": "t1", "name": "transport", "display_name": "transport", "state": "active"},
        {"id": "t2", "name": "autobus", "display_name": "autobus", "state": "active"},
    ],
    "groups": [
        {
            "id": "2be1c718-4fdc-425f-b09e-263be63735a2",
            "name": "transport",
            "title": "Transport",
            "display_name": "Transport",
            "description": "Transport routier, maritime...",
        }
    ],
    "language": "FR",
    "update_frequency": "asNeeded",
    "spatial_data": "Oui",
    "methodologie": "Projection: EPSG:4326 (WGS 84)",
    "temporal": "2022-12-19",
    "isopen": True,
    "metadata_created": "2022-12-15T20:21:08.611000",
    "metadata_modified": "2026-09-08T14:26:51.883302",
    "num_resources": 1,
    "resources": [
        {
            "id": "bd4021ba-d3ae-4d3b-b8fd-016405166761",
            "package_id": "d2d92b84-4361-42f0-81eb-3c395bc54597",
            "name": "GTFS RimouskiBus",
            "description": "Trajets, arrêts et horaires en format GTFS",
            "format": "GTFS",
            "url": "https://www.donneesquebec.ca/recherche/dataset/x/resource/y/download/gtfs.zip",
            "size": 48760,
            "resource_type": "donnees",
            "datastore_active": False,
            "created": "2022-12-15T20:24:06.024913",
            "last_modified": None,
            "metadata_modified": "2026-09-08T14:26:51.893447",
            "mimetype": "application/zip",
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=transport&rows=10&start=0",
        json=_envelope({"count": 297, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("transport")
    assert result.total_count == 297
    assert result.returned_count == 1
    assert result.packages[0].id == "d2d92b84-4361-42f0-81eb-3c395bc54597"
    assert result.packages[0].organization_name == "ville-de-rimouski"
    assert result.packages[0].resource_formats == ["GTFS"]
    assert result.packages[0].tags == ["transport", "autobus"]
    assert result.packages[0].group_names == ["Transport"]


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
            "&fq=organization%3Amtq&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="organization:mtq", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a
    {"error": {"__type": "Search Query Error", "message": "..."}} body
    for a bad `sort` field -- a caller-input problem, not an upstream
    failure. The message text is in French on this deployment, but
    shared/ckan.py's mapping is status-code-driven, not text-matched."""
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
    {"success": false, "error": {"__type": "Not Found Error",
    "message": "Introuvable"}} for an unknown id -- the French message
    text, unlike ckan_federal's English "Not found"."""
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Introuvable"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("does-not-exist")


async def test_get_dataset_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_dataset("   ")


async def test_get_dataset_lang_is_a_no_op(httpx_mock):
    """Confirmed live: this portal has no _translated/_fra bilingual
    infrastructure at all -- lang must not change the result."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result_en = await client.get_dataset(_PACKAGE_OBJ["id"], lang="en")
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    cache_module._caches.clear()  # force a second real fetch, not a cache hit
    result_fr = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result_en.title == result_fr.title == "Transport collectif"
    assert result_en.notes == result_fr.notes


async def test_get_dataset_parses_qc_specific_fields(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.language == "FR"
    assert result.update_frequency == "asNeeded"
    assert result.has_spatial_data is True
    assert result.methodology == "Projection: EPSG:4326 (WGS 84)"
    assert result.temporal_coverage == "2022-12-19"
    assert result.is_open is True
    assert result.tags == ["transport", "autobus"]
    assert result.groups[0].name == "transport"
    assert result.groups[0].title == "Transport"


async def test_get_dataset_normalizes_spatial_data_non(httpx_mock):
    obj = {**_PACKAGE_OBJ, "spatial_data": "Non"}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.has_spatial_data is False


async def test_get_dataset_normalizes_spatial_data_blank_to_none(httpx_mock):
    """A blank spatial_data value means the field was never filled in,
    not "no" -- must map to None, not False."""
    obj = {**_PACKAGE_OBJ, "spatial_data": ""}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.has_spatial_data is None


async def test_get_dataset_handles_empty_tags_and_groups(httpx_mock):
    """Confirmed live: roughly 5% of sampled packages carry no
    tags/groups at all -- must default to empty lists, not error."""
    obj = {**_PACKAGE_OBJ, "tags": [], "groups": []}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.tags == []
    assert result.groups == []


async def test_get_dataset_resource_has_no_language_field(httpx_mock):
    """Confirmed live: unlike ckan_federal's ResourceInfo, this
    portal's resources carry no `language` field at all -- ResourceInfo
    for ckan_qc has no such attribute as a result."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    resource = result.resources[0]
    assert not hasattr(resource, "language")
    assert resource.resource_type == "donnees"
    assert resource.datastore_active is False


async def test_list_organizations_uses_rich_all_fields_shape(httpx_mock):
    """Confirmed live: unlike ckan_federal, organization_list(all_fields=true)
    here already returns description/image_display_url, the same shape
    organization_show does."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "fb1886c9-2993-46e0-9a10-f9b938a7826f",
                    "name": "mtq",
                    "title": "Ministère des Transports et de la Mobilité durable",
                    "description": "Assurer la mobilité durable.",
                    "package_count": 31,
                    "image_url": "2023-01-27-194316.670080MTMDimprime2coul.png",
                    "image_display_url": (
                        "https://www.donneesquebec.ca/recherche/uploads/group/"
                        "2023-01-27-194316.670080MTMDimprime2coul.png"
                    ),
                }
            ]
        ),
    )
    result = await client.list_organizations()
    assert result.total_count == 1
    org = result.organizations[0]
    assert org.description == "Assurer la mobilité durable."
    # image_url must come from image_display_url, not the raw filename in image_url
    assert org.image_url == (
        "https://www.donneesquebec.ca/recherche/uploads/group/"
        "2023-01-27-194316.670080MTMDimprime2coul.png"
    )


async def test_get_organization_maps_404_to_not_found(httpx_mock):
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Introuvable"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_organization("not-a-real-org")


async def test_get_organization_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_organization("  ")


async def test_get_resource_wraps_in_resource_detail(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ["resources"][0]))
    result = await client.get_resource("bd4021ba-d3ae-4d3b-b8fd-016405166761")
    assert result.resource.id == "bd4021ba-d3ae-4d3b-b8fd-016405166761"
    assert result.resource.format == "GTFS"
    assert result.provenance.source == "ckan-qc"


async def test_list_licenses_handles_missing_compliance_flags(httpx_mock):
    """Confirmed live: this deployment's license records use
    `is_ost_compliant`, not ckan_federal's `is_osi_compliant`, and some
    licenses (e.g. CC0-1.0) omit both compliance flags entirely rather
    than carrying `false` -- must stay None, not be coerced to False."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "cc-by",
                    "title": "Attribution (CC-BY 4.0)",
                    "url": "https://www.donneesquebec.ca/licence/#cc-by",
                    "status": "active",
                    "family": "Creative Commons",
                    "is_okd_compliant": True,
                    "is_ost_compliant": True,
                },
                {
                    "id": "CC0-1.0",
                    "title": "Domaine public (CC0 1.0)",
                    "url": "https://www.donneesquebec.ca/licence/#cc-0",
                    "status": "active",
                    "family": "",
                },
            ]
        )
    )
    result = await client.list_licenses()
    assert result.licenses[0].is_okd_compliant is True
    assert result.licenses[0].is_ost_compliant is True
    assert result.licenses[1].is_okd_compliant is None
    assert result.licenses[1].is_ost_compliant is None
    assert result.licenses[1].family is None  # empty string normalized to None


async def test_list_groups_returns_real_populated_data(httpx_mock):
    """Confirmed live: unlike ckan_federal (group_list confirmed empty),
    this portal's group_list(all_fields=true) returns real thematic
    categories."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "2be1c718-4fdc-425f-b09e-263be63735a2",
                    "name": "transport",
                    "title": "Transport",
                    "description": "Transport routier, maritime, aérien...",
                    "package_count": 202,
                }
            ]
        ),
    )
    result = await client.list_groups()
    assert result.total_count == 1
    assert result.groups[0].name == "transport"
    assert result.groups[0].package_count == 202
    assert result.groups[0].landing_page_url == f"{constants.GROUP_LANDING_URL}transport"


async def test_list_tags_unfiltered_is_truncated(httpx_mock):
    """Confirmed live: the unfiltered tag namespace is large (4,402
    entries) and uncontrolled -- an unfiltered call must be capped at
    TAGS_LIST_MAX with truncated=True, unlike ckan_federal which has no
    tag data to begin with."""
    many_tags = [f"tag-{i}" for i in range(constants.TAGS_LIST_MAX + 50)]
    httpx_mock.add_response(url=f"{constants.BASE_URL}tag_list", json=_envelope(many_tags))
    result = await client.list_tags()
    assert result.total_count == constants.TAGS_LIST_MAX + 50
    assert len(result.tags) == constants.TAGS_LIST_MAX
    assert result.truncated is True
    assert result.query is None


async def test_list_tags_filtered_by_query_is_not_truncated(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list?query=transport",
        json=_envelope(["transport", "Transport", "TRANSPORT", "transport routier"]),
    )
    result = await client.list_tags(query="transport")
    assert result.total_count == 4
    assert result.truncated is False
    assert result.query == "transport"


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
