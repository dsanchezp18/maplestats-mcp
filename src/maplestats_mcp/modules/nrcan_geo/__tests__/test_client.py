"""Tests for modules/nrcan_geo/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.nrcan_geo import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_CODES = re.compile(r".*/codes/concise\.json.*")
_NAMES = re.compile(r".*/geonames\.json.*")


async def test_locate_skips_results_without_coordinates(httpx_mock):
    httpx_mock.add_response(
        json=[
            {
                "key": "fsa",
                "name": "K1A",
                "province": "Ontario",
                "category": "Postal Code",
                "lat": 45.44,
                "lng": -75.62,
                "bbox": [-75.63, 45.43, -75.61, 45.45],
            },
            {"key": "locate", "name": "broken", "lat": None, "lng": None},
        ]
    )
    result = await client.locate("K1A 0A9", lang="fr")
    assert [loc.source for loc in result.locations] == ["fsa"]
    params = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert params == {"q": ["K1A 0A9"], "lang": ["fr"]}


async def test_search_names_maps_codes_and_parameters(httpx_mock):
    httpx_mock.add_response(
        url=_NAMES,
        json={
            "items": [
                {
                    "id": "IACYE",
                    "name": "Banff",
                    "concise": {"code": "TOWN"},
                    "status": {"code": "official"},
                    "province": {"code": "48"},
                    "latitude": 51.18,
                    "longitude": -115.57,
                    "location": "25-12-W5",
                    "map": ["082O04"],
                    "decision": "1995-01-01",
                }
            ]
        },
    )
    httpx_mock.add_response(
        url=_CODES, json={"definitions": [{"code": "TOWN", "term": "TOWN-Ville"}]}
    )
    result = await client.search_names(
        "Banff", province="ab", latitude=51.18, longitude=-115.57, limit=5, lang="fr"
    )
    assert result.names[0].feature_type == "TOWN-Ville"
    assert result.names[0].map_sheets == ["082O04"]
    request = next(r for r in httpx_mock.get_requests() if "geonames.json" in str(r.url))
    assert "/geoname/fr/" in str(request.url)
    params = parse_qs(urlparse(str(request.url)).query)
    assert params["province"] == ["48"]
    assert params["radius"] == ["10"]


async def test_search_names_validation():
    with pytest.raises(InvalidInput, match="Give a query"):
        await client.search_names()
    with pytest.raises(InvalidInput):
        await client.search_names("x", province="Atlantis")
    with pytest.raises(InvalidInput):
        await client.search_names(latitude=51.0)
    with pytest.raises(InvalidInput):
        await client.search_names(bbox=[1.0, 2.0])
    with pytest.raises(InvalidInput):
        await client.locate("  ")


async def test_tomcat_404_is_invalid_input(httpx_mock):
    httpx_mock.add_response(url=_NAMES, status_code=404, text="<html>Apache Tomcat</html>")
    with pytest.raises(InvalidInput, match="rejected"):
        await client.search_names("Banff")


# Trimmed from https://geogratis.gc.ca/services/geoname/en/geonames.json?q=Banff&num=3,
# captured 2026-10-03: CRLF-separated JSON, every code wrapped as {"code", "links"},
# `location` present as null (not absent) on parks, extra keys the client ignores.
_LIVE_GEONAMES = (
    b'{\r\n"links":{"self":{"href":"https://geogratis.gc.ca/services/geoname/en/geonames'
    b'?q=Banff&num=3"}},\r\n"items":[\r\n'
    b'{"id":"IACYE","links":{"self":{"href":"https://geogratis.gc.ca/services/geoname/en/'
    b'geonames/IACYE"}},"name":"Banff","language":{"code":"und"},"category":"O",'
    b'"status":{"code":"official","links":{}},"concise":{"code":"TOWN","links":{}},'
    b'"generic":{"code":"2"},"location":"25-12-W5","province":{"code":"48","links":{}},'
    b'"latitude":51.1777778,"longitude":-115.5736111,"map":["082O04","082O00"],'
    b'"relevance":15000000,"bbox":[-115.5936111,51.1577778,-115.5536111,51.1977778],'
    b'"accuracy":100,"position":{"type":"Point","coordinates":[-115.5736111,51.1777778]},'
    b'"decision":"1995-01-01"},\r\n'
    b'{"id":"IATZH","name":"Banff National Park of Canada","category":"O",'
    b'"status":{"code":"official"},"concise":{"code":"PARK"},"location":null,'
    b'"province":{"code":"48"},"latitude":51.6,"longitude":-116.05,'
    b'"map":["082N09","082N01"],"decision":"2001-01-12"}\r\n]\r\n}'
)

# Trimmed from https://geogratis.gc.ca/services/geoname/en/codes/concise.json (2026-10-03).
_LIVE_CONCISE = (
    b'{\r\n"links":{"self":{"href":"https://geogratis.gc.ca/services/geoname/en/codes/concise"}},'
    b'\r\n"definitions":[\r\n'
    b'{"links":{},"code":"TOWN","term":"TOWN-Town","description":"Populated place"},\r\n'
    b'{"links":{},"code":"PARK","term":"PARK-Park","description":"Park"}\r\n]\r\n}'
)

# Trimmed from https://geolocator.api.geo.ca/?q=Banff&lang=en (2026-10-03): `tag` is a list
# of land-description strings or null, every hit here is backed by the "geonames" index.
_LIVE_LOCATE = [
    {
        "key": "geonames",
        "name": "Banff",
        "province": "Alberta",
        "category": "Town",
        "lat": 51.1777778,
        "lng": -115.5736111,
        "bbox": [-115.5936111, 51.1577778, -115.5536111, 51.1977778],
        "tag": ["25-12-W5"],
    },
    {
        "key": "geonames",
        "name": "Banff National Park of Canada",
        "province": "Alberta",
        "category": "National Park",
        "lat": 51.6,
        "lng": -116.05,
        "bbox": [-117.4205484, 50.6559908, -114.9836072, 52.6238334],
        "tag": None,
    },
    {
        "key": "geonames",
        "name": "Parc national du Canada Banff",
        "province": "Alberta",
        "category": "National Park",
        "lat": 51.6,
        "lng": -116.05,
        "bbox": [-117.4205484, 50.6559908, -114.9836072, 52.6238334],
        "tag": None,
    },
]


async def test_search_names_parses_live_shaped_crlf_payload(httpx_mock):
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    httpx_mock.add_response(url=_NAMES, content=_LIVE_GEONAMES, headers=headers)
    httpx_mock.add_response(url=_CODES, content=_LIVE_CONCISE, headers=headers)
    result = await client.search_names("Banff", limit=3)
    assert [n.id for n in result.names] == ["IACYE", "IATZH"]
    town, park = result.names
    assert (town.feature_type, town.status, town.province) == ("TOWN-Town", "official", "48")
    assert town.map_sheets == ["082O04", "082O00"]
    assert town.location == "25-12-W5"
    assert park.location is None
    assert park.feature_type == "PARK-Park"
    assert result.returned_count == 2


async def test_locate_trims_live_shaped_results_to_limit(httpx_mock):
    httpx_mock.add_response(json=_LIVE_LOCATE)
    result = await client.locate("Banff", limit=2)
    assert [loc.name for loc in result.locations] == ["Banff", "Banff National Park of Canada"]
    assert result.locations[0].bbox == [-115.5936111, 51.1577778, -115.5536111, 51.1977778]
    assert result.locations[1].source == "geonames"


async def test_search_names_empty_and_null_lists_give_empty_result(httpx_mock):
    # Live no-match answer (q=zzqqxxnotaplace, 2026-10-03) is "items": []; a null
    # `items`, `map` or `definitions` must not break parsing either.
    httpx_mock.add_response(url=_NAMES, json={"links": {}, "items": None})
    httpx_mock.add_response(url=_CODES, json={"definitions": None})
    result = await client.search_names("zzqqxxnotaplace")
    assert result.names == []
    assert result.returned_count == 0

    cache_module._caches.clear()
    httpx_mock.add_response(
        url=_NAMES,
        json={"items": [{"id": "X1", "name": None, "concise": None, "map": None}]},
    )
    httpx_mock.add_response(url=_CODES, json={"definitions": []})
    result = await client.search_names("x")
    assert result.names[0].name == ""
    assert result.names[0].feature_type is None
    assert result.names[0].map_sheets == []


async def test_upstream_5xx_is_retried_then_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=502, text="<html>Bad Gateway</html>")
    with pytest.raises(UpstreamError, match="HTTP 502"):
        await client.locate("Banff")
    assert len(httpx_mock.get_requests()) == 3


async def test_html_or_non_list_body_is_upstream_error(httpx_mock):
    # A proxy error page served with HTTP 200 is a malformed answer, not a timeout.
    httpx_mock.add_response(text="<html><body>Gateway error</body></html>")
    with pytest.raises(UpstreamError, match="did not return JSON"):
        await client.locate("Banff")

    cache_module._caches.clear()
    httpx_mock.add_response(json={"error": "bad query"})
    with pytest.raises(UpstreamError, match="did not return a list"):
        await client.locate("Banff")


async def test_limit_and_radius_bounds_are_invalid_input():
    with pytest.raises(InvalidInput, match="limit"):
        await client.locate("Banff", limit=0)
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_names("Banff", limit=101)
    with pytest.raises(InvalidInput, match="radius_km"):
        await client.search_names(latitude=51.0, longitude=-115.0, radius_km=501)
