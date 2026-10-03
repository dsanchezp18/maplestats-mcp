"""RDaaS cases shaped like the live API (probed 2026-10-02): the index and
detailed-category endpoints ignore start/limit and return everything (8.3 MB
for NAICS 2022 indexes), facets can be an explicit null, and 5xx must not leak
as raw httpx errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.rdaas import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

_BASE = constants.BASE_URL
_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


def _live_index_graph() -> dict:
    """A 20-entry slice of the live NAICS 2022.1.0 `/indexes` response (captured
    2026-10-02 from api.statcan.gc.ca): the first 12 entries plus 8 whose primary
    term contains "bakery". Real keys, real `@context`, real optional fields
    (`otherExamples`, `illustrativeExamples` present on some entries only)."""
    return json.loads((_FIXTURES / "naics_2022_indexes_slice.json").read_text(encoding="utf-8"))


async def test_indexes_are_paged_and_report_truncation(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/classification/MJRdRiFsfmJAprtT/indexes", json=_live_index_graph()
    )
    result = await client.get_classification_indexes("MJRdRiFsfmJAprtT", limit=5)
    assert len(result.entries) == 5
    assert result.total_count == 20
    assert "5 of 20" in (result.provenance.limits or "")
    first = result.entries[0]
    assert first.index_id == 1
    assert first.primary_term == "general partners (managing), except portfolio management"
    assert first.index_code_value == "551114"
    assert first.other_examples == ["general partners (managing), except portfolio management"]


async def test_indexes_query_and_offset(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/classification/MJRdRiFsfmJAprtT/indexes", json=_live_index_graph()
    )
    result = await client.get_classification_indexes(
        "MJRdRiFsfmJAprtT", query="bakery", limit=5, offset=5
    )
    assert result.total_count == 8
    assert len(result.entries) == 3
    assert result.provenance.limits is None


async def test_indexes_second_page_is_served_from_cache(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/classification/MJRdRiFsfmJAprtT/indexes", json=_live_index_graph()
    )
    await client.get_classification_indexes("MJRdRiFsfmJAprtT", limit=10)
    second = await client.get_classification_indexes("MJRdRiFsfmJAprtT", limit=10, offset=10)
    assert second.provenance.cached is True
    assert len(second.entries) == 10


async def test_index_limit_is_validated():
    with pytest.raises(InvalidInput):
        await client.get_classification_indexes("MJRdRiFsfmJAprtT", limit=100000)


async def test_categories_are_paged(httpx_mock):
    graph = {
        "@graph": [
            {"@id": f"{_BASE}/code/{i}", "code": f"{i:05d}", "descriptor": f"Category {i}"}
            for i in range(250)
        ]
    }
    httpx_mock.add_response(
        url=f"{_BASE}/classification/S049Pjk4RIUgw6j2/categories/detailed?lang=en", json=graph
    )
    result = await client.get_classification_categories_detailed("S049Pjk4RIUgw6j2")
    assert len(result.categories) == constants.DEFAULT_LIST_LIMIT
    assert result.total_count == 250
    narrowed = await client.get_classification_categories_detailed(
        "S049Pjk4RIUgw6j2", query="category 24"
    )
    assert narrowed.total_count == 11


async def test_null_facets_do_not_crash_search(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/search/classifications?start=0&limit=10&lang=en&q=NAICS",
        json={"results": {"@graph": []}, "found": 0, "facets": None},
    )
    result = await client.search_classifications("NAICS")
    assert result.facets.status == {}


async def test_null_facet_members_do_not_crash_search(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/search/concordances?start=0&limit=10&lang=en",
        json={"results": {"@graph": None}, "facets": {"status": None, "audience": None}},
    )
    result = await client.search_concordances()
    assert result.results == []


async def test_status_and_audience_filters_reach_the_query_string(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/search/classifications?start=0&limit=10&lang=en&q=NAICS"
        "&audience=STANDARDS&status=RELEASED",
        json={"results": {"@graph": []}},
    )
    await client.search_classifications("NAICS", audience=["STANDARDS"], status=["RELEASED"])


async def test_5xx_is_unavailable_not_raw_httpx(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}/classification/MJRdRiFsfmJAprtT?lang=en", status_code=503, is_reusable=True
    )
    with pytest.raises(UpstreamUnavailable, match="503"):
        await client.get_classification("MJRdRiFsfmJAprtT")


async def test_invalid_id_and_empty_detail_follow_lang(httpx_mock):
    with pytest.raises(InvalidInput, match="n'est pas un identifiant"):
        await client.get_classification("bad id?", lang="fr")
    with pytest.raises(InvalidInput, match="n'est pas un identifiant"):
        await client.get_concordance("bad id?", lang="fr")
    # A 200 whose object has no "@id" is how RDaaS reports an unknown id.
    httpx_mock.add_response(url=f"{_BASE}/classification/zzzz?lang=fr", json={})
    with pytest.raises(NotFound, match="Aucune classification trouvée"):
        await client.get_classification("zzzz", lang="fr")


async def test_not_found_message_follows_lang(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}/classification/zzzz?lang=fr", status_code=404)
    with pytest.raises(NotFound, match="Aucune ressource"):
        await client.get_classification("zzzz", lang="fr")
