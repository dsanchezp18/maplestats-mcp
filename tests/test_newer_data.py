"""The "newer data exist" note on date-range requests (shared/newer_data.py).

Agents chose date ranges from an out-of-date sense of today (a 2024 window
asked for in November 2026) and reported those values as current. Each
range tool now says when the series runs past the range asked for.
"""

from __future__ import annotations

import re
from datetime import date

import httpx

from maplestats_mcp.modules.ab_economic import client as ab_client
from maplestats_mcp.modules.ab_economic import constants as ab_constants
from maplestats_mcp.modules.boc import client as boc_client
from maplestats_mcp.modules.boc import constants as boc_constants
from maplestats_mcp.modules.statcan.wds import client as wds_client
from maplestats_mcp.modules.statcan.wds import constants as wds_constants
from maplestats_mcp.modules.statcan.wds import context, tools
from maplestats_mcp.modules.statcan.wds.schemas import SeriesContext
from maplestats_mcp.shared import newer_data
from maplestats_mcp.shared.newer_data import newer_data_note

_TODAY = date(2026, 11, 4)


def _fixed_today(monkeypatch) -> None:
    monkeypatch.setattr(newer_data, "today", lambda: _TODAY)
    monkeypatch.setattr(boc_client, "today", lambda: _TODAY)


def test_note_only_when_the_series_runs_past_the_range(monkeypatch):
    _fixed_today(monkeypatch)
    kwargs = {"latest_args": "latest_n"}
    assert (
        newer_data_note(requested_end=date(2026, 9, 30), latest=date(2026, 9, 1), **kwargs) is None
    )
    assert newer_data_note(requested_end=None, latest=date(2026, 9, 1), **kwargs) is None
    assert newer_data_note(requested_end=date(2024, 12, 31), latest=None, **kwargs) is None
    note = newer_data_note(
        requested_end=date(2024, 12, 31),
        latest=date(2026, 9, 1),
        released="2026-10-09",
        **kwargs,
    )
    assert note == (
        "Newer data exist: the series runs to 2026-09-01, released 2026-10-09, after the end "
        "of the range asked for (2024-12-31). Today is 2026-11-04; for the latest values pass "
        "latest_n instead of a date range."
    )


def test_note_in_french(monkeypatch):
    _fixed_today(monkeypatch)
    note = newer_data_note(
        requested_end=date(2024, 12, 31),
        latest=date(2026, 9, 1),
        latest_args="latest_n",
        lang="fr",
    )
    assert note is not None
    assert note.startswith("Des données plus récentes existent : la série va jusqu'à 2026-09-01")
    assert "Nous sommes le 2026-11-04 ;" in note


def _wds_range(httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(
            re.escape(f"{wds_constants.BASE_URL}getDataFromVectorByReferencePeriodRange")
        ),
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "responseStatusCode": 0,
                    "productId": 14100287,
                    "coordinate": "10.7.1.1.1.1.0.0.0.0",
                    "vectorId": 2064516,
                    "vectorDataPoint": [
                        {
                            "refPer": "2024-12-01",
                            "value": 6.8,
                            "decimals": 1,
                            "scalarFactorCode": 0,
                            "symbolCode": 0,
                            "statusCode": 0,
                            "securityLevelCode": 0,
                            "releaseTime": "2026-01-26T08:30",
                        }
                    ],
                },
            }
        ],
    )


def _table_context(monkeypatch) -> None:
    async def describe(series):
        ctx = SeriesContext(
            table_id="14-10-0287-01",
            table_url="https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701",
            table_release_time="2026-10-09T08:30",
            last_period=date(2026, 9, 1),
        )
        return [s.model_copy(update={"context": ctx}) for s in series], None

    async def no_legend():
        return None

    async def no_prefetch(vector_ids):
        return None

    monkeypatch.setattr(context, "describe", describe)
    monkeypatch.setattr(context, "prefetch", no_prefetch)
    monkeypatch.setattr(wds_client, "observation_legend", no_legend)


