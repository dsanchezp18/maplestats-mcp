"""Tests for modules/nrcan_geo/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.nrcan_geo import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput


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
