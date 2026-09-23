"""Tests for modules/ckan/client.py.

Fixtures reuse record shapes confirmed live on each portal when its
original per-portal module was written: federal's `_translated` dicts
and `_fra` license fields, BC's literal "null" strings and facet-only
rosters, Québec's French-only extras, Toronto's curated excerpt and
package-level formats, and Yukon's missing DataStore extension.
"""

from __future__ import annotations

import json
from typing import get_args
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from maple_data_mcp.modules.ckan import client, constants
from maple_data_mcp.modules.ckan.schemas import PortalKey
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _ok(result: object) -> dict[str, object]:
    return {"help": "help", "success": True, "result": result}


def _error(kind: str, message: str) -> dict[str, object]:
    return {"help": "help", "success": False, "error": {"__type": kind, "message": message}}


def _query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(request.url)).query)


_FEDERAL_PACKAGE = {
    "id": "fe1b2c3d",
    "name": "fe1b2c3d",
    "title": "Charities Listing",
    "title_translated": {"en": "Charities Listing", "fr": "Liste des organismes de bienfaisance"},
    "notes": "English notes",
    "notes_translated": {"en": "English notes", "fr": "Notes en français"},
    "keywords": {"en": ["charities"], "fr": ["bienfaisance"]},
    "organization": {"id": "org1", "name": "cra-arc", "title": "Canada Revenue Agency"},
    "license_id": "ca-ogl-lgo",
    "license_title": "Open Government Licence - Canada",
    "metadata_modified": "2026-09-01T12:00:00",
    "num_resources": 1,
    "resources": [
        {
            "id": "res1",
            "package_id": "fe1b2c3d",
            "name": "Data",
            "name_translated": {"en": "Data", "fr": "Données"},
            "format": "CSV",
            "url": "https://example.ca/data.csv",
            "size": "1024",
            "language": ["en", "fr"],
            "datastore_active": "false",
        }
    ],
}


def test_portal_key_literal_matches_registry():
    assert set(get_args(PortalKey)) == set(constants.PORTALS)
    assert len(constants.PORTALS) == 10


def test_list_portals_reports_capabilities_in_both_languages():
    en = client.list_portals("en")
    fr = client.list_portals("fr")
    by_key = {p.portal: p for p in en.portals}
    assert by_key["federal"].has_tags is False
    assert by_key["federal"].has_groups is False
    assert by_key["yt"].has_datastore is False
    assert by_key["bc"].has_groups is True
    assert {p.portal: p.name for p in fr.portals}["montreal"].startswith("Données ouvertes")


async def test_unknown_portal_is_invalid_input():
    with pytest.raises(InvalidInput, match="Valid portals"):
        await client.search_datasets("atlantis", "x")


async def test_federal_search_picks_french_and_builds_lang_landing(httpx_mock):
    httpx_mock.add_response(json=_ok({"count": 1, "results": [_FEDERAL_PACKAGE]}))
    result = await client.search_datasets("federal", "charities", lang="fr")
    package = result.packages[0]
    assert package.title == "Liste des organismes de bienfaisance"
    assert package.notes_excerpt == "Notes en français"
    assert package.landing_page_url == "https://open.canada.ca/data/fr/dataset/fe1b2c3d"
    assert result.provenance.source == "ckan-federal"
    request = httpx_mock.get_request()
    assert str(request.url).startswith(constants.PORTALS["federal"].base_url)


async def test_federal_get_dataset_translates_keywords_and_resources(httpx_mock):
    httpx_mock.add_response(json=_ok(_FEDERAL_PACKAGE))
    detail = await client.get_dataset("federal", "fe1b2c3d", lang="fr")
    assert detail.keywords == ["bienfaisance"]
    assert detail.resources[0].name == "Données"
    assert detail.resources[0].size == 1024
    assert detail.resources[0].datastore_active is False
    assert detail.resources[0].language == ["en", "fr"]


async def test_search_rejects_out_of_bounds_paging():
    with pytest.raises(InvalidInput):
        await client.search_datasets("on", rows=0)
    with pytest.raises(InvalidInput):
        await client.search_datasets("on", rows=constants.SEARCH_ROWS_MAX + 1)
    with pytest.raises(InvalidInput):
        await client.search_datasets("on", start=-1)


async def test_search_sends_fq_and_sort(httpx_mock):
    httpx_mock.add_response(json=_ok({"count": 0, "results": []}))
    await client.search_datasets("on", "water", fq="res_format:CSV", sort="metadata_modified desc")
    params = _query(httpx_mock.get_request())
    assert params["fq"] == ["res_format:CSV"]
    assert params["sort"] == ["metadata_modified desc"]


async def test_ontario_extras_use_translated_values(httpx_mock):
    package = {
        "id": "on1",
        "name": "on-dataset",
        "title": "T",
        "organization": {"id": "o", "name": "health", "title": "Health"},
        "access_level": "open",
        "geographic_coverage": "Ontario",
        "geographic_coverage_translated": {"en": "Ontario", "fr": "Ontario (province)"},
        "maintainer": "",
        "resources": [{"id": "r", "url": "u", "data_range_start": "2020-01-01"}],
    }
    httpx_mock.add_response(json=_ok(package))
    detail = await client.get_dataset("on", "on1", lang="fr")
    assert detail.extras == {"access_level": "open", "geographic_coverage": "Ontario (province)"}
    assert detail.resources[0].extras == {"data_range_start": "2020-01-01"}


