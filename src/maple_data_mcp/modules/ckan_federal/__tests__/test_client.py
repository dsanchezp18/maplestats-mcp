"""Tests for modules/ckan_federal/client.py.

Shaped around the real quirks confirmed live against open.canada.ca
this session (see client.py's module docstring and the throwaway
smoke script run before these were written), not just the happy path:
the `{"help","success","result"}` envelope, the 404/400 error shapes,
`_translated` dicts missing their "fr" key, organization_list lacking
`title_translated` (unlike organization_show), and license_list's
`_fra`-suffixed fields instead of `_translated`.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.ckan_federal import client, constants
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
        "help": "https://open.canada.ca/data/api/3/action/help_show",
        "success": True,
        "result": result,
    }


_PACKAGE_OBJ = {
    "id": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
    "name": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
    "title": "Climatic Regions",
    "title_translated": {"en": "Climatic Regions", "fr": "Régions climatiques"},
    "notes": "A long description of climatic regions in Canada spanning many sentences of detail.",
    "notes_translated": {
        "en": "A long description of climatic regions in Canada spanning many sentences of detail.",
        "fr": "Une longue description des régions climatiques du Canada.",
    },
    "organization": {
        "id": "9391E0A2-9717-4755-B548-4499C21F917B",
        "name": "nrcan-rncan",
        "title": "Natural Resources Canada | Ressources naturelles Canada",
    },
    "license_id": "ca-ogl-lgo",
    "license_title": "Open Government Licence - Canada",
    "license_url": "https://open.canada.ca/en/open-government-licence-canada",
    "keywords": {"en": ["climate", "meteorology"], "fr": ["climat", "météorologie"]},
    "metadata_created": "2016-09-24T01:31:00.885817",
    "metadata_modified": "2022-03-14T19:51:11.728358",
    "num_resources": 1,
    "resources": [
        {
            "id": "4ec05161-60d1-4fc9-9e7c-487798c19b82",
            "package_id": "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58",
            "name": "Download the English JPG through HTTP",
            "name_translated": {
                "en": "Download the English JPG through HTTP",
                "fr": "Télécharger le fichier en format JPG Anglais via HTTP",
            },
            "description": "",
            "format": "JPG",
            "url": "https://ftp.geogratis.gc.ca/pub/nrcan_rncan/raster/atlas_3_ed/eng/environment/climate/030.jpg",
            "size": 1134541,
            "language": ["en", "fr"],
            "created": "2017-01-26T11:25:44.012952",
            "last_modified": None,
            "metadata_modified": "2017-01-26T11:25:44.012952",
            "mimetype": None,
        }
    ],
}


async def test_search_datasets_parses_real_envelope(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}package_search?q=climate&rows=10&start=0",
        json=_envelope({"count": 2852, "results": [_PACKAGE_OBJ]}),
    )
    result = await client.search_datasets("climate")
    assert result.total_count == 2852
    assert result.returned_count == 1
    assert result.packages[0].id == "09ffaeb5-ec8f-5bb5-bdcb-3436ccf26f58"
    assert result.packages[0].organization_name == "nrcan-rncan"
    assert result.packages[0].resource_formats == ["JPG"]


async def test_search_datasets_notes_excerpt_is_truncated(httpx_mock):
    long_notes = "x" * (constants.NOTES_EXCERPT_LENGTH + 50)
    obj = {**_PACKAGE_OBJ, "notes": long_notes, "notes_translated": {"en": long_notes}}
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
            "&fq=organization%3Astatcan&sort=metadata_modified+desc"
        ),
        json=_envelope({"count": 0, "results": []}),
    )
    result = await client.search_datasets(
        "", fq="organization:statcan", rows=5, sort="metadata_modified desc"
    )
    assert result.total_count == 0
    assert result.packages == []


async def test_search_datasets_maps_400_to_invalid_input(httpx_mock):
    """Confirmed live: package_search returns HTTP 400 with a
    {"error": {"__type": "Search Query Error", ...}} body for a bad
    `sort` field -- a caller-input problem, not an upstream failure."""
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


async def test_get_dataset_maps_404_to_not_found(httpx_mock):
    """Confirmed live: package_show returns HTTP 404 with
    {"success": false, "error": {"__type": "Not Found Error", ...}}
    for an unknown id."""
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


async def test_get_dataset_falls_back_to_english_when_translated_missing_fr(httpx_mock):
    """Confirmed live: a `_translated` dict is occasionally missing its
    "fr" key (~2% of a live 100-dataset sample) but never missing "en"
    -- must fall back to the English value, not raise or return empty."""
    obj = {
        **_PACKAGE_OBJ,
        "title_translated": {"en": "English Only Title"},
        "notes_translated": {"en": "English only notes."},
        "keywords": {"en": ["only-english-keyword"]},
    }
    httpx_mock.add_response(json=_envelope(obj))
    result = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result.title == "English Only Title"
    assert result.notes == "English only notes."
    assert result.keywords == ["only-english-keyword"]


async def test_get_dataset_picks_french_when_available(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"], lang="fr")
    assert result.title == "Régions climatiques"
    assert result.keywords == ["climat", "météorologie"]


async def test_get_dataset_resource_description_falls_back_to_none_when_empty(httpx_mock):
    """Confirmed live: a resource's `description` is frequently an empty
    string rather than null or absent -- normalize to None rather than
    surfacing a meaningless empty string."""
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.resources[0].description is None
    assert result.resources[0].size == 1134541
    assert result.resources[0].last_modified is None


async def test_get_dataset_parses_num_resources_and_resource_list(httpx_mock):
    httpx_mock.add_response(json=_envelope(_PACKAGE_OBJ))
    result = await client.get_dataset(_PACKAGE_OBJ["id"])
    assert result.num_resources == 1
    assert len(result.resources) == 1
    assert result.organization.name == "nrcan-rncan"


async def test_list_organizations_uses_combined_title_not_translated(httpx_mock):
    """Confirmed live: organization_list(all_fields=True), unlike
    organization_show, does not attach a title_translated dict -- title
    is this portal's combined "English | French" string regardless of
    the requested lang."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}organization_list?all_fields=true",
        json=_envelope(
            [
                {
                    "id": "9391E0A2-9717-4755-B548-4499C21F917B",
                    "name": "nrcan-rncan",
                    "title": "Natural Resources Canada | Ressources naturelles Canada",
                    "package_count": 10251,
                }
            ]
        ),
    )
    result = await client.list_organizations(lang="fr")
    assert result.total_count == 1
    assert (
        result.organizations[0].title == "Natural Resources Canada | Ressources naturelles Canada"
    )


