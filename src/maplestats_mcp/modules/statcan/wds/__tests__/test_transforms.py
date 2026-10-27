"""Status-code decoding and server-side transforms on the WDS series tools.

Fixture values are the live CPI all-items (v41690973) and unemployment rate
(v2062815) figures read on 2026-10-27; the expected changes are worked out
by hand from them.
"""

from __future__ import annotations

import json

import httpx
import pytest

from maplestats_mcp.modules.statcan.wds import client, constants, tools

# CPI all-items, 2025-07 to 2026-09 (15 months, as latestN=15 returns them).
CPI = [
    ("2025-07-01", 164.9),
    ("2025-08-01", 164.8),
    ("2025-09-01", 164.9),
    ("2025-10-01", 165.3),
    ("2025-11-01", 165.4),
    ("2025-12-01", 165.0),
    ("2026-01-01", 165.6),
    ("2026-02-01", 166.6),
    ("2026-03-01", 167.6),
    ("2026-04-01", 168.4),
    ("2026-05-01", 169.0),
    ("2026-06-01", 169.3),
    ("2026-07-01", 169.9),
    ("2026-08-01", 169.8),
    ("2026-09-01", 170.0),
]
RATE = [("2026-06-01", 6.5), ("2026-07-01", 6.4), ("2026-08-01", 6.4), ("2026-09-01", 6.5)]


def _fn(t):
    return getattr(t, "fn", t)


def _point(ref, value, status=0, symbol=0, security=0):
    return {
        "refPer": ref,
        "value": value,
        "decimals": 1,
        "scalarFactorCode": 0,
        "symbolCode": symbol,
        "statusCode": status,
        "securityLevelCode": security,
        "releaseTime": "2026-10-19T08:30",
    }


def _series(vector, pid, coord, points):
    return {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": pid,
            "coordinate": coord,
            "vectorId": vector,
            "vectorDataPoint": [_point(r, v) for r, v in points],
        },
    }


INFO = {
    41690973: {"productId": 18100004, "coordinate": "2.2.0.0.0.0.0.0.0.0", "uom": 17},
    2062815: {"productId": 14100287, "coordinate": "1.7.1.1.1.1.0.0.0.0", "uom": 239},
}


def _mock_wds(httpx_mock, data):
    def info(request):
        vector = json.loads(request.content)[0]["vectorId"]
        meta = INFO[vector]
        return httpx.Response(
            200,
            json=[
                {
                    "status": "SUCCESS",
                    "object": {
                        "responseStatusCode": 0,
                        "productId": meta["productId"],
                        "coordinate": meta["coordinate"],
                        "vectorId": vector,
                        "frequencyCode": 6,
                        "scalarFactorCode": 0,
                        "decimals": 1,
                        "memberUomCode": meta["uom"],
                    },
                }
            ],
        )

    httpx_mock.add_callback(
        info, url=f"{constants.BASE_URL}getSeriesInfoFromVector", is_reusable=True
    )
    httpx_mock.add_callback(
        lambda request: httpx.Response(200, json=data),
        url=f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods",
        is_reusable=True,
        is_optional=True,
    )


async def test_codes_are_decoded_in_the_call_language(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods",
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "productId": 14100325,
                    "coordinate": "15.1.0.0.0.0.0.0.0.0",
                    "vectorId": 104272660,
                    "vectorDataPoint": [
                        _point("2023-07-01", 3910.0, status=7, symbol=1),
                        _point("2023-10-01", None, status=8, security=1),
                    ],
                },
            }
        ],
        is_reusable=True,
    )
    result = await _fn(tools.wds_get_data_from_cube_coord)(14100325, "15.1", latest_n=2)
    first, second = result.observations
    assert (first.status_code, first.status, first.symbol) == (7, "use with caution", "preliminary")
    assert second.value is None
    assert second.status == "too unreliable to be published"
    assert second.security_level.startswith("suppressed")
    french = await _fn(tools.wds_get_data_from_cube_coord)(14100325, "15.1", 2, lang="fr")
    assert french.observations[0].status == "à utiliser avec prudence"


async def test_undecoded_codes_are_said_not_hidden(httpx_mock, monkeypatch):
    async def down():
        raise client.UpstreamUnavailable("getCodeSets down")

    monkeypatch.setattr(client, "_code_sets_raw", down)
    obj = _series(41690973, 18100004, "2.2.0.0.0.0.0.0.0.0", CPI[-1:])["object"]
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods",
        json=[{"status": "SUCCESS", "object": obj}],
    )
    result = await client.get_data_from_cube_pid_coord_and_latest_n_periods(18100004, "2.2", 1)
    assert result.observations[0].status is None
    assert result.observations[0].status_code == 0
    assert "not decoded" in (result.provenance.limits or "")


