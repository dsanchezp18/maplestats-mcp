"""Tests for modules/dfo_iwls/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maple_data_mcp.modules.dfo_iwls import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_STATIONS_URL = re.compile(re.escape(constants.BASE_URL) + r"/stations$")
_VICTORIA = {
    "code": "07120",
    "id": "5cebf1df3d0f4a073c4bbd1e",
    "latitude": 48.424363,
    "longitude": -123.370828,
    "officialName": "Victoria Harbour",
    "operating": True,
    "type": "PERMANENT",
    "timeSeries": [
        {
            "code": "wlo",
            "nameEn": "Water level official value",
            "nameFr": "Niveau d'eau, valeur officielle",
        },
        {
            "code": "wlp",
            "nameEn": "Water level predictions",
            "nameFr": "Prédictions de niveaux d'eau",
        },
        {
            "code": "wlp-hilo",
            "nameEn": "High and Low Tide Predictions",
            "nameFr": "Prédictions de pleines et basses mers",
        },
    ],
}
_CLOSED = {
    "code": "04315",
    "id": "5cebf1dd3d0f4a073c4bb8c3",
    "officialName": "Tasiujaq",
    "alternativeName": "Leaf Basin",
    "operating": False,
    "timeSeries": [{"code": "wlo", "nameEn": "Water level official value"}],
}


async def test_search_filters_operating_and_matches_alternative_name(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA, _CLOSED])
    result = await client.search_stations("victoria")
    assert [s.code for s in result.stations] == ["07120"]
    assert (await client.search_stations("leaf")).total_matches == 0
    closed = await client.search_stations("leaf", operating_only=False, lang="fr")
    assert closed.stations[0].time_series[0].name == "Water level official value"


async def test_get_water_levels_hilo_omits_resolution(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        json=[
            {
                "eventDate": "2026-09-23T02:40:00Z",
                "qcFlagCode": "1",
                "reviewed": False,
                "value": 2.181,
            },
            {
                "eventDate": "2026-09-23T14:52:00Z",
                "qcFlagCode": "1",
                "reviewed": False,
                "value": 0.922,
            },
        ]
    )
    result = await client.get_water_levels(
        "7120",
        "wlp-hilo",
        start="2026-09-23",
        end="2026-09-24",
        resolution="SIXTY_MINUTES",
        lang="fr",
    )
    assert result.series_name == "Prédictions de pleines et basses mers"
    assert [p.value for p in result.points] == [2.181, 0.922]
    assert result.resolution is None
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert "resolution" not in params
    assert params["from"] == ["2026-09-23T00:00:00Z"]


async def test_get_water_levels_sends_resolution_for_regular_series(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    await client.get_water_levels(
        "07120", "wlp", start="2026-09-23", end="2026-09-24", resolution="SIXTY_MINUTES"
    )
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["resolution"] == ["SIXTY_MINUTES"]


async def test_window_over_seven_days_is_rejected_before_calling(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    with pytest.raises(InvalidInput, match="7 days"):
        await client.get_water_levels("07120", "wlp", start="2026-09-01", end="2026-09-30")


async def test_unknown_series_and_station(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    with pytest.raises(InvalidInput, match="available"):
        await client.get_water_levels("07120", "wlf")
    with pytest.raises(NotFound):
        await client.get_station("99999")
    with pytest.raises(InvalidInput):
        await client.get_station("victoria")


async def test_upstream_400_maps_to_invalid_input(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        status_code=400,
        json={
            "status": "400 BAD_REQUEST",
            "message": "Wrong parameter format",
            "errors": ["from is improperly formatted"],
        },
    )
    with pytest.raises(InvalidInput, match="improperly formatted"):
        await client.get_water_levels("07120", "wlo", start="2026-09-23", end="2026-09-24")


async def test_get_station_reads_datums(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        json={
            "chsRegionCode": "PAC",
            "isTidal": True,
            "isTideTableReferencePort": True,
            "establishedYear": 1905,
            "datums": [{"code": "CGVD2013", "offset": -1.71}],
        }
    )
    detail = await client.get_station("07120")
    assert detail.region_code == "PAC"
    assert detail.datums[0].offset == -1.71
