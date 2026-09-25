"""Tests for eps/client.py, shaped around quirks confirmed live
2026-09-22 (see the module docstring): 12:00 UTC calendar dates, the
DD/MM/YYYY load date, and HTTP 200 responses carrying an embedded error.
"""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.eps import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

_CURRENT_QUERY = re.compile(re.escape(constants.DATASETS["current"]) + r"/query.*")


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_build_where_quotes_and_makes_end_date_inclusive():
    where = client.build_where(
        category="Violent",
        group="O'Brien",
        start_date="2026-09-01",
        end_date="2026-09-01",
        intersection_contains=" jasper av ",
    )
    assert "Occurrence_Category = 'Violent'" in where
    assert "Occurrence_Group = 'O''Brien'" in where
    assert "Reported_Date >= DATE '2026-09-01'" in where
    assert "Reported_Date < DATE '2026-09-02'" in where
    assert "UPPER(Intersection) LIKE '%JASPER AV%'" in where


def test_build_where_defaults_to_all_rows():
    assert client.build_where() == "1=1"


def test_build_where_rejects_bad_dates():
    with pytest.raises(InvalidInput):
        client.build_where(start_date="2026/09/01")
    with pytest.raises(InvalidInput):
        client.build_where(start_date="2026-09-02", end_date="2026-09-01")


async def test_list_occurrences_parses_rows(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 17})
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "features": [
                {
                    "attributes": {
                        "Reported_Date": 1769342400000,
                        "Occurrence_Category": "Non-Violent",
                        "Occurrence_Group": "Property",
                        "Occurrence_Type_Group": "Theft From Vehicle",
                        "Intersection": "82 ST/123 AV",
                    },
                    "geometry": {"x": -113.45, "y": 53.57},
                }
            ]
        },
    )
    result = await client.list_occurrences(limit=1)
    assert result.total_matches == 17
    occurrence = result.occurrences[0]
    assert occurrence.reported_date is not None
    assert occurrence.reported_date.isoformat() == "2026-01-25"
    assert occurrence.intersection == "82 ST/123 AV"
    assert occurrence.latitude == 53.57


async def test_embedded_error_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={"error": {"code": 400, "message": "Invalid query", "details": ["bad where"]}},
    )
    with pytest.raises(InvalidInput):
        await client.list_occurrences(category="Violent")


async def test_summarize_occurrences_by_month(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 3})
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "features": [
                {
                    "attributes": {
                        "Reported_Year": "2026",
                        "Reported_Month": 8,
                        "occurrence_count": 2,
                    }
                },
                {
                    "attributes": {
                        "Reported_Year": "2026",
                        "Reported_Month": 9,
                        "occurrence_count": 1,
                    }
                },
            ]
        },
    )
    result = await client.summarize_occurrences(group_by="month")
    assert result.total_matches == 3
    assert [group.count for group in result.groups] == [2, 1]
    assert result.groups[0].keys == {"Reported_Year": "2026", "Reported_Month": 8}


async def test_invalid_arguments_raise():
    with pytest.raises(InvalidInput):
        await client.list_occurrences(limit=0)
    with pytest.raises(InvalidInput):
        await client.summarize_occurrences(group_by="neighbourhood")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.list_occurrences("2024")  # type: ignore[arg-type]


async def test_get_last_load_date_parses_day_first(httpx_mock):
    httpx_mock.add_response(json={"features": [{"attributes": {"Last_Load_Date": "20/09/2026"}}]})
    result = await client.get_last_load_date()
    assert result.last_load_date is not None
    assert result.last_load_date.isoformat() == "2026-09-20"
    assert result.raw_value == "20/09/2026"
