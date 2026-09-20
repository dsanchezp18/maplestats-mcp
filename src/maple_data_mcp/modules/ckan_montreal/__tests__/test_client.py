"""Tests for modules/ckan_montreal/client.py.

Shaped around the real quirks confirmed live against donnees.montreal.ca
this session (see client.py's module docstring and the throwaway smoke
script scripts/smoke_test_ckan_montreal.py run before these were
written), not just the happy path: the `{"help","success","result"}`
envelope, the 404 error shape (French "Indisponible" message), no
bilingual fields anywhere, real tags/groups usage, `name` != `id`, and
this deployment's distinct license-register field shape.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_montreal import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clear_shared_cache():
    """shared/cache.py's TTLCache buckets are module-level singletons, so
    a cache hit from an earlier test would otherwise silently reuse a
    stale mocked response instead of exercising the next mock -- several
    tests below intentionally reuse the same dataset id/cache key to
    check different `lang` values against it."""
    cache_module._caches.clear()
    yield


def _envelope(result: object) -> dict[str, object]:
    return {
        "help": "https://donnees.montreal.ca/api/3/action/help_show?name=x",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "b89fd27d-4b49-461b-8e54-fa2b34a628c4",
    "name": "arbres",
    "title": "Arbres publics sur le territoire de la Ville",
    "notes": "Données sur les arbres appartenant à la municipalité.",
    "language": "FR",
    "isopen": True,
    "organization": {
        "id": "11287be6-b543-4e28-97b4-99b7111f8de0",
        "name": "ville-de-montreal",
        "title": "Ville de Montréal",
        "type": "organization",
    },
    "license_id": "cc-by",
    "license_title": "Creative Commons Attribution 4.0 International",
    "license_url": "http://creativecommons.org/licenses/by/4.0/",
    "update_frequency": "monthly",
    "tags": [
        {
            "id": "e34531bf-0b19-4376-8488-753fab8a9713",
            "name": "Arbre",
            "display_name": "Arbre",
            "state": "active",
            "vocabulary_id": None,
        },
        {
            "id": "c249e005-4da6-405c-bd98-0cdca9ea6ffa",
            "name": "Foresterie",
            "display_name": "Foresterie",
            "state": "active",
            "vocabulary_id": None,
        },
    ],
    "groups": [
        {
            "id": "a1294878-47b7-47ab-8393-896b90edd3ad",
            "name": "environnement-ressources-naturelles-energie",
            "title": "Environnement, ressources naturelles et énergie",
            "description": "Domaine d'affaires lié aux ressources naturelles.",
        }
    ],
    "metadata_created": "2013-10-17T20:45:22.826827",
    "metadata_modified": "2026-09-16T07:12:36.602495",
    "num_resources": 1,
    "resources": [
        {
            "id": "64e28fe6-ef37-437a-972d-d1d3f1f7d891",
            "package_id": "b89fd27d-4b49-461b-8e54-fa2b34a628c4",
            "name": "Liste des arbres",
            "description": "",
            "format": "CSV",
            "resource_type": "donnees",
            "url": "https://donnees.montreal.ca/dataset/arbres/resource/64e28fe6/download/arbres.csv",
            "size": 10044953,
            "created": "2018-04-30T15:19:29.896594",
            "last_modified": None,
            "metadata_modified": "2026-09-16T07:05:00.166369",
            "mimetype": "",
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=arbres&rows=10&start=0",
        json=_envelope({"count": 13, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("arbres")
    assert result.total_count == 13
    assert result.returned_count == 1
    assert result.packages[0].id == "b89fd27d-4b49-461b-8e54-fa2b34a628c4"
    assert result.packages[0].name == "arbres"
    assert result.packages[0].organization_name == "ville-de-montreal"
    assert result.packages[0].resource_formats == ["CSV"]
    assert result.packages[0].tags == ["Arbre", "Foresterie"]
    assert result.packages[0].is_open is True
    assert result.packages[0].update_frequency == "monthly"


async def test_search_datasets_empty_query_is_match_all(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=&rows=10&start=0",
        json=_envelope({"count": 404, "results": []}),
    )
    result = await client.search_datasets("")
    assert result.total_count == 404
    assert result.query == ""


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
            "&fq=organization%3Aville-de-montreal&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 389, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="organization:ville-de-montreal", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 389
    assert result.packages == []


async def test_search_datasets_unrecognized_sort_does_not_raise(httpx_mock):
    """Confirmed live: unlike ckan_federal (HTTP 400 on a bad sort field),
    this deployment silently ignores an unrecognized `sort` and returns
    HTTP 200 with default ordering -- so this must not raise."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=x&rows=10&start=0&sort=bogus_field_zzz",
        json=_envelope({"count": 70, "results": []}),
    )
    result = await client.search_datasets("x", sort="bogus_field_zzz")
    assert result.total_count == 70