async def test_bc_null_strings_become_none(httpx_mock):
    package = {
        "id": "bc1",
        "name": "bc-dataset",
        "title": "Wildfire perimeters",
        "organization": {"id": "o", "name": "bcws", "title": "BC Wildfire Service"},
        "license_url": "null",
        "resources": [
            {"id": "r", "url": "https://x", "format": "null", "mimetype": "null"},
        ],
    }
    httpx_mock.add_response(json=_ok(package))
    detail = await client.get_dataset("bc", "bc1")
    assert detail.license_url is None
    assert detail.resources[0].format is None
    assert detail.resources[0].mimetype is None
    assert detail.landing_page_url == "https://catalogue.data.gov.bc.ca/dataset/bc1"


async def test_bc_organizations_come_from_search_facet(httpx_mock):
    httpx_mock.add_response(
        json=_ok(
            {
                "count": 10,
                "results": [],
                "search_facets": {
                    "organization": {
                        "items": [{"name": "bc-stats", "display_name": "BC Stats", "count": 42}]
                    }
                },
            }
        )
    )
    result = await client.list_organizations("bc")
    assert result.organizations[0].title == "BC Stats"
    assert result.organizations[0].package_count == 42
    params = _query(httpx_mock.get_request())
    assert httpx_mock.get_request().url.path.endswith("package_search")
    assert json.loads(params["facet.field"][0]) == ["organization"]


async def test_bc_groups_come_from_search_facet(httpx_mock):
    httpx_mock.add_response(
        json=_ok({"search_facets": {"groups": {"items": [{"name": "health", "count": 3}]}}})
    )
    result = await client.list_groups("bc")
    assert result.groups[0].landing_page_url == "https://catalogue.data.gov.bc.ca/group/health"


async def test_all_fields_organization_list(httpx_mock):
    httpx_mock.add_response(
        json=_ok(
            [{"id": "1", "name": "city-of-regina", "title": "City of Regina", "package_count": 9}]
        )
    )
    result = await client.list_organizations("regina")
    assert result.organizations[0].id == "1"
    assert _query(httpx_mock.get_request())["all_fields"] == ["true"]


async def test_organization_image_prefers_display_url(httpx_mock):
    httpx_mock.add_response(
        json=_ok(
            {
                "id": "o",
                "name": "ville",
                "title": "Ville de Rimouski",
                "image_url": "2020-11-11-154709.png",
                "image_display_url": "https://www.donneesquebec.ca/logo.png",
            }
        )
    )
    detail = await client.get_organization("qc", "ville")
    assert detail.image_url == "https://www.donneesquebec.ca/logo.png"
    assert detail.landing_page_url == "https://www.donneesquebec.ca/recherche/organization/ville"


async def test_quebec_extras_and_name_based_landing(httpx_mock):
    package = {
        "id": "d2d9",
        "name": "transport-collectif",
        "title": "Transport collectif",
        "organization": {"id": "o", "name": "ville-de-rimouski", "title": "Ville de Rimouski"},
        "language": "FR",
        "spatial_data": "Oui",
        "methodologie": "Projection: EPSG:4326",
        "tags": [{"name": "transport"}],
        "groups": [{"name": "transport", "title": "Transport"}],
        "isopen": True,
        "resources": [],
    }
    httpx_mock.add_response(json=_ok(package))
    detail = await client.get_dataset("qc", "transport-collectif", lang="en")
    assert detail.title == "Transport collectif"
    assert detail.extras["spatial_data"] == "Oui"
    assert detail.extras["methodologie"] == "Projection: EPSG:4326"
    assert detail.tags == ["transport"]
    assert detail.groups == ["transport"]
    assert detail.is_open is True
    assert detail.landing_page_url.endswith("/dataset/transport-collectif")


async def test_toronto_summary_uses_excerpt_and_package_formats(httpx_mock):
    package = {
        "id": "uuid-1",
        "name": "bike-share-toronto",
        "title": "Bike Share Toronto",
        "excerpt": "Curated excerpt",
        "notes": "Long notes",
        "formats": ["CSV", "JSON"],
        "organization": {"id": "o", "name": "city-of-toronto", "title": "City of Toronto"},
        "resources": [],
    }
    httpx_mock.add_response(json=_ok({"count": 1, "results": [package]}))
    result = await client.search_datasets("toronto", "bike")
    summary = result.packages[0]
    assert summary.notes_excerpt == "Curated excerpt"
    assert summary.resource_formats == ["CSV", "JSON"]
    assert summary.landing_page_url == "https://open.toronto.ca/dataset/bike-share-toronto/"


