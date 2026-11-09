"""wds_get_data_from_cube_coord with several coordinates, its cache, and the
cube metadata fetched beside the data; plus the memoized table inventory.

fixtures/cube_coord_batch.json holds 18-10-0004's metadata trimmed from the
live answer and live-shaped data envelopes (its `_note` says which values are
live). The data mock answers in the order of the coordinates in the request
body, as WDS does.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.statcan.wds import client, constants, tools
from maplestats_mcp.shared.errors import InvalidInput, NotFound

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "cube_coord_batch.json").read_text(encoding="utf-8")
)
DATA_URL = f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods"
CUBE_URL = f"{constants.BASE_URL}getCubeMetadata"
INFO_URL = f"{constants.BASE_URL}getSeriesInfoFromVector"
COORD_INFO_URL = f"{constants.BASE_URL}getSeriesInfoFromCubePidCoord"
ENVELOPES = {
    "2.2.0.0.0.0.0.0.0.0": FIXTURE["series_canada"],
    "14.2.0.0.0.0.0.0.0.0": FIXTURE["series_ontario"],
    "29.24.0.0.0.0.0.0.0.0": FIXTURE["missing_whitehorse_butter"],
}


def _fn(t):
    return getattr(t, "fn", t)


def _data(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    answer = []
    for pair in body:
        envelope = json.loads(json.dumps(ENVELOPES[pair["coordinate"]]))
        points = envelope["object"]["vectorDataPoint"]
        envelope["object"]["vectorDataPoint"] = points[-pair["latestN"] :]
        answer.append(envelope)
    return httpx.Response(200, json=answer)


def _series_info(request: httpx.Request) -> httpx.Response:
    by_vector = {e["object"]["vectorId"]: e["object"] for e in ENVELOPES.values()}
    answer = []
    for item in json.loads(request.content):
        obj = by_vector[item["vectorId"]]
        answer.append(
            {
                "status": "SUCCESS",
                "object": {
                    "responseStatusCode": 0,
                    "productId": obj["productId"],
                    "coordinate": obj["coordinate"],
                    "vectorId": obj["vectorId"],
                    "frequencyCode": 6,
                    "scalarFactorCode": 0,
                    "decimals": 1,
                    "memberUomCode": 17,
                    "SeriesTitleEn": "Consumer Price Index; All-items",
                },
            }
        )
    return httpx.Response(200, json=answer)


def _mock(httpx_mock, *, data=_data) -> None:
    httpx_mock.add_callback(data, url=DATA_URL, is_reusable=True)
    httpx_mock.add_response(
        url=CUBE_URL,
        json=[{"status": "SUCCESS", "object": FIXTURE["cube_metadata"]}],
        is_reusable=True,
        is_optional=True,
    )
    httpx_mock.add_callback(_series_info, url=INFO_URL, is_reusable=True, is_optional=True)


def _bodies(httpx_mock, url: str) -> list[list[dict]]:
    return [json.loads(r.content) for r in httpx_mock.get_requests(url=url)]


async def test_several_coordinates_are_one_request_with_a_series_each(httpx_mock):
    _mock(httpx_mock)
    result = await _fn(tools.wds_get_data_from_cube_coord)(
        "18-10-0004-01", coordinates=["14.2", "2.2", "29.24"], latest_n=2
    )
    # One POST, pairs sorted so every ordering shares one cache entry.
    assert _bodies(httpx_mock, DATA_URL) == [
        [
            {"productId": 18100004, "coordinate": "14.2.0.0.0.0.0.0.0.0", "latestN": 2},
            {"productId": 18100004, "coordinate": "2.2.0.0.0.0.0.0.0.0", "latestN": 2},
            {"productId": 18100004, "coordinate": "29.24.0.0.0.0.0.0.0.0", "latestN": 2},
        ]
    ]
    assert result.series is not None
    # Back in the order asked, each with its own context.
    assert [s.vector_id for s in result.series] == [41691783, 41690973]
    assert [len(s.observations) for s in result.series] == [2, 2]
    assert result.series[1].observations[-1].value == 170.0
    assert all(s.context and s.context.table_id == "18-10-0004-01" for s in result.series)
    assert result.series[0].context.geography == "Ontario"  # type: ignore[union-attr]
    # The top level names the first series and leaves its rows to `series`.
    assert (result.vector_id, result.coordinate, result.observations) == (
        41691783,
        "14.2.0.0.0.0.0.0.0.0",
        [],
    )
    # The combination StatCan does not publish is explained, not fatal.
    (failed,) = result.failed
    assert failed.coordinate == "29.24.0.0.0.0.0.0.0.0"
    assert "does not publish a series" in failed.reason and "Whitehorse" in failed.reason
    assert "1 coordinate(s) returned no data" in (result.provenance.limits or "")


async def test_one_coordinate_keeps_the_old_shape(httpx_mock):
    _mock(httpx_mock)
    result = await _fn(tools.wds_get_data_from_cube_coord)(18100004, "2.2", latest_n=3)
    assert result.series is None and result.failed == []
    assert result.vector_id == 41690973
    assert [o.value for o in result.observations] == [169.9, 169.8, 170.0]
    assert result.context is not None and result.context.geography == "Canada"


async def test_one_missing_coordinate_still_raises_the_explanation(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(NotFound, match="does not publish a series"):
        await _fn(tools.wds_get_data_from_cube_coord)(18100004, "29.24")


async def test_data_is_cached_for_any_order_of_the_same_coordinates(httpx_mock):
    _mock(httpx_mock)
    first = await client.get_data_from_cube_pid_coords_and_latest_n_periods(
        18100004, ["2.2", "14.2"], 4
    )
    again = await client.get_data_from_cube_pid_coords_and_latest_n_periods(
        18100004, ["14.2.0.0.0.0.0.0.0.0", "2.2"], 4
    )
    assert len(httpx_mock.get_requests(url=DATA_URL)) == 1
    assert not first.provenance.cached and again.provenance.cached
    assert [s.vector_id for s in again.series or []] == [41691783, 41690973]
    # A different window is a different request.
    await client.get_data_from_cube_pid_coords_and_latest_n_periods(18100004, ["2.2"], 4)
    assert len(httpx_mock.get_requests(url=DATA_URL)) == 2


async def test_cube_metadata_is_fetched_beside_the_data(httpx_mock):
    """The data request waits until getCubeMetadata has started: run one after
    the other, this would time out."""
    metadata_started = asyncio.Event()

    async def cube(request: httpx.Request) -> httpx.Response:
        metadata_started.set()
        return httpx.Response(200, json=[{"status": "SUCCESS", "object": FIXTURE["cube_metadata"]}])

    async def data(request: httpx.Request) -> httpx.Response:
        await asyncio.wait_for(metadata_started.wait(), timeout=5)
        return _data(request)

    httpx_mock.add_callback(data, url=DATA_URL)
    httpx_mock.add_callback(cube, url=CUBE_URL)
    httpx_mock.add_callback(_series_info, url=INFO_URL)
    result = await _fn(tools.wds_get_data_from_cube_coord)(18100004, "2.2", latest_n=1)
    assert result.context is not None and result.context.table_title is not None
    assert len(httpx_mock.get_requests(url=CUBE_URL)) == 1
    assert not httpx_mock.get_requests(url=COORD_INFO_URL)


async def test_transform_reads_the_frequency_from_cube_metadata(httpx_mock):
    _mock(httpx_mock)
    result = await _fn(tools.wds_get_data_from_cube_coord)(
        18100004, coordinates=["2.2", "14.2"], latest_n=3, transform="yoy_pct_change"
    )
    # Monthly (the table's frequencyCode 6): three year-over-year changes need 15 months.
    assert {p["latestN"] for p in _bodies(httpx_mock, DATA_URL)[0]} == {15}
    assert not httpx_mock.get_requests(url=COORD_INFO_URL)
    # Both series' info in one batched request, shared with the context.
    assert _bodies(httpx_mock, INFO_URL) == [[{"vectorId": 41690973}, {"vectorId": 41691783}]]
    canada = (result.series or [])[1]
    assert canada.transformed is not None
    assert [round(p.value or 0, 1) for p in canada.transformed.points] == [3.0, 3.0, 3.1]
    assert "latestN=15" in (result.provenance.coverage or "")


async def test_transform_falls_back_to_series_info_without_metadata(httpx_mock):
    httpx_mock.add_callback(_data, url=DATA_URL, is_reusable=True)
    httpx_mock.add_response(url=CUBE_URL, status_code=500, is_reusable=True, is_optional=True)
    httpx_mock.add_callback(_series_info, url=INFO_URL, is_reusable=True, is_optional=True)
    httpx_mock.add_response(
        url=COORD_INFO_URL,
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "responseStatusCode": 0,
                    "productId": 18100004,
                    "coordinate": "2.2.0.0.0.0.0.0.0.0",
                    "vectorId": 41690973,
                    "frequencyCode": 6,
                    "memberUomCode": 17,
                },
            }
        ],
    )
    result = await _fn(tools.wds_get_data_from_cube_coord)(
        18100004, "2.2", latest_n=1, transform="yoy_pct_change"
    )
    assert _bodies(httpx_mock, DATA_URL)[0][0]["latestN"] == 13
    assert result.transformed is not None


async def test_too_many_coordinates_are_refused_before_any_request(httpx_mock):
    coordinates = [f"{i}.2" for i in range(1, constants.WDS_MAX_LIST + 2)]
    with pytest.raises(InvalidInput, match="at most 300 coordinates"):
        await _fn(tools.wds_get_data_from_cube_coord)(18100004, coordinates=coordinates)
    with pytest.raises(InvalidInput, match="at least one coordinate"):
        await _fn(tools.wds_get_data_from_cube_coord)(18100004)
    assert not httpx_mock.get_requests()


INVENTORY = [
    {
        "productId": 18100004 + i,
        "cansimId": None,
        "cubeTitleEn": f"Consumer Price Index table {i}",
        "cubeTitleFr": f"Indice des prix à la consommation tableau {i}",
        "cubeStartDate": "1914-01-01",
        "cubeEndDate": "2026-09-01",
        "releaseTime": "2026-10-21T08:30",
        "archived": "2",
        "frequencyCode": 6,
        "subjectCode": ["18"],
        "surveyCode": ["2301"],
        "dimensionCount": 2,
    }
    for i in range(50)
]


async def test_search_parses_and_folds_the_inventory_once(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getAllCubesListLite", json=INVENTORY, is_reusable=True
    )
    parsed = 0
    folded = 0
    parse, fold = client._cube_summary_from_json, client._fold

    def counting_parse(obj):
        nonlocal parsed
        parsed += 1
        return parse(obj)

    def counting_fold(text):
        nonlocal folded
        folded += 1
        return fold(text)

    monkeypatch.setattr(client, "_cube_summary_from_json", counting_parse)
    monkeypatch.setattr(client, "_fold", counting_fold)
    client._parsed_inventory.clear()
    first = await client.search_cubes("prix consommation")
    assert (parsed, folded) == (50, 101)  # every title in both languages, and the query
    second = await client.search_cubes("table 42")
    third = await client.search_cubes("18-10-0005")
    assert (parsed, folded) == (50, 102)  # only the second query was folded
    assert first.total_count == 50 and second.total_count == 1
    assert [c.product_id for c in third.cubes] == [18100005]
    assert len(httpx_mock.get_requests()) == 1