async def test_search_datasets_malformed_fq_maps_409_to_invalid_input(httpx_mock):
    """Confirmed live: a syntactically malformed `fq` returns HTTP 409
    with `{"error": {"__type": "Search Error", ...}}` on this deployment
    -- a different status/type than federal's HTTP 400 "Search Query
    Error", but still a caller-input mistake. shared/ckan.py's action()
    maps every non-404 4xx to InvalidInput for exactly this reason."""
    httpx_mock.add_response(
        status_code=409,
        json={
            "help": "help",
            "error": {"__type": "Search Error", "message": "Search error: malformed fq"},
            "success": False,
        },
    )
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", fq="(((")


async def test_get_dataset_maps_404_to_not_found(httpx_mock):
    """Confirmed live: package_show returns HTTP 404 with
    {"success": false, "error": {"__type": "Not Found Error", "message":
    "Indisponible"}} for an unknown id -- the French error message is
    this deployment's own CKAN instance localization, not a bug."""
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Indisponible"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_dataset("does-not-exist")


async def test_get_dataset_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_dataset("   ")


async def test_get_dataset_name_and_id_can_differ(httpx_mock):
    """Confirmed live: unlike ckan_federal, `name` (URL slug) and `id`
    (UUID) are NOT always identical on this deployment -- both are
    surfaced on PackageDetail rather than assuming one implies the
    other."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset("arbres")
    assert result.id == "b89fd27d-4b49-461b-8e54-fa2b34a628c4"
    assert result.name == "arbres"


async def test_get_dataset_content_identical_across_lang(httpx_mock):
    """Confirmed live: no bilingual `_translated`/`_fra` fields exist on
    this deployment -- `lang` must not change title/notes, only
    landing_page_url's path segment. Only one mocked response is
    registered: get_dataset caches by dataset_id alone (not by lang,
    matching ckan_federal's own cache-key design), so the second call
    below is correctly served from cache rather than a second request --
    that is real production behavior, not a test gap, since
    landing_page_url is still recomputed per-call from the requested
    `lang` after the cache hit."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result_en = await client.get_dataset(_PACKAGE_OBJ["id"], lang="en")
    result_fr = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result_en.title == result_fr.title
    assert result_en.notes == result_fr.notes
    assert result_en.landing_page_url == "https://donnees.montreal.ca/en/dataset/arbres"
    assert result_fr.landing_page_url == "https://donnees.montreal.ca/fr/dataset/arbres"


async def test_get_dataset_parses_tags_and_groups_as_names(httpx_mock):
    """Confirmed live: this deployment genuinely uses tags/groups (unlike
    federal) -- embedded tag/group objects are reduced to plain name
    lists on PackageDetail for compactness."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.tags == ["Arbre", "Foresterie"]
    assert result.groups == ["environnement-ressources-naturelles-energie"]


async def test_get_dataset_resource_description_falls_back_to_none_when_empty(httpx_mock):
    """Confirmed live: a resource's `description` is frequently an empty
    string rather than null or absent -- normalize to None."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.resources[0].description is None
    assert result.resources[0].size == 10044953
    assert result.resources[0].last_modified is None
    assert result.resources[0].resource_type == "donnees"


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 1
    assert len(result.resources) == 1
    assert result.organization is not None
    assert result.organization.name == "ville-de-montreal"


async def test_get_dataset_handles_null_organization(httpx_mock):
    """A package can outlive its organization (deleted/purged) - a null
    "organization" must not crash the detail path the way a bare
    obj["organization"] indexing would."""
    obj = {**_PACKAGE_OBJ, "organization": None}
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.organization is None
    assert result.is_open is True
    assert result.update_frequency == "monthly"


async def test_list_organizations_only_six(httpx_mock):
    """Confirmed live: 6 total organizations -- a small municipal
    roster, unlike federal's ~350."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "11287be6-b543-4e28-97b4-99b7111f8de0",
                    "name": "ville-de-montreal",
                    "title": "Ville de Montréal",
                    "package_count": 389,
                    "description": "Montréal estime que les données ouvertes sont un élément central.",
                }
            ]
        ),
    )
    result = await client.list_organizations()
    assert result.total_count == 1
    assert result.organizations[0].title == "Ville de Montréal"
    assert result.organizations[0].description_excerpt is not None


async def test_get_organization_uses_image_display_url_not_image_url(httpx_mock):
    """Confirmed live: `image_url` is a bare uploaded filename, not a
    usable link -- `image_display_url` is the resolved CDN URL that
    must be surfaced as OrganizationDetail.image_url."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "607d80b4-2523-4ee0-9f68-9bc0e80fdaf3",
                "name": "211-grand-montreal",
                "title": "211 Grand Montréal",
                "description": "",
                "package_count": 1,
                "image_url": "2022-06-17-180502.937876211-grand-montreal.png",
                "image_display_url": "https://donnees.montreal.ca/uploads/group/2022-06-17-180502.937876211-grand-montreal.png",
            }
        )
    )
    result = await client.get_organization("211-grand-montreal")
    assert result.description is None
    assert result.image_url == (
        "https://donnees.montreal.ca/uploads/group/2022-06-17-180502.937876211-grand-montreal.png"
    )


async def test_get_organization_maps_404_to_not_found(httpx_mock):
    httpx_mock.add_response(
        status_code=404,
        json={
            "help": "help",
            "error": {"__type": "Not Found Error", "message": "Indisponible"},
            "success": False,
        },
    )
    with pytest.raises(NotFound):
        await client.get_organization("not-a-real-org")


async def test_get_resource_wraps_in_resource_detail(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ["resources"][0]))
    result = await client.get_resource("64e28fe6-ef37-437a-972d-d1d3f1f7d891")
    assert result.resource.id == "64e28fe6-ef37-437a-972d-d1d3f1f7d891"
    assert result.resource.format == "CSV"
    assert result.provenance.source == "ckan-montreal"


