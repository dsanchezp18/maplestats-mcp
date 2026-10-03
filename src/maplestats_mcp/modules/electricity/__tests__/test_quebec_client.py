"""Tests for electricity/quebec_client.py, shaped around the Hydro-Quebec
Opendatasoft behaviour confirmed live 2026-09-29 (see the client docstring).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import unquote_plus

import pytest

from maplestats_mcp.modules.electricity import constants, quebec_client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = constants.QUEBEC_DATASETS_URL


def _exports(dataset: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(BASE)}/{dataset}/exports/json\?.*")


def _records(dataset: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(BASE)}/{dataset}/records\?.*")


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


async def test_demand_recent_returns_oldest_first_with_summary(httpx_mock):
    # export order is newest first (order_by date desc); the client reverses it
    httpx_mock.add_response(
        url=_exports("demande-electricite-quebec"),
        json=[
            {"date": "2026-09-29T15:45:00+00:00", "valeurs_demandetotal": 18260.0},
            {"date": "2026-09-29T15:30:00+00:00", "valeurs_demandetotal": 18382.0},
        ],
    )
    httpx_mock.add_response(url=_records("demande-electricite-quebec"), json={"total_count": 96})
    result = await quebec_client.get_demand(limit=2)
    assert [p.demand_mw for p in result.points] == [18382.0, 18260.0]
    assert result.latest_demand_mw == 18260.0
    assert result.latest_timestamp == datetime(2026, 9, 29, 15, 45, tzinfo=UTC)
    assert result.peak_demand_mw == 18382.0
    assert result.average_demand_mw == 18321.0
    assert result.rows_matched == 96
    assert "CC BY-NC 4.0" in (result.provenance.licence or "")
    assert "non-commercial" in (result.provenance.licence or "")
    url = unquote_plus(str(httpx_mock.get_requests()[0].url))
    # The not-null filter keeps future null slots out of "latest".
    assert "valeurs_demandetotal is not null" in url
    assert "order_by=date desc" in url


async def test_demand_history_range_uses_ascending_order_and_utc_bounds(httpx_mock):
    httpx_mock.add_response(
        url=_exports("historique-demande-electricite-quebec"),
        json=[{"date": "2025-01-01T00:00:00+00:00", "moyenne_mw": 24404.29}],
    )
    httpx_mock.add_response(
        url=_records("historique-demande-electricite-quebec"), json={"total_count": 1}
    )
    result = await quebec_client.get_demand("history", "2025-01-01", "2025-01-01", limit=5)
    assert result.interval == "hourly average"
    assert result.points[0].demand_mw == 24404.29
    url = unquote_plus(str(httpx_mock.get_requests()[0].url))
    assert "order_by=date&" in url
    assert 'date >= "2025-01-01T00:00:00Z"' in url
    # End date is inclusive, so the bound is the start of the next UTC day.
    assert 'date < "2025-01-02T00:00:00Z"' in url


async def test_generation_shares_and_placeholder_filter(httpx_mock):
    httpx_mock.add_response(
        url=_exports("production-electricite-quebec"),
        json=[
            {
                "date": "2026-09-28T04:30:00+00:00",
                "valeurs_total": 13377.0,
                "valeurs_hydraulique": 10779.0,
                "valeurs_eolien": 1868.0,
                "valeurs_autres": 730.0,
                "valeurs_solaire": 0.0,
                "valeurs_thermique": 0.0,
            }
        ],
    )
    httpx_mock.add_response(url=_records("production-electricite-quebec"), json={"total_count": 30})
    result = await quebec_client.get_generation()
    assert result.points[0].wind_mw == 1868.0
    assert result.average_share_percent["hydro"] == round(100 * 10779 / 13377, 2)
    assert result.rows_matched == 30
    url = unquote_plus(str(httpx_mock.get_requests()[0].url))
    # Placeholder future hours (total 0.0, null components) are cut by a "now" cutoff.
    assert "valeurs_hydraulique is not null" in url
    assert re.search(r'date <= "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"', url)


async def test_generation_history_uses_unprefixed_fields(httpx_mock):
    httpx_mock.add_response(
        url=_exports("historique-production-electricite-quebec"),
        json=[
            {
                "date": "2026-01-01T04:00:00+00:00",
                "hydraulique": 25516.0,
                "eolien": 805.0,
                "autres": 583.0,
                "solaire": 0.0,
                "thermique": 0.0,
                "total": 26904.0,
            }
        ],
    )
    httpx_mock.add_response(
        url=_records("historique-production-electricite-quebec"), json={"total_count": 59915}
    )
    result = await quebec_client.get_generation("history", limit=1)
    assert result.points[0].total_mw == 26904.0
    assert result.rows_matched == 59915


async def test_trade_maps_markets_and_unknown_spelling(httpx_mock):
    httpx_mock.add_response(
        url=_exports("importations-exportations-avec-transits"),
        json=[
            {
                "date": "2026-09-28T07:00:00+00:00",
                "exportations_total": 628.3,
                "exportations_newengland": -927.0,
                "exportations_newbrunswick": 0.0,
                "exportations_newyork": -1000.0,
                "exportations_ontario": 628.3,
                "importations_sources_ontario_total": 0.0,
                "importations_sources_ontario_unknow": 5.0,
                "importations_sources_newyork_total": 1000.0,
                "importations_sources_newyork_gas": 514.5,
                "importations_sources_newyork_unknown": 20.2,
                "importations_sources_newyork_hydro": None,
            }
        ],
    )
    httpx_mock.add_response(
        url=_records("importations-exportations-avec-transits"), json={"total_count": 24}
    )
    point = (await quebec_client.get_trade()).points[0]
    assert point.net_exports_mw["newyork"] == -1000.0
    assert point.imports_mw["newyork"] == 1000.0
    assert point.import_sources_mw["newyork"]["gas"] == 514.5
    assert point.import_sources_mw["newyork"]["unknown"] == 20.2
    # Ontario's dataset column is spelled "unknow".
    assert point.import_sources_mw["ontario"]["unknown"] == 5.0
    assert point.import_sources_mw["newyork"]["hydro"] is None
    assert point.import_sources_mw["newengland"]["gas"] is None


async def test_input_validation():
    with pytest.raises(InvalidInput):
        await quebec_client.get_demand("archive")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await quebec_client.get_demand(limit=0)
    with pytest.raises(InvalidInput):
        await quebec_client.get_generation(start_date="2025-02-01", end_date="2025-01-01")
    with pytest.raises(InvalidInput):
        await quebec_client.get_trade(start_date="soon")


async def test_upstream_status_mapping(httpx_mock):
    httpx_mock.add_response(url=_exports("demande-electricite-quebec"), status_code=404)
    with pytest.raises(NotFound):
        await quebec_client.get_demand()
    httpx_mock.add_response(
        url=_exports("importations-exportations-avec-transits"), status_code=400, json={}
    )
    with pytest.raises(InvalidInput):
        await quebec_client.get_trade()
