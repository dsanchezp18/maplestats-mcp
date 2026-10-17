"""Error mapping shared by the portal-family helpers (CKAN, Socrata, Opendatasoft, ArcGIS Hub).

The four helpers used to keep their own status mapping and their own copy of the
French network-error text. A 429 that outlasted the retries was InvalidInput
("rejected the request") in three of them and UpstreamUnavailable in ArcGIS and
WFS; each now follows the same rule (shared/upstream_text.is_unavailable_status)
and takes its network-error wording from upstream_text.network_error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from maplestats_mcp.shared import arcgis, ckan, opendatasoft, socrata
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.i18n import reset_call_lang, set_call_lang
from maplestats_mcp.shared.upstream_text import network_error

_CKAN = ckan.CkanConfig(
    source="ckan-test",
    base_url="https://example.invalid/api/3/action/",
    rate_limit_per_second=100.0,
    rate_limit_capacity=100.0,
)
_SOCRATA = socrata.SocrataConfig(
    source="socrata-test",
    domain="data.example.invalid",
    rate_limit_per_second=100.0,
    rate_limit_capacity=100.0,
)
_ODS = opendatasoft.OpendatasoftConfig(
    source="ods-test",
    domain="data.example.invalid",
    rate_limit_per_second=100.0,
    rate_limit_capacity=100.0,
)
_ARCGIS = arcgis.ArcGISHubConfig(
    source="arcgis-test",
    domain="hub.example.invalid",
    rate_limit_per_second=100.0,
    rate_limit_capacity=100.0,
)

Call = Callable[[str], Awaitable[Any]]


async def _ckan(lang: str) -> Any:
    return await ckan.action(_CKAN, "package_search", lang=lang)


async def _socrata(lang: str) -> Any:
    return await socrata.catalog_search(_SOCRATA, query="x", lang=lang)


async def _ods(lang: str) -> Any:
    return await opendatasoft.search_datasets(_ODS, query="x", lang=lang)


async def _arcgis(lang: str) -> Any:
    return await arcgis.search_items(_ARCGIS, query="x", lang=lang)


PORTALS = [
    pytest.param(_ckan, id="ckan"),
    pytest.param(_socrata, id="socrata"),
    pytest.param(_ods, id="opendatasoft"),
    pytest.param(_arcgis, id="arcgis"),
]
# The context each helper puts in front of its error text.
CONTEXTS: dict[Call, str] = {
    _ckan: "ckan-test:package_search",
    _socrata: "socrata-test:catalog_search",
    _ods: "ods-test:search_datasets",
    _arcgis: "arcgis-test:search_items",
}


@pytest.mark.parametrize("call", PORTALS)
async def test_429_after_retries_is_unavailable_not_invalid_input(httpx_mock, call: Call):
    # shared/http.py retries a 429 three times; every attempt gets the same answer.
    httpx_mock.add_response(status_code=429, json={"message": "slow down"}, is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="temporarily unavailable") as caught:
        await call("en")
    assert "HTTP 429" in str(caught.value)
    assert not isinstance(caught.value, InvalidInput)


@pytest.mark.parametrize("call", PORTALS)
async def test_429_is_unavailable_in_french(httpx_mock, call: Call):
    httpx_mock.add_response(status_code=429, json={"message": "slow down"}, is_reusable=True)
    with pytest.raises(UpstreamUnavailable) as caught:
        await call("fr")
    assert "temporairement indisponible" in str(caught.value)
    assert "HTTP 429" in str(caught.value)


@pytest.mark.parametrize("call", PORTALS)
async def test_other_4xx_is_still_the_callers_mistake(httpx_mock, call: Call):
    httpx_mock.add_response(status_code=400, json={"message": "bad"}, is_reusable=True)
    with pytest.raises(InvalidInput, match="bad"):
        await call("en")


@pytest.mark.parametrize("call", PORTALS)
async def test_404_is_not_found(httpx_mock, call: Call):
    httpx_mock.add_response(status_code=404, json={"message": "nope"}, is_reusable=True)
    with pytest.raises(NotFound):
        await call("en")


@pytest.mark.parametrize("call", PORTALS)
async def test_5xx_stays_upstream_error(httpx_mock, call: Call):
    # Same as ArcGIS Hub and WFS before this change: only a 429 and a 4xx that names
    # the server's own pool failing are read as "unavailable".
    httpx_mock.add_response(status_code=500, json={"message": "boom"}, is_reusable=True)
    with pytest.raises(UpstreamError, match="HTTP 500") as caught:
        await call("en")
    assert not isinstance(caught.value, UpstreamUnavailable)


@pytest.mark.parametrize("call", PORTALS)
async def test_pool_failure_behind_a_4xx_is_unavailable(httpx_mock, call: Call):
    httpx_mock.add_response(
        status_code=400,
        json={"message": "Unable to obtain connection from the pool"},
        is_reusable=True,
    )
    with pytest.raises(UpstreamUnavailable, match="temporarily unavailable"):
        await call("en")


@pytest.mark.parametrize("call", PORTALS)
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("reset by peer"),
        httpx.DecodingError("not json"),
    ],
    ids=["timeout", "connect", "decoding"],
)
async def test_french_network_error_text_lives_in_upstream_text(httpx_mock, call: Call, exc):
    httpx_mock.add_exception(exc, is_reusable=True)
    expected = network_error(CONTEXTS[call], exc, "fr")
    with pytest.raises(type(expected)) as caught:
        await call("fr")
    assert str(caught.value) == str(expected)


@pytest.mark.parametrize("call", PORTALS)
async def test_english_network_error_is_unchanged(httpx_mock, call: Call):
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match=r"did not respond in time \(ReadTimeout\)"):
        await call("en")


@pytest.mark.parametrize("call", PORTALS)
async def test_call_language_applies_when_lang_is_not_passed_down(httpx_mock, call: Call):
    # A tool called with lang="fr" sets the call language; a helper whose caller forgot
    # to hand `lang` on (it defaults to "en") must still answer in French.
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), is_reusable=True)
    token = set_call_lang("fr")
    try:
        with pytest.raises(UpstreamUnavailable) as caught:
            await call("en")
    finally:
        reset_call_lang(token)
    assert "n'a pas répondu à temps" in str(caught.value)


def test_network_error_explicit_lang_beats_an_english_call():
    timeout = httpx.ReadTimeout("slow")
    assert "n'a pas répondu à temps" in str(network_error("x", timeout, "fr"))
    assert "did not respond in time" in str(network_error("x", timeout, "en"))
    assert "did not respond in time" in str(network_error("x", timeout))
