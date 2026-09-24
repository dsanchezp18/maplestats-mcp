"""Tests for modules/earthquakes/client.py, shaped on the FDSN text format."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from maple_data_mcp.modules.earthquakes import client
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound

_TEXT = (
    "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|"
    "MagType|Magnitude|MagAuthor|EventLocationName\n"
    "20260901a|2026-09-01T10:00:00.5|49.3|-123.1|12.0|NRCan|NRCan|NRCan|x|ML|2.4|NRCan|"
    "10 km W of Vancouver, BC\n"
    "20260910b|2026-09-10T03:15:00|48.9|-124.0|30.1|NRCan|NRCan|NRCan|y|Mw|3.1|NRCan|"
    "Vancouver Island, BC\n"
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
    assert quake.event_id == "20260910b"
    assert quake.time == datetime(2026, 9, 10, 3, 15, tzinfo=UTC)
    assert (quake.magnitude, quake.magnitude_type, quake.depth_km) == (3.1, "Mw", 30.1)
    query = parse_qs(urlparse(str(httpx_mock.get_request().url)).query)
    assert query["starttime"] == ["2026-09-01T00:00:00"]
    assert query["maxradius"] == ["1.0"]
    assert query["format"] == ["text"]


async def test_no_data_statuses_are_empty(httpx_mock):
    httpx_mock.add_response(status_code=204)
    assert (await client.search(start="2026-09-01", end="2026-09-02")).total_matches == 0
    httpx_mock.add_response(status_code=404)
    with pytest.raises(NotFound):
        await client.search(event_id="nope1")


async def test_validation():
    with pytest.raises(InvalidInput):
        await client.search(start="2026-09-10", end="2026-09-01")
    with pytest.raises(InvalidInput):
        await client.search(latitude=49.0)
    with pytest.raises(InvalidInput):
        await client.search(bbox=(10, 50, -10, 40))
    with pytest.raises(InvalidInput):
        await client.search(event_id="../x")
    with pytest.raises(InvalidInput):
        await client.search(start="2000-01-01", end="2026-01-01")