async def test_federal_has_no_tags_or_groups():
    with pytest.raises(InvalidInput, match="tags"):
        await client.list_tags("federal")
    with pytest.raises(InvalidInput, match="groups"):
        await client.list_groups("federal")
    with pytest.raises(InvalidInput, match="groups"):
        await client.get_group("toronto", "x")


@pytest.mark.parametrize("portal", ["yt", "ab"])
async def test_portals_without_working_datastore_fail_fast(portal):
    with pytest.raises(InvalidInput, match="DataStore"):
        await client.datastore_search(portal, "res1")


async def test_unfiltered_tags_are_truncated_and_filtered_are_not(httpx_mock):
    tags = [f"tag{i}" for i in range(constants.TAG_LIST_MAX + 5)]
    httpx_mock.add_response(json=_ok(tags))
    result = await client.list_tags("montreal")
    assert result.truncated is True
    assert len(result.tags) == constants.TAG_LIST_MAX
    assert result.total_count == constants.TAG_LIST_MAX + 5

    httpx_mock.add_response(json=_ok([{"id": "1", "name": "velo"}]))
    filtered = await client.list_tags("montreal", query="vel")
    assert filtered.truncated is False
    assert filtered.tags == ["velo"]
    assert _query(httpx_mock.get_requests()[-1])["query"] == ["vel"]


async def test_licenses_use_fra_fields_and_optional_flags(httpx_mock):
    httpx_mock.add_response(
        json=_ok(
            [
                {
                    "id": "ca-ogl-lgo",
                    "title": "Open Government Licence - Canada",
                    "title_fra": "Licence du gouvernement ouvert - Canada",
                    "url": "https://open.canada.ca/en/open-government-licence-canada",
                    "url_fra": "https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada",
                    "is_okd_compliant": True,
                    "domain_data": "True",
                }
            ]
        )
    )
    result = await client.list_licenses("federal", lang="fr")
    lic = result.licenses[0]
    assert lic.title == "Licence du gouvernement ouvert - Canada"
    assert lic.url is not None
    assert lic.url.startswith("https://ouvert.canada.ca/fr/")
    assert lic.is_okd_compliant is True
    assert lic.domain_data is True
    assert lic.is_osi_compliant is None


async def test_404_maps_to_not_found(httpx_mock):
    httpx_mock.add_response(status_code=404, json=_error("Not Found Error", "Introuvable"))
    with pytest.raises(NotFound):
        await client.get_dataset("qc", "does-not-exist")


async def test_toronto_html_404_still_maps_to_not_found(httpx_mock):
    httpx_mock.add_response(status_code=404, text="<html>404 Error</html>")
    with pytest.raises(NotFound):
        await client.get_dataset("toronto", "missing")


async def test_montreal_409_maps_to_invalid_input(httpx_mock):
    httpx_mock.add_response(status_code=409, json=_error("Search Error", "bad fq"))
    with pytest.raises(InvalidInput):
        await client.search_datasets("montreal", fq="((")


async def test_unsuccessful_envelope_is_upstream_error(httpx_mock):
    httpx_mock.add_response(json={"help": "h", "success": False})
    with pytest.raises(UpstreamError):
        await client.get_resource("nt", "r1")


async def test_timeout_is_upstream_unavailable(httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), is_reusable=True)
    with pytest.raises(UpstreamUnavailable):
        await client.get_dataset("ab", "x")


async def test_empty_ids_are_rejected():
    with pytest.raises(InvalidInput):
        await client.get_dataset("on", "  ")
    with pytest.raises(InvalidInput):
        await client.get_organization("on", "")
    with pytest.raises(InvalidInput):
        await client.get_resource("on", " ")
    with pytest.raises(InvalidInput):
        await client.get_group("on", "")


async def test_datastore_search_encodes_filters_and_parses_rows(httpx_mock):
    httpx_mock.add_response(
        json=_ok(
            {
                "records": [{"_id": 1, "Year": "2024"}],
                "fields": [{"id": "_id", "type": "int"}, {"id": "Year", "type": "text"}],
                "total": 57,
            }
        )
    )
    result = await client.datastore_search("federal", "res1", filters={"Year": "2024"}, limit=5)
    assert result.total_count == 57
    assert [f.id for f in result.fields] == ["_id", "Year"]
    assert json.loads(_query(httpx_mock.get_request())["filters"][0]) == {"Year": "2024"}


async def test_datastore_search_rejects_bad_paging():
    with pytest.raises(InvalidInput):
        await client.datastore_search("on", "r", limit=0)
    with pytest.raises(InvalidInput):
        await client.datastore_search("on", "r", limit=constants.DATASTORE_ROWS_MAX + 1)
    with pytest.raises(InvalidInput):
        await client.datastore_search("on", "r", offset=-1)


@pytest.mark.parametrize("portal", sorted(constants.PORTALS))
async def test_every_portal_routes_to_its_own_base_url(portal, httpx_mock):
    httpx_mock.add_response(json=_ok({"count": 0, "results": []}))
    result = await client.search_datasets(portal)
    assert str(httpx_mock.get_request().url).startswith(constants.PORTALS[portal].base_url)
    assert result.provenance.source == f"ckan-{portal}"
