"""drivebc/client.py against payloads shaped like the live Open511 API (2026-10-03)."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.drivebc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

EVENTS_RE = re.compile(re.escape(constants.EVENTS_URL) + r"\?.*")
AREAS_RE = re.compile(re.escape(constants.AREAS_URL) + r"\?.*")


def _event(
    ident: str,
    *,
    kind: str = "CONSTRUCTION",
    severity: str = "MINOR",
    road: str = "Highway 1",
    area: tuple[str, str] = ("drivebc.ca/1", "Lower Mainland District"),
    geography: dict | None = None,
    updated: str = "2026-09-24T11:02:28-07:00",
    description: str = "Paving. Expect delays.",
) -> dict:
    return {
        "jurisdiction_url": "https://api.open511.gov.bc.ca/jurisdiction",
        "url": f"https://api.open511.gov.bc.ca/events/drivebc.ca/{ident}",
        "id": f"drivebc.ca/{ident}",
        "headline": kind,
        "status": "ACTIVE",
        "created": "2026-09-24T11:02:28-07:00",
        "updated": updated,
        "description": description,
        "+ivr_message": description,
        "+linear_reference_km": 0,
        "schedule": {"intervals": ["2026-09-24T18:02/"]},
        "event_type": kind,
        "event_subtypes": ["ROAD_MAINTENANCE"] if kind == "CONSTRUCTION" else ["HAZARD"],
        "severity": severity,
        "geography": geography or {"type": "Point", "coordinates": [-122.9, 49.2]},
        "roads": [
            {"name": road, "from": "Exit 50", "direction": "BOTH", "state": "ALL_LANES_OPEN"}
        ],
        "areas": [{"url": "http://www.geonames.org/8630136", "name": area[1], "id": area[0]}],
    }


EVENTS = [
    _event("A1"),
    _event(
        "A2",
        kind="INCIDENT",
        severity="MAJOR",
        road="Highway 16",
        area=("drivebc.ca/9", "Fort George District"),
        geography={"type": "LineString", "coordinates": [[-122.7, 53.9], [-122.6, 53.95]]},
        description="Vehicle incident. Road closed.",
    ),
    _event("A3", updated="2026-10-02T08:00:00-07:00", road="Other Roads"),
]


def _page(events: list[dict], offset: int = 0) -> dict:
    return {
        "events": events,
        "pagination": {"offset": str(offset)},
        "meta": {"url": "/events", "up_url": "", "version": "v1"},
    }


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _serve(httpx_mock, events: list[dict] = EVENTS) -> None:
    httpx_mock.add_response(url=EVENTS_RE, json=_page(events), is_reusable=True)


async def test_search_filters_combine_and_major_comes_first(httpx_mock):
    _serve(httpx_mock)
    every = await client.search_events()
    assert every.total_active == 3
    assert [e.event_id for e in every.events] == [
        "drivebc.ca/A2",  # MAJOR first
        "drivebc.ca/A3",  # then newest update
        "drivebc.ca/A1",
    ]
    assert every.events[0].latitude == 53.9 and every.events[0].longitude == -122.7
    assert every.events[1].schedule == ["2026-09-24T18:02/"]
    assert "Open Government Licence - British Columbia" in (every.provenance.licence or "")
    assert (await client.search_events(severity="major")).total_matches == 1
    assert (await client.search_events(event_type="INCIDENT")).total_matches == 1
    assert (await client.search_events(subtype="road maintenance")).total_matches == 2
    assert (await client.search_events(query="closed")).total_matches == 1


async def test_road_number_does_not_match_a_longer_number(httpx_mock):
    _serve(httpx_mock)
    for road in ("Highway 1", "hwy 1", "1"):
        result = await client.search_events(road=road)
        assert [e.event_id for e in result.events] == ["drivebc.ca/A1"], road
    assert (await client.search_events(road="16")).total_matches == 1
    assert (await client.search_events(road="other")).total_matches == 1


async def test_area_by_id_number_or_name_and_bbox(httpx_mock):
    _serve(httpx_mock)
    assert (await client.search_events(area="drivebc.ca/9")).total_matches == 1
    assert (await client.search_events(area="9")).total_matches == 1
    assert (await client.search_events(area="lower mainland")).total_matches == 2
    # The line's second point is in the box, its first is not.
    box = await client.search_events(bbox=[-122.65, 53.92, -122.5, 54.0])
    assert [e.event_id for e in box.events] == ["drivebc.ca/A2"]


async def test_bad_arguments_are_input_errors(httpx_mock):
    with pytest.raises(InvalidInput, match="severity"):
        await client.search_events(severity="huge")
    with pytest.raises(InvalidInput, match="bbox"):
        await client.search_events(bbox=[1.0, 2.0])
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_events(limit=0)
    with pytest.raises(InvalidInput, match="group_by"):
        await client.summarize_events("colour")


async def test_pages_until_a_short_page(httpx_mock, monkeypatch):
    # The API reports no total; a full page means there may be more.
    monkeypatch.setattr(constants, "PAGE_SIZE", 2)
    httpx_mock.add_response(url=re.compile(r".*offset=0.*"), json=_page(EVENTS[:2]))
    httpx_mock.add_response(url=re.compile(r".*offset=2.*"), json=_page(EVENTS[2:], 2))
    result = await client.search_events()
    assert result.total_active == 3


async def test_event_detail_and_not_found(httpx_mock):
    _serve(httpx_mock)
    detail = await client.get_event("A2")
    assert detail.geometry["type"] == "LineString"
    assert detail.event.roads[0].name == "Highway 16"
    assert detail.linear_reference_km == 0.0
    with pytest.raises(NotFound, match="ended"):
        await client.get_event("drivebc.ca/ZZ")


async def test_summary_and_areas_agree(httpx_mock):
    _serve(httpx_mock)
    httpx_mock.add_response(
        url=AREAS_RE,
        json={
            "areas": [
                {
                    "url": "http://www.geonames.org/8630136",
                    "name": "Lower Mainland District",
                    "id": "drivebc.ca/1",
                },
                {
                    "url": "http://www.geonames.org/8630131",
                    "name": "Fort George District",
                    "id": "drivebc.ca/9",
                },
                {
                    "url": "http://www.geonames.org/8630140",
                    "name": "Vancouver Island District",
                    "id": "drivebc.ca/2",
                },
            ],
            "meta": {"url": "/areas", "version": "v1"},
        },
    )
    summary = await client.summarize_events("area")
    assert [(g.value, g.events, g.major) for g in summary.groups] == [
        ("Lower Mainland District", 2, 0),
        ("Fort George District", 1, 1),
    ]
    areas = await client.list_areas()
    counts = {a.area_id: a.active_events for a in areas.areas}
    assert counts == {"drivebc.ca/1": 2, "drivebc.ca/9": 1, "drivebc.ca/2": 0}


async def test_null_lists_and_missing_geometry_are_tolerated(httpx_mock):
    raw = _event("N1")
    raw["roads"] = None
    raw["event_subtypes"] = None
    raw["geography"] = None
    _serve(httpx_mock, [raw])
    result = await client.search_events(road="1")
    assert result.total_matches == 0
    event = (await client.search_events()).events[0]
    assert event.roads == [] and event.latitude is None


async def test_rate_limit_page_is_unavailable(httpx_mock):
    # Live: an HTML "429 - Too Many Requests" page with no Retry-After.
    httpx_mock.add_response(
        url=EVENTS_RE, status_code=429, html="<html><title>429</title></html>", is_reusable=True
    )
    with pytest.raises(UpstreamUnavailable, match="rate-limiting"):
        await client.search_events()


async def test_response_without_events_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=EVENTS_RE, json={"meta": {}})
    with pytest.raises(UpstreamError, match="events"):
        await client.search_events()