async def test_list_licenses_uses_this_deployments_conformance_fields(httpx_mock):
    """Confirmed live: this deployment's license_list carries
    family/maintainer/domain_*/od_conformance/osd_conformance, not
    federal's is_okd_compliant/is_osi_compliant/status."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "cc-by",
                    "title": "Creative Commons Attribution 4.0 International",
                    "url": "http://creativecommons.org/licenses/by/4.0/",
                    "family": "Creative Commons",
                    "maintainer": "Creative Commons",
                    "domain_content": True,
                    "domain_data": False,
                    "domain_software": False,
                    "od_conformance": "approved",
                    "osd_conformance": "not reviewed",
                }
            ]
        )
    )
    result = await client.list_licenses()
    assert result.licenses[0].family == "Creative Commons"
    assert result.licenses[0].domain_content is True
    assert result.licenses[0].od_conformance == "approved"


async def test_list_tags_returns_plain_names(httpx_mock):
    """Confirmed live: tag_list's default call returns bare name
    strings, not objects -- unlike a package's embedded tags array."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}tag_list",
        json=_envelope(["Arbre", "Foresterie", "Agrile"]),
    )
    result = await client.list_tags()
    assert result.total_count == 3
    assert result.tags == ["Arbre", "Foresterie", "Agrile"]


async def test_list_groups_uses_all_fields(httpx_mock):
    """Confirmed live: this deployment genuinely uses groups (12 real
    ones), unlike federal, which confirmed group_list returns []."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}group_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "6150acd9-9fe4-4c34-b611-65758e2ebc62",
                    "name": "agriculture-alimentation",
                    "title": "Agriculture et alimentation",
                    "description": "Domaine d'affaires correspondant à la mise en valeur.",
                    "package_count": 7,
                }
            ]
        ),
    )
    result = await client.list_groups()
    assert result.total_count == 1
    assert result.groups[0].name == "agriculture-alimentation"
    assert result.groups[0].package_count == 7


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
