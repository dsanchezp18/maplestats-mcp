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


def _sent_body(httpx_mock) -> dict:
    import json as json_module

    return json_module.loads(httpx_mock.get_requests()[-1].content)


async def test_nice_classes_go_in_nicetextfield1_as_a_list(httpx_mock):
    # Live 2026-10-03: textfield1="45" matched the whole register (2,188,587);
    # nicetextfield1=["45"] matched 97,515 marks, each listing class 45.
    httpx_mock.add_response(
        url=constants.BASE_URL,
        json={"numFound": 97515, "docs": [{**_SAMPLE_DOC, "niceCodes": [45]}]},
    )
    result = await client.search_trademarks("nice_classification", "45, 9", max_return=3)
    body = _sent_body(httpx_mock)
    assert body["searchfield1"] == "nice_for_search"
    assert body["textfield1"] == ""
    assert body["nicetextfield1"] == ["9", "45"]
    assert result.total_matched == 97515
    assert result.criteria == "45, 9"


@pytest.mark.parametrize("criteria", ["abc", "46", "-1", "9 x"])
async def test_bad_nice_class_raises_before_sending(httpx_mock, criteria):
    with pytest.raises(InvalidInput):
        await client.search_trademarks("nice_classification", criteria)
    assert httpx_mock.get_requests() == []


async def test_cipo_status_names_map_to_the_form_codes(httpx_mock):
    # "REGISTERED" in textfield1 answered HTTP 500 live; the form sends codes.
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 11350, "docs": []})
    await client.search_trademarks("cipo_status", "approved, 19")
    body = _sent_body(httpx_mock)
    assert body["textfield1"] == ""
    assert body["cipotextfield1"] == ["4", "17", "19"]


async def test_unknown_cipo_status_raises(httpx_mock):
    # Code 12 is the results' statusCode for REGISTERED, not a filter code.
    with pytest.raises(InvalidInput):
        await client.search_trademarks("cipo_status", "12")
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    ("field", "criteria"),
    [
        ("application_number", "abc"),
        ("original_application_number", "12a"),
        ("international_registration_number", "abc"),
        ("registration_number", "abc"),
        ("registration_number", "TMA"),
    ],
)
async def test_non_numeric_number_fields_raise(httpx_mock, field, criteria):
    with pytest.raises(InvalidInput):
        await client.search_trademarks(field, criteria)
    assert httpx_mock.get_requests() == []


async def test_number_fields_drop_thousands_separators(httpx_mock):
    # "1,244,495" matched nothing live; the bare digits match.
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 1, "docs": [_SAMPLE_DOC]})
    await client.search_trademarks("application_number", "1,244,495")
    assert _sent_body(httpx_mock)["textfield1"] == "1244495"
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 1, "docs": [_SAMPLE_DOC]})
    await client.search_trademarks("registration_number", "TMA700,000")
    assert _sent_body(httpx_mock)["textfield1"] == "TMA700,000"


async def test_french_invalid_field_is_french():
    with pytest.raises(InvalidInput) as excinfo:
        await client.search_trademarks("not_a_real_field", "maple", lang="fr")
    message = str(excinfo.value)
    assert message.startswith("Entrée invalide : ised_cipo:search_trademarks :")
    assert "search_field doit valoir" in message


async def test_french_limits_are_french_and_spaced(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 1, "docs": [_SAMPLE_DOC]})
    result = await client.search_trademarks("all", "maple", max_return=5, lang="fr")
    limits = result.provenance.limits or ""
    assert limits.startswith("Requête : POST")
    assert "qu'en anglais ;" in limits
    assert "No pagination" not in limits


async def test_english_limits_unchanged(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL, json={"numFound": 1, "docs": [_SAMPLE_DOC]})
    result = await client.search_trademarks("all", "maple", max_return=5)
    assert (result.provenance.limits or "").startswith(f"Request: POST {constants.BASE_URL}")


async def test_french_bad_nice_class_is_french(httpx_mock):
    with pytest.raises(InvalidInput) as excinfo:
        await client.search_trademarks("nice_classification", "46", lang="fr")
    assert "les classes de Nice vont de 0 à 45" in str(excinfo.value)
    assert httpx_mock.get_requests() == []
