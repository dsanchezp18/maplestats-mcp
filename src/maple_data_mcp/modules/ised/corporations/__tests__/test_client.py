from __future__ import annotations

import pytest

from maple_data_mcp.modules.ised.corporations import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_ENGLISH_RECORD = {
    "corporationId": "1007",
    "act": "Boards of Trade Act - Part II",
    "status": "Active",
    "corporationNames": [
        {
            "CorporationName": {
                "name": "Abbotsford Chamber of Commerce",
                "nameType": "Primary",
                "current": True,
                "effectiveDate": "1995-02-06",
            }
        }
    ],
    "adresses": [
        {
            "address": {
                "addressLine": ["207 - 32900 SOUTH FRASER WAY"],
                "city": "ABBOTSFORD",
                "postalCode": "V2S 5A1",
                "provinceCode": "BC",
                "countryCode": "CA",
                "typeCode": "2",
                "current": True,
            }
        }
    ],
    "directorLimits": {"minimum": 3, "maximum": 30},
    "businessNumbers": {"businessNumber": "106679285"},
    "annualReturns": [
        {"annualReturn": {"annualMeetingdate": "2026-03-25", "yearOfFiling": "2026"}}
    ],
    "activities": [{"activity": {"activity": "Incorporation", "date": "1947-01-10"}}],
}


async def test_get_corporation_by_id_parses_english_record(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/1007.json?lang=eng",
        json=[_ENGLISH_RECORD, None],
    )
    result = await client.get_corporation("1007")
    assert result.corporation_id == "1007"
    assert result.status == "Active"
    assert result.business_number == "106679285"
    assert result.names[0].name == "Abbotsford Chamber of Commerce"
    assert result.addresses[0].city == "ABBOTSFORD"
    assert result.director_limits is not None
    assert result.director_limits.maximum == 30
    assert result.annual_returns[0].year_of_filing == "2026"
    assert result.activities[0].activity == "Incorporation"


async def test_get_corporation_by_business_number_uses_same_endpoint(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/106679285.json?lang=eng",
        json=[_ENGLISH_RECORD, None],
    )
    result = await client.get_corporation("106679285")
    assert result.corporation_id == "1007"


async def test_french_lang_reads_second_slot(httpx_mock):
    french_record = {**_ENGLISH_RECORD, "act": "Loi sur les chambres de commerce - partie II"}
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/1007.json?lang=fra",
        json=[None, french_record],
    )
    result = await client.get_corporation("1007", lang="fr")
    assert result.act == "Loi sur les chambres de commerce - partie II"


async def test_falls_back_to_other_slot_when_requested_language_is_null(httpx_mock):
    """Confirmed live: the API can return the matching-language slot as
    `null` while the other slot still holds real data -- the client
    must not treat that as a not-found result."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/1007.json?lang=fra",
        json=[_ENGLISH_RECORD, None],
    )
    result = await client.get_corporation("1007", lang="fr")
    assert result.corporation_id == "1007"


async def test_not_found_body_is_a_pair_of_strings_not_an_http_error(httpx_mock):
    """Confirmed live: an unmatched id/business number returns HTTP 200
    with a two-string-element body, not a 404."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/999999999999.json?lang=eng",
        status_code=200,
        json=["could not find corporation 999999999999", "Corporation 999999999999 est inconnu."],
    )
    with pytest.raises(NotFound):
        await client.get_corporation("999999999999")


async def test_invalid_input_rejects_empty_and_non_numeric_input():
    with pytest.raises(InvalidInput):
        await client.get_corporation(" ")
    with pytest.raises(InvalidInput):
        await client.get_corporation("not-a-number")


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=f"{constants.BASE_URL}/1007.json?lang=eng", status_code=500)
    with pytest.raises(UpstreamError):
        await client.get_corporation("1007")