async def test_wds_range_before_the_table_end_says_so(httpx_mock, monkeypatch):
    _fixed_today(monkeypatch)
    _table_context(monkeypatch)
    _wds_range(httpx_mock)
    fn = getattr(tools.wds_get_data_by_reference_period_range, "fn", None)
    fn = fn or tools.wds_get_data_by_reference_period_range
    result = await fn([2064516], "2024-01", "2024-12")
    limits = result.provenance.limits or ""
    assert limits.startswith(
        "Newer data exist: the series runs to 2026-09-01, released 2026-10-09, after the end "
        "of the range asked for (2024-12-31)."
    )
    assert "latest_n to wds_get_data_from_vectors" in limits


async def test_wds_range_reaching_the_table_end_has_no_note(httpx_mock, monkeypatch):
    _table_context(monkeypatch)
    _wds_range(httpx_mock)
    fn = getattr(tools.wds_get_data_by_reference_period_range, "fn", None)
    fn = fn or tools.wds_get_data_by_reference_period_range
    result = await fn([2064516], "2026-07", "2026-09")
    assert "Newer data exist" not in (result.provenance.limits or "")


def _boc_rows(day: str) -> dict[str, object]:
    return {
        "seriesDetail": {"FXUSDCAD": {"label": "USD/CAD"}},
        "observations": [{"d": day, "FXUSDCAD": {"v": "1.39"}}],
    }


async def test_boc_range_before_the_newest_observation_says_so(httpx_mock, monkeypatch):
    _fixed_today(monkeypatch)
    base = f"{boc_constants.BASE_URL}observations/FXUSDCAD/json"
    httpx_mock.add_response(
        url=f"{base}?start_date=2024-01-01&end_date=2024-12-31", json=_boc_rows("2024-12-31")
    )
    httpx_mock.add_response(url=f"{base}?recent=1", json=_boc_rows("2026-11-03"))
    result = await boc_client.get_observations(
        ["FXUSDCAD"], start_date="2024-01-01", end_date="2024-12-31"
    )
    limits = result.provenance.limits or ""
    assert limits.startswith("Newer data exist: the series runs to 2026-11-03, after the end")
    assert "recent, recent_months or recent_years" in limits


async def test_boc_range_reaching_today_makes_no_extra_request(httpx_mock, monkeypatch):
    _fixed_today(monkeypatch)
    httpx_mock.add_response(
        url=f"{boc_constants.BASE_URL}observations/FXUSDCAD/json?start_date=2026-11-01&end_date=2026-11-04",
        json=_boc_rows("2026-11-03"),
    )
    result = await boc_client.get_observations(
        ["FXUSDCAD"], start_date="2026-11-01", end_date="2026-11-04"
    )
    assert result.provenance.limits is None
    assert len(httpx_mock.get_requests()) == 1


async def test_boc_range_note_is_skipped_when_the_check_fails(httpx_mock, monkeypatch):
    _fixed_today(monkeypatch)
    base = f"{boc_constants.BASE_URL}observations/FXUSDCAD/json"
    httpx_mock.add_response(
        url=f"{base}?start_date=2024-01-01&end_date=2024-12-31", json=_boc_rows("2024-12-31")
    )
    httpx_mock.add_exception(
        httpx.ReadTimeout("timed out"), url=f"{base}?recent=1", is_reusable=True
    )
    result = await boc_client.get_observations(
        ["FXUSDCAD"], start_date="2024-01-01", end_date="2024-12-31"
    )
    assert result.provenance.limits is None
    assert [o.ref_date.isoformat() for o in result.observations] == ["2024-12-31"]


async def test_alberta_range_before_the_newest_row_says_so(httpx_mock, monkeypatch):
    _fixed_today(monkeypatch)
    httpx_mock.add_response(
        url=f"{ab_constants.BASE_URL}/api/chart-editor/data-tables",
        json=[{"tableName": "UnemploymentRates_14100287"}],
    )
    httpx_mock.add_response(
        json=[
            {"Date": f"{day}T00:00:00", "GeoName": "Alberta", "Value": value}
            for day, value in (("2024-12-01", 6.8), ("2026-08-01", 6.8), ("2026-09-01", 6.4))
        ]
    )
    result = await ab_client.get_data(
        "UnemploymentRates_14100287", {"GeoName": "Alberta"}, end_date="2024-12-31"
    )
    assert [r["Value"] for r in result.rows] == [6.8]
    limits = result.provenance.limits or ""
    assert limits.startswith("Newer data exist: the series runs to 2026-09-01, after the end")
    assert "limit with no end_date" in limits
