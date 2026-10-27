"""Observation flags and transforms on sdmx_get_data.

The XML is shaped like live responses (2026-10-27): DF_14100325 carries
STATUS_CAN on each Obs, and writes a value it does not publish as "NaN".
"""

from __future__ import annotations

import httpx
import pytest
from defusedxml import ElementTree

from maplestats_mcp.modules.statcan.sdmx import client, constants, tools
from maplestats_mcp.modules.statcan.wds import client as wds_client
from maplestats_mcp.modules.statcan.wds import constants as wds_constants

_NS = (
    'xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic" '
    'xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"'
)


def _xml(observations: str, uom: str = "239", vector: str = "2062815") -> str:
    return (
        f"<?xml version='1.0' encoding='UTF-8'?><message:GenericData {_NS}><message:DataSet>"
        '<generic:Series><generic:SeriesKey><generic:Value id="Geography" value="1"/>'
        "</generic:SeriesKey><generic:Attributes>"
        f'<generic:Value id="VECTOR_ID" value="{vector}"/>'
        '<generic:Value id="SCALAR_FACTOR" value="0"/>'
        '<generic:Value id="NB_DECIMAL" value="1"/>'
        f'<generic:Value id="UOM" value="{uom}"/>'
        f"</generic:Attributes>{observations}</generic:Series></message:DataSet>"
        "</message:GenericData>"
    )


def _obs(period: str, value: str, status: str | None = None) -> str:
    attributes = (
        f'<generic:Attributes><generic:Value id="STATUS_CAN" value="{status}"/>'
        "</generic:Attributes>"
        if status
        else ""
    )
    return (
        f'<generic:Obs><generic:ObsDimension value="{period}"/>'
        f'<generic:ObsValue value="{value}"/>{attributes}</generic:Obs>'
    )


def _fn(t):
    return getattr(t, "fn", t)


async def test_flags_are_read_and_nan_is_missing(httpx_mock):
    legend = await wds_client.observation_legend()
    root = ElementTree.fromstring(
        _xml(_obs("2022-Q2", "NaN", "8") + _obs("2023-Q3", "3910", "7") + _obs("2023-Q4", "5"))
    )
    series, _ = client._parse_data(root, max_rows=500, legend=legend)
    suppressed, caution, plain = series[0].observations
    assert suppressed.value is None
    assert (suppressed.status_code, suppressed.status) == (8, "too unreliable to be published")
    assert (caution.value, caution.status) == (3910.0, "use with caution")
    assert plain.status_code is None and plain.status is None


async def test_unemployment_rate_pct_change_is_in_points(httpx_mock):
    httpx_mock.add_response(
        url=f"{wds_constants.BASE_URL}getCubeMetadata",
        json=[{"status": "SUCCESS", "object": {"productId": 14100287, "frequencyCode": 6}}],
    )
    httpx_mock.add_response(
        url=httpx.URL(
            f"{constants.BASE_URL}data/DF_14100287/1.7.1.1.1.1",
            params={"startPeriod": "2026-06"},
        ),
        content=_xml(
            _obs("2026-06", "6.5")
            + _obs("2026-07", "6.4")
            + _obs("2026-08", "6.4")
            + _obs("2026-09", "6.5")
        ).encode(),
    )
    result = await _fn(tools.sdmx_get_data)(
        14100287, "1.7.1.1.1.1", start_period="2026-07", transform="pct_change"
    )
    series = result.series[0]
    assert [o.period for o in series.observations] == ["2026-07", "2026-08", "2026-09"]
    computed = series.transformed
    assert computed is not None
    assert computed.transform == "diff" and computed.unit == "percentage points"
    assert [p.value for p in computed.points] == pytest.approx([-0.1, 0.0, 0.1])


def test_transform_params_reach_back_in_the_callers_notation():
    request = client.TransformRequest("yoy_pct_change")
    params = client.transform_params(
        {"startPeriod": "2024-01", "endPeriod": "2025-12"}, request, 12, latest_n=None
    )
    assert params == {"startPeriod": "2023-01", "endPeriod": "2025-12"}
    quarterly = client.transform_params(
        {"startPeriod": "2024-Q1"}, client.TransformRequest("diff"), 4, latest_n=None
    )
    assert quarterly == {"startPeriod": "2023-Q4"}
    latest = client.transform_params({"lastNObservations": 3}, request, 12, latest_n=3)
    assert latest == {"lastNObservations": 15}