async def test_yoy_inflation_fetches_a_year_more_and_returns_the_window(httpx_mock):
    _mock_wds(httpx_mock, [_series(41690973, 18100004, "2.2.0.0.0.0.0.0.0.0", CPI)])
    result = await _fn(tools.wds_get_data_from_vectors)(
        [41690973], latest_n=3, transform="yoy_pct_change"
    )
    body = json.loads(
        httpx_mock.get_requests(url=f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods")[
            0
        ].content
    )
    assert body == [{"vectorId": 41690973, "latestN": 15}]
    series = result.series[0]
    # The published values stay, for the requested window only.
    assert [o.value for o in series.observations] == [169.9, 169.8, 170.0]
    computed = series.transformed
    assert computed is not None
    assert [p.period for p in computed.points] == ["2026-07", "2026-08", "2026-09"]
    # 100 * (170.0 / 164.9 - 1) = 3.0928: StatCan's The Daily (2026-10-19)
    # reports the September 2026 CPI up 3.1% year over year.
    assert computed.points[-1].value == pytest.approx(3.0927835, abs=1e-6)
    assert round(computed.points[-1].value, 1) == 3.1
    assert computed.points[0].value == pytest.approx(100 * (169.9 / 164.9 - 1))
    assert computed.unit == "percent"
    assert "x_{t-12}" in computed.formula
    assert "Computed by MapleStats" in (result.provenance.coverage or "")


async def test_percent_change_of_the_unemployment_rate_is_in_points(httpx_mock):
    _mock_wds(httpx_mock, [_series(2062815, 14100287, "1.7.1.1.1.1.0.0.0.0", RATE)])
    result = await _fn(tools.wds_get_data_from_vectors)(
        [2062815], latest_n=3, transform="pct_change"
    )
    computed = result.series[0].transformed
    assert computed is not None
    assert computed.transform == "diff"
    assert computed.unit == "percentage points"
    # The Daily (2026-10-09): the rate rose 0.1 percentage points to 6.5%.
    assert [p.value for p in computed.points] == pytest.approx([-0.1, 0.0, 0.1])
    assert "Percent" in computed.notes[0]


async def test_reference_range_starts_earlier_for_the_lag(httpx_mock):
    def respond(request):
        return httpx.Response(200, json=[_series(41690973, 18100004, "2.2.0.0.0.0.0.0.0.0", CPI)])

    _mock_wds(httpx_mock, [])
    httpx_mock.add_callback(
        respond,
        url=httpx.URL(
            f"{constants.BASE_URL}getDataFromVectorByReferencePeriodRange",
            params={
                "vectorIds": "41690973",
                "startRefPeriod": "2026-06-01",
                "endReferencePeriod": "2026-09-30",
            },
        ),
    )
    result = await _fn(tools.wds_get_data_by_reference_period_range)(
        [41690973], "2026-07", "2026-09", transform="pct_change"
    )
    computed = result.series[0].transformed
    assert computed is not None
    assert [p.period for p in computed.points] == ["2026-07", "2026-08", "2026-09"]
    assert computed.points[0].value == pytest.approx(100 * (169.9 / 169.3 - 1))
    assert [o.ref_period.isoformat() for o in result.series[0].observations] == [
        "2026-07-01",
        "2026-08-01",
        "2026-09-01",
    ]


async def test_quarterly_average_needs_whole_quarters(httpx_mock):
    _mock_wds(httpx_mock, [_series(41690973, 18100004, "2.2.0.0.0.0.0.0.0.0", CPI)])
    result = await _fn(tools.wds_get_data_from_vectors)(
        [41690973], latest_n=2, frequency="quarterly"
    )
    computed = result.series[0].transformed
    assert computed is not None
    assert [p.period for p in computed.points] == ["2026-Q2", "2026-Q3"]
    assert computed.points[-1].value == pytest.approx((169.9 + 169.8 + 170.0) / 3)
    assert computed.aggregation == "average"


async def test_moving_average_fetches_the_window_and_returns_the_requested_months(httpx_mock):
    _mock_wds(httpx_mock, [_series(41690973, 18100004, "2.2.0.0.0.0.0.0.0.0", CPI[-5:])])
    result = await _fn(tools.wds_get_data_from_vectors)(
        [41690973], latest_n=3, transform="moving_average", window=3
    )
    body = json.loads(
        httpx_mock.get_requests(url=f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods")[
            0
        ].content
    )
    assert body == [{"vectorId": 41690973, "latestN": 5}]  # 3 months and the 2 before them
    series = result.series[0]
    assert [o.value for o in series.observations] == [169.9, 169.8, 170.0]
    computed = series.transformed
    assert computed is not None and computed.window == 3
    assert [p.value for p in computed.points] == pytest.approx(
        [(169.0 + 169.3 + 169.9) / 3, (169.3 + 169.9 + 169.8) / 3, (169.9 + 169.8 + 170.0) / 3]
    )
    assert "moving_average_3 = mean(x_{t-2}, x_{t-1}, x_t)" in computed.formula
    with pytest.raises(client.InvalidInput, match="window"):
        await _fn(tools.wds_get_data_from_vectors)([41690973], transform="moving_average")