async def test_get_organization_uses_title_translated(httpx_mock):
    """Confirmed live: unlike organization_list, organization_show DOES
    attach title_translated -- so lang should actually change the
    result here."""
    httpx_mock.add_response(
        json=_envelope(
            {
                "id": "9391E0A2-9717-4755-B548-4499C21F917B",
                "name": "nrcan-rncan",
                "title": "Natural Resources Canada | Ressources naturelles Canada",
                "title_translated": {
                    "en": "Natural Resources Canada",
                    "fr": "Ressources naturelles Canada",
                },
                "description": "",
                "package_count": 10251,
                "image_url": "",
            }
        )
    )
    result = await client.get_organization("nrcan-rncan", lang="fr")
    assert result.title == "Ressources naturelles Canada"
    assert result.description is None
    assert result.image_url is None


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
    result = await client.get_resource("4ec05161-60d1-4fc9-9e7c-487798c19b82")
    assert result.resource.id == "4ec05161-60d1-4fc9-9e7c-487798c19b82"
    assert result.resource.format == "JPG"
    assert result.provenance.source == "ckan-federal"


async def test_list_licenses_uses_fra_suffix_not_translated(httpx_mock):
    """Confirmed live: license_list records use `title_fra`/`url_fra`,
    a different, older bilingual convention than the `_translated` dict
    package/resource/organization_show records use."""
    httpx_mock.add_response(
        json=_envelope(
            [
                {
                    "id": "ca-ogl-lgo",
                    "title": "Open Government Licence - Canada",
                    "title_fra": "Licence du gouvernement ouvert - Canada",
                    "url": "https://open.canada.ca/en/open-government-licence-canada",
                    "url_fra": "https://open.canada.ca/fr/licence-du-gouvernement-ouvert-canada",
                    "status": "active",
                    "is_okd_compliant": False,
                    "is_osi_compliant": False,
                }
            ]
        )
    )
    result_en = await client.list_licenses(lang="en")
    result_fr = await client.list_licenses(lang="fr")
    assert result_en.licenses[0].title == "Open Government Licence - Canada"
    assert result_fr.licenses[0].title == "Licence du gouvernement ouvert - Canada"
    assert (
        result_fr.licenses[0].url
        == "https://open.canada.ca/fr/licence-du-gouvernement-ouvert-canada"
    )


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
