"""A climate-collection query by station that matches no row says why, from climate-stations.

In the Maple Test (2026-11-10) the 1981-2010 normal of Toronto City Centre (6158359),
which opened in 2009, came back as zero rows, and the answer said the normal was not in
the data it could reach instead of that ECCC publishes none.
"""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.eccc import client, constants
from maplestats_mcp.shared import cache as cache_module

_NORMALS_QUERYABLES = {
    "properties": {
        "CLIMATE_IDENTIFIER": {"type": "string"},
        "STATION_NAME": {"type": "string"},
    }
}


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    cache_module._caches.clear()
    yield


def _empty_normals(httpx_mock, query: str, lang: str = "en") -> None:
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/climate-normals/queryables?f=json",
        json=_NORMALS_QUERYABLES,
    )
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/collections/climate-normals/items"
            f"?f=json&lang={lang}&limit=10&offset=0&{query}"
        ),
        json={"type": "FeatureCollection", "features": [], "numberMatched": 0},
    )


def _stations(httpx_mock, query: str, features: list[dict[str, object]], lang: str = "en"):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/collections/climate-stations/items"
            f"?f=json&lang={lang}&limit=5&{query}"
        ),
        json={"type": "FeatureCollection", "features": features},
    )


def _station(climate_id: str, has_normals: str, first: str) -> dict[str, object]:
    # Properties as climate-stations returned them for Toronto City Centre (2026-11-10).
    return {
        "properties": {
            "STATION_NAME": "TORONTO CITY CENTRE",
            "CLIMATE_IDENTIFIER": climate_id,
            "FIRST_DATE": f"{first} 17:00:00",
            "LAST_DATE": "2026-11-08 12:30:10",
            "HAS_NORMALS_DATA": has_normals,
        }
    }


async def test_station_without_normals_says_none_are_published(httpx_mock):
    _empty_normals(httpx_mock, "CLIMATE_IDENTIFIER=6158359")
    _stations(httpx_mock, "CLIMATE_IDENTIFIER=6158359", [_station("6158359", "N", "2009-12-10")])
    result = await client.query_items("climate-normals", filters={"CLIMATE_IDENTIFIER": "6158359"})
    assert result.items == []
    assert result.note is not None
    assert "this station has no climate normals (HAS_NORMALS_DATA = N)" in result.note
    assert "2009-12-10" in result.note


async def test_station_name_shared_by_two_stations_names_both(httpx_mock):
    _empty_normals(httpx_mock, "STATION_NAME=TORONTO+CITY+CENTRE")
    _stations(
        httpx_mock,
        "STATION_NAME=TORONTO+CITY+CENTRE",
        [_station("6158667", "N", "2006-01-01"), _station("6158359", "N", "2009-12-10")],
    )
    result = await client.query_items(
        "climate-normals", filters={"STATION_NAME": "TORONTO CITY CENTRE"}
    )
    assert result.note is not None
    assert "none of these stations has" in result.note
    assert "6158667" in result.note and "6158359" in result.note


async def test_station_with_normals_points_to_the_other_filters(httpx_mock):
    _empty_normals(httpx_mock, "CLIMATE_IDENTIFIER=6158350")
    _stations(httpx_mock, "CLIMATE_IDENTIFIER=6158350", [_station("6158350", "Y", "1840-03-01")])
    result = await client.query_items("climate-normals", filters={"CLIMATE_IDENTIFIER": "6158350"})
    assert result.note is not None
    assert "HAS_NORMALS_DATA = Y" in result.note
    assert "No row of climate-normals matched" in result.note


async def test_unknown_station_id_says_so(httpx_mock):
    _empty_normals(httpx_mock, "CLIMATE_IDENTIFIER=0000000")
    _stations(httpx_mock, "CLIMATE_IDENTIFIER=0000000", [])
    result = await client.query_items("climate-normals", filters={"CLIMATE_IDENTIFIER": "0000000"})
    assert result.note is not None
    assert result.note.startswith("No climate station has CLIMATE_IDENTIFIER = 0000000")


async def test_station_lookup_failure_leaves_the_result_alone(httpx_mock):
    _empty_normals(httpx_mock, "CLIMATE_IDENTIFIER=6158359")
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    result = await client.query_items("climate-normals", filters={"CLIMATE_IDENTIFIER": "6158359"})
    assert result.items == [] and result.note is None


async def test_station_note_in_french(httpx_mock):
    _empty_normals(httpx_mock, "CLIMATE_IDENTIFIER=6158359", lang="fr")
    _stations(
        httpx_mock,
        "CLIMATE_IDENTIFIER=6158359",
        [_station("6158359", "N", "2009-12-10")],
        lang="fr",
    )
    result = await client.query_items(
        "climate-normals", filters={"CLIMATE_IDENTIFIER": "6158359"}, lang="fr"
    )
    assert result.note is not None
    assert "cette station n'a pas de normales climatiques" in result.note


async def test_no_station_lookup_for_other_collections(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/queryables?f=json",
        json={"properties": {"province": {"type": "string"}}},
    )
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/collections/weather-alerts/items"
            "?f=json&lang=en&limit=10&offset=0&province=PE"
        ),
        json={"type": "FeatureCollection", "features": [], "numberMatched": 0},
    )
    result = await client.query_items("weather-alerts", filters={"province": "PE"})
    assert result.note is None
