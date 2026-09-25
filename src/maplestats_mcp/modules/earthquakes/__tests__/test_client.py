"""Tests for modules/earthquakes/client.py, shaped on the FDSN text format."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.earthquakes import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# Real shape, captured live 2026-09-24.
_TEXT = (
    "#EventID|Time|Latitude|Longitude|Depth/km|MagType|Magnitude|EventLocationName\n"
    "20260901.1000001|2026-09-01T10:00:00.500Z|49.3|-123.1|12|ML|2.4|"
    "10 km W of Vancouver, BC/10 km O de Vancouver, BC\n"
    "20260910.0315002|2026-09-10T03:15:00.000Z|48.9|-124.0|30.1|Mw'|3.1|"
    "Vancouver Island, BC/Île de Vancouver, BC\n"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_search_parses_by_header_newest_first_and_sends_params(httpx_mock):
    httpx_mock.add_response(text=_TEXT)
    result = await client.search(
        start="2026-09-01",
        end="2026-09-20",
        min_magnitude=2,
        latitude=49.28,
        longitude=-123.12,
        radius_km=111.19,
        limit=1,
    )
    assert result.total_matches == 2 and result.returned_count == 1
    quake = result.earthquakes[0]
    assert quake.event_id == "20260910.0315002"
    assert quake.time == datetime(2026, 9, 10, 3, 15, tzinfo=UTC)
    assert (quake.magnitude, quake.magnitude_type, quake.depth_km) == (3.1, "Mw'", 30.1)
    assert quake.location == "Vancouver Island, BC"
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query["starttime"] == ["2026-09-01T00:00:00"]
    assert query["maxradius"] == ["1.0"]
    assert query["format"] == ["text"]


async def test_no_data_statuses_are_empty(httpx_mock):
    httpx_mock.add_response(status_code=204)
    assert (await client.search(start="2026-09-01", end="2026-09-02")).total_matches == 0
    httpx_mock.add_response(status_code=204)
    with pytest.raises(NotFound):
        await client.search(event_id="20260901.1000")


async def test_event_id_queries_by_minute_then_matches_exactly(httpx_mock):
    httpx_mock.add_response(text=_TEXT)
    result = await client.search(event_id="20260910.0315002", lang="fr")
    assert [q.event_id for q in result.earthquakes] == ["20260910.0315002"]
    assert result.earthquakes[0].location == "Île de Vancouver, BC"
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query["eventid"] == ["20260910.0315"]


async def test_422_is_invalid_input(httpx_mock):
    httpx_mock.add_response(status_code=422, json={"errors": [{"msg": "bad"}]})
    with pytest.raises(InvalidInput):
        await client.search(start="2026-09-01", end="2026-09-02", min_magnitude=-99)


async def test_validation():
    with pytest.raises(InvalidInput):
        await client.search(start="2026-09-10", end="2026-09-01")
    with pytest.raises(InvalidInput):
        await client.search(latitude=49.0)
    with pytest.raises(InvalidInput):
        await client.search(bbox=(10, 50, -10, 40))
    with pytest.raises(InvalidInput):
        await client.search(event_id="nope1")
    with pytest.raises(InvalidInput):
        await client.search(start="2000-01-01", end="2026-01-01")
