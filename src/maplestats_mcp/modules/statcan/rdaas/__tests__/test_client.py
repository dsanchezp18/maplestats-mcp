"""Tests for the RDaaS client against fixtures shaped exactly like the
live responses fetched from api.statcan.gc.ca/rdaas this session
(query "NAICS")."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.rdaas import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_SEARCH_RESPONSE = {
    "results": {
        "@graph": [
            {
                "@id": "https://api.statcan.gc.ca/rdaas/classification/MJRdRiFsfmJAprtT",
                "name": "North American Industry Classification System - Canada",
                "abbreviation": "NAICS",
                "versionNumber": "2022.1.0",
                "audience": "STANDARDS",
                "status": "RELEASED",
                "lastUpdated": "2026-07-21T18:05:44Z",
                "codeCount": 2059,
                "levelCount": 5,
            }
        ]
    },
    "found": 558,
    "start": 0,
    "limit": 1,
    "facets": {"status": {"RELEASED": 476}, "audience": {"STANDARDS": 49}},
}

_DETAIL_RESPONSE = {
    "@id": "https://api.statcan.gc.ca/rdaas/classification/MJRdRiFsfmJAprtT",
    "name": "North American Industry Classification System - Canada",
    "abbreviation": "NAICS",
    "audience": "Standardized",
    "status": "Released",
    "isHarmonized": True,
    "catalogueNumber": "12-501-X",
    "lastUpdated": "2026-07-21T18:05:44.22Z",
    "levels": [
        {
            "@id": "https://api.statcan.gc.ca/rdaas/level/HXVRFoNcmORtJcqf",
            "levelDepth": 1,
            "name": "level 1",
            "codeCount": 20,
        }
    ],
}

_MAPS_RESPONSE = {
    "@graph": [
        {
            "@id": "https://api.statcan.gc.ca/rdaas/codemap/XUDsG2u1SGS8cJSN",
            "maptype": "No Change",
            "sourceCode": "5621",
            "sourceDescriptor": "Waste collection",
            "targetCode": "5621",
            "targetDescriptor": "Waste collection",
        }
    ]
}


async def test_search_classifications_parses_graph_and_facets(httpx_mock):
    httpx_mock.add_response(json=_SEARCH_RESPONSE)
    result = await client.search_classifications("NAICS", limit=1)
    assert result.found == 558
    assert len(result.results) == 1
    assert result.results[0].abbreviation == "NAICS"
    assert result.facets.status["RELEASED"] == 476


async def test_get_classification_accepts_full_url_or_bare_id(httpx_mock):
    httpx_mock.add_response(json=_DETAIL_RESPONSE)
    result = await client.get_classification(
        "https://api.statcan.gc.ca/rdaas/classification/MJRdRiFsfmJAprtT"
    )
    assert result.id.endswith("MJRdRiFsfmJAprtT")
    assert result.is_harmonized is True
    assert len(result.levels) == 1
    assert result.levels[0].level_depth == 1


async def test_get_classification_raises_not_found_when_missing(httpx_mock):
    httpx_mock.add_response(json={})
    with pytest.raises(NotFound):
        await client.get_classification("does-not-exist")


async def test_get_concordance_maps_parses_code_map_entries(httpx_mock):
    httpx_mock.add_response(json=_MAPS_RESPONSE)
    result = await client.get_concordance_maps("COO5gFyeiXnZ04zI")
    assert len(result.maps) == 1
    assert result.maps[0].map_type == "No Change"
    assert result.maps[0].source_code == "5621"


def test_resource_id_normalizes_full_url_to_bare_id():
    assert client._resource_id("https://api.statcan.gc.ca/rdaas/classification/ABC123") == "ABC123"
    assert client._resource_id("ABC123") == "ABC123"


@pytest.mark.parametrize(
    "malicious_id",
    [
        "ABC123?lang=fr&extra=1",
        "ABC123#fragment",
        "ABC 123",
        "ABC:123",
        "",
    ],
)
def test_resource_id_rejects_ids_that_would_inject_into_the_request(malicious_id):
    """A caller-supplied classification/concordance/term-exclusion id is
    interpolated directly into the upstream URL path and the cache key —
    it must not be able to smuggle a query string or fragment into either
    (a "/"-containing value is already reduced to its final segment by the
    URL-normalization above, so that class of traversal is not at risk)."""
    with pytest.raises(InvalidInput):
        client._resource_id(malicious_id)


_CATEGORIES_RESPONSE = {
    "@graph": [
        {
            "@id": "https://api.statcan.gc.ca/rdaas/code/yN1BU0Otk9LyUG24",
            "code": "00010",
            "descriptor": "Legislators",
            "definition": "Legislators participate in the activities of a government.",
            "levelDepth": 6,
            "mainDuties": ["Enact, amend or repeal laws and regulations"],
            "employmentRequirements": ["Election to a legislative body is required."],
        }
    ]
}

_EXCLUSIONS_RESPONSE = {
    "@graph": [
        {
            "@id": "https://api.statcan.gc.ca/rdaas/termexclusion/KmK7aMlM3Es9NDPv",
            "source": "https://api.statcan.gc.ca/rdaas/code/yN1BU0Otk9LyUG24",
            "sourceCodeValue": "00010",
            "term": "Commissioner - government services",
            "target": "https://api.statcan.gc.ca/rdaas/code/QvPHVFiWTfGBWFvw",
            "targetCodeValue": "00011",
        }
    ]
}

_INDEX_ENTRY_JSON = {
    "@id": "https://api.statcan.gc.ca/rdaas/indexentry/nDJuafeBmgLKvvat",
    "indexId": 1,
    "primaryTerm": "general partners (managing), except portfolio management",
    "otherExamples": ["general partners (managing), except portfolio management"],
    "indexCode": "https://api.statcan.gc.ca/rdaas/code/zSbWEnYeffYO9zMQ",
    "indexCodeValue": "551114",
    "indexCodeDescriptor": "Corporate, regional and subsidiary management offices and companies",
}

_TERM_EXCLUSION_RESPONSE = {
    "@id": "https://api.statcan.gc.ca/rdaas/termexclusion/KmK7aMlM3Es9NDPv",
    "source": "https://api.statcan.gc.ca/rdaas/code/yN1BU0Otk9LyUG24",
    "sourceCodeValue": "00010",
    "term": "Commissioner - government services",
    "target": "https://api.statcan.gc.ca/rdaas/code/QvPHVFiWTfGBWFvw",
    "targetCodeValue": "00011",
}


async def test_get_classification_categories_detailed_parses_real_fields(httpx_mock):
    httpx_mock.add_response(json=_CATEGORIES_RESPONSE)
    result = await client.get_classification_categories_detailed("MJRdRiFsfmJAprtT")
    assert len(result.categories) == 1
    cat = result.categories[0]
    assert cat.code == "00010"
    assert cat.descriptor == "Legislators"
    assert cat.level_depth == 6
    assert cat.main_duties == ["Enact, amend or repeal laws and regulations"]


async def test_get_classification_categories_detailed_handles_empty_body(httpx_mock):
    """Reproduces the live NAICS quirk: HTTP 200 with a zero-byte body."""
    httpx_mock.add_response(content=b"")
    result = await client.get_classification_categories_detailed("MJRdRiFsfmJAprtT")
    assert result.categories == []
    assert result.provenance.coverage is not None


async def test_get_classification_exclusions_parses_source_and_target_fields(httpx_mock):
    httpx_mock.add_response(json=_EXCLUSIONS_RESPONSE)
    result = await client.get_classification_exclusions("MJRdRiFsfmJAprtT")
    assert len(result.exclusions) == 1
    excl = result.exclusions[0]
    assert excl.source_code_value == "00010"
    assert excl.target_code_value == "00011"
    assert excl.term == "Commissioner - government services"


async def test_get_classification_exclusions_handles_empty_body(httpx_mock):
    httpx_mock.add_response(content=b"")
    result = await client.get_classification_exclusions("MJRdRiFsfmJAprtT")
    assert result.exclusions == []


async def test_get_classification_indexes_parses_index_entries(httpx_mock):
    httpx_mock.add_response(json={"@graph": [_INDEX_ENTRY_JSON]})
    result = await client.get_classification_indexes("MJRdRiFsfmJAprtT")
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.index_id == 1
    assert entry.primary_term == "general partners (managing), except portfolio management"
    assert entry.index_code_value == "551114"


async def test_get_classification_index_entry_uses_integer_index_id(httpx_mock):
    httpx_mock.add_response(json=_INDEX_ENTRY_JSON)
    result = await client.get_classification_index_entry("MJRdRiFsfmJAprtT", 1)
    assert result.index_id == 1
    assert (
        result.index_code_descriptor
        == "Corporate, regional and subsidiary management offices and companies"
    )


async def test_get_term_exclusion_parses_source_and_target_fields(httpx_mock):
    httpx_mock.add_response(json=_TERM_EXCLUSION_RESPONSE)
    result = await client.get_term_exclusion("KmK7aMlM3Es9NDPv")
    assert result.source_code_value == "00010"
    assert result.target_code_value == "00011"
    assert result.term == "Commissioner - government services"


async def test_get_classification_search_filters_parses_list_shape(httpx_mock):
    """Real shape is a list of {parameter, values} objects, not a dict
    keyed by parameter name — confirmed live."""
    httpx_mock.add_response(
        json=[
            {"parameter": "status", "values": ["RELEASED", "RETIRED"]},
            {"parameter": "audience", "values": ["STANDARDS", "SYSTEM"]},
        ]
    )
    result = await client.get_classification_search_filters()
    assert len(result.filters) == 2
    status_filter = next(f for f in result.filters if f.parameter == "status")
    assert "RELEASED" in status_filter.values


async def test_get_classification_raises_not_found_on_real_404(httpx_mock):
    """The empty-json-200 case above is one way a "not found" surfaces;
    a genuine HTTP 404 (confirmed live for an unknown classification id)
    must also translate to NotFound, not propagate as a raw
    HTTPStatusError."""
    httpx_mock.add_response(status_code=404)
    with pytest.raises(NotFound):
        await client.get_classification("does-not-exist-xyz")


async def test_classification_indexes_send_accept_language(httpx_mock):
    """Index routes ignore ?lang= and only honour Accept-Language (confirmed live)."""
    httpx_mock.add_response(json={"@graph": [_INDEX_ENTRY_JSON]})
    await client.get_classification_indexes("MJRdRiFsfmJAprtT", lang="fr")
    assert httpx_mock.get_request().headers["Accept-Language"] == "fr"
