from __future__ import annotations

import pytest

from maplestats_mcp.modules.ised.cipo import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SAMPLE_DOC = {
    "id": "1137536",
    "appNo": "1137536",
    "st13ApplicationNumber": None,
    "intlRegNos": [None],
    "mediaFileNames": ["/media/1137536.png"],
    "niceCodes": [29, 30, 35, 43],
    "cipoStatuses": [],
    "markName": "Les Délices de l'Érable & DESSIN",
    "statusCode": 13,
    "statusDesc": "EXPUNGED",
    "markTypeCodes": [],
    "type": "Design",
    "lang": None,
}


async def test_search_trademarks_parses_records(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 24651, "docs": [_SAMPLE_DOC]})
    result = await client.search_trademarks("all", "maple", max_return=5)
    assert result.total_matched == 24651
    assert result.returned_count == 1
    record = result.records[0]
    assert record.application_number == "1137536"
    assert record.mark_name == "Les Délices de l'Érable & DESSIN"
    assert record.status_description == "EXPUNGED"
    assert record.nice_classes == [29, 30, 35, 43]
    assert record.image_urls == [f"{constants.MEDIA_BASE_URL}/media/1137536.png"]
    # a lone `null` entry in intlRegNos means "no international registration"
    assert record.international_registration_numbers == []


async def test_search_trademarks_sends_expected_body(httpx_mock):
    httpx_mock.add_response(
        url=constants.BASE_URL, json={"numFound": 1, "docs": [_SAMPLE_DOC]}, method="POST"
    )
    await client.search_trademarks("trademark", "maple", max_return=10)
    request = httpx_mock.get_requests()[0]
    import json as json_module

    body = json_module.loads(request.content)
    assert body["searchfield1"] == "tm"
    assert body["textfield1"] == "maple"
    assert body["maxReturn"] == "10"
    assert body["display"] == "list"


async def test_search_trademarks_empty_criteria_is_match_all(httpx_mock):
    httpx_mock.add_response(
        url=constants.BASE_URL, json={"numFound": 2185568, "docs": [_SAMPLE_DOC]}
    )
    result = await client.search_trademarks("all", "", max_return=1)
    assert result.total_matched == 2185568


async def test_invalid_search_field_raises_invalid_input():
    with pytest.raises(InvalidInput):
        await client.search_trademarks("not_a_real_field", "maple")


async def test_max_return_out_of_range_raises_invalid_input():
    with pytest.raises(InvalidInput):
        await client.search_trademarks("all", "maple", max_return=0)
    with pytest.raises(InvalidInput):
        await client.search_trademarks("all", "maple", max_return=constants.MAX_RETURN_MAX + 1)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=constants.BASE_URL, status_code=500)
    with pytest.raises(UpstreamError):
        await client.search_trademarks("all", "maple")


async def test_unexpected_response_shape_becomes_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL, json={"unexpected": "shape"})
    with pytest.raises(UpstreamError):
        await client.search_trademarks("all", "maple")
