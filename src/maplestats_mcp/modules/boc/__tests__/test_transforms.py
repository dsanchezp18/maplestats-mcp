"""Valet values that are not numbers, series units, and transforms.

Payloads are shaped like live Valet responses (2026-10-27): seriesDetail
carries dateFormat and metadata {unit, frequency}; "v" is always a string.
"""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.boc import client, constants, tools
from maplestats_mcp.shared.transform import TransformRequest


def _fn(t):
    return getattr(t, "fn", t)


def _detail(label, unit, date_format="monthly", frequency="Monthly"):
    return {
        "label": label,
        "description": "",
        "dimension": {"key": "d", "name": "Date"},
        "dateFormat": date_format,
        "metadata": {"unit": unit, "frequency": frequency},
    }


CPI = {
    "2025-07-01": "164.9",
    "2025-08-01": "164.8",
    "2025-09-01": "164.9",
    "2026-07-01": "169.9",
    "2026-08-01": "169.8",
    "2026-09-01": "170.0",
}


def test_text_that_is_not_a_number_is_kept_beside_the_null():
    rows = [{"d": "2026-09-15", "FXUSDCAD": {"v": "n/a"}, "FXEURCAD": {"v": "1.5"}}]
    observation = client._observations_from_json(rows)[0]
    assert observation.values == {"FXUSDCAD": None, "FXEURCAD": 1.5}
    assert observation.non_numeric == {"FXUSDCAD": "n/a"}
    assert "1 value(s)" in (client._non_numeric_note([observation], "en") or "")
    empty = client._observations_from_json([{"d": "2026-09-15", "X": {"v": ""}}])[0]
    assert empty.non_numeric is None


async def test_yoy_reaches_back_a_year_and_keeps_the_published_rows(httpx_mock):
    detail = {"V41690973": _detail("Total CPI", "Index (2002=100)")}
    window = {"start_date": "2026-07-01"}
    httpx_mock.add_response(
        url=httpx.URL(f"{constants.BASE_URL}observations/V41690973/json", params=window),
        json={
            "seriesDetail": detail,
            "observations": [
                {"d": d, "V41690973": {"v": v}} for d, v in CPI.items() if d >= "2026"
            ],
        },
    )
    history = {"start_date": "2025-07-01", "end_date": "2026-09-01"}
    httpx_mock.add_response(
        url=httpx.URL(f"{constants.BASE_URL}observations/V41690973/json", params=history),
        json={
            "seriesDetail": detail,
            "observations": [{"d": d, "V41690973": {"v": v}} for d, v in CPI.items()],
        },
    )
    result = await _fn(tools.boc_get_observations)(
        ["V41690973"], start_date="2026-07-01", transform="yoy_pct_change"
    )
    assert [o.ref_date.isoformat() for o in result.observations] == [
        "2026-07-01",
        "2026-08-01",
        "2026-09-01",
    ]
    assert result.series["V41690973"].unit == "Index (2002=100)"
    assert result.transformed is not None
    computed = result.transformed["V41690973"]
    assert computed.points[-1].value == pytest.approx(100 * (170.0 / 164.9 - 1))
    assert "history for the lag" in (result.provenance.coverage or "")


async def test_policy_rate_change_is_in_points_and_daily_yoy_needs_a_frequency(httpx_mock):
    detail = {
        "V39079": _detail("Target for the overnight rate", "Percent", "daily", "Business daily")
    }
    httpx_mock.add_response(
        url=httpx.URL(f"{constants.BASE_URL}observations/V39079/json"),
        json={
            "seriesDetail": detail,
            "observations": [
                {"d": "2026-09-16", "V39079": {"v": "2.50"}},
                {"d": "2026-09-17", "V39079": {"v": "2.25"}},
            ],
        },
        is_reusable=True,
    )
    result = await client.get_observations(["V39079"], request=TransformRequest("pct_change"))
    assert result.transformed is not None
    computed = result.transformed["V39079"]
    assert computed.transform == "diff"
    assert computed.unit == "percentage points"
    assert computed.points[-1].value == pytest.approx(-0.25)
    with pytest.raises(client.InvalidInput, match="frequency"):
        await client.get_observations(["V39079"], request=TransformRequest("yoy_pct_change"))


def test_rate_words_without_a_unit():
    exchange = client.SeriesInfoBrief(
        name="FXUSDCAD", label="USD/CAD", description="Daily average exchange rate"
    )
    yield_ = client.SeriesInfoBrief(name="BD.CDN.10YR", label="10-year bond yield", description="")
    assert not client._is_rate(exchange)
    assert client._is_rate(yield_)
