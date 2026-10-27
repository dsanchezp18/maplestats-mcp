import json

import httpx
import pytest

from maplestats_mcp.modules.statcan.wds import constants, vintage
from maplestats_mcp.shared.errors import InvalidInput, NotFound

METADATA_URL = f"{constants.BASE_URL}getCubeMetadata"
DATA_URL = f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods"


def _member(member_id, name):
    return {"memberId": member_id, "memberNameEn": name, "memberNameFr": name}


def _dimension(position, name, members):
    return {
        "dimensionPositionId": position,
        "dimensionNameEn": name,
        "dimensionNameFr": name,
        "member": members,
    }


# Shaped like 18-10-0256 and its real-time table 18-10-0259 (live 2026-10-27),
# with the measure numbered differently in the two tables, as the NAICS
# dimension of 12-10-0163 and 12-10-0165 is.
REGULAR = {
    "productId": 18100256,
    "cubeTitleEn": "Consumer Price Index (CPI) statistics",
    "cubeEndDate": "2026-09-01",
    "dimension": [
        _dimension(1, "Geography", [_member(1, "Canada")]),
        _dimension(
            2,
            "Alternative measures",
            [
                _member(3, "CPI-trim (year-over-year percent change)"),
                _member(9, "Not in real time"),
            ],
        ),
    ],
}
REAL_TIME = {
    "productId": 18100259,
    "cubeTitleEn": "Historical (real-time) releases of Consumer Price Index (CPI) statistics",
    "cubeEndDate": "2026-03-01",
    "dimension": [
        _dimension(1, "Geography", [_member(1, "Canada")]),
        _dimension(
            2, "Alternative measures", [_member(7, "CPI-trim (year-over-year  percent change)")]
        ),
        _dimension(
            3,
            "Release",
            [
                _member(113, "April 20, 2026"),
                _member(112, "March 16, 2026"),
                _member(1, "December 22, 2016"),
            ],
        ),
    ],
}


def _metadata(httpx_mock):
    def respond(request):
        pid = json.loads(request.content)[0]["productId"]
        obj = REAL_TIME if pid == 18100259 else REGULAR
        return httpx.Response(200, json=[{"status": "SUCCESS", "object": obj}])

    httpx_mock.add_callback(respond, url=METADATA_URL, method="POST", is_reusable=True)


def _point(ref, value, status=0):
    return {
        "refPer": ref,
        "value": value,
        "decimals": 1,
        "scalarFactorCode": 0,
        "symbolCode": 0,
        "statusCode": status,
        "securityLevelCode": 0,
        "releaseTime": "2026-05-04T08:30" if value is not None else None,
    }


async def test_series_as_of_reads_the_release_on_or_before_the_date(httpx_mock):
    _metadata(httpx_mock)
    httpx_mock.add_response(
        url=DATA_URL,
        method="POST",
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "productId": 18100259,
                    "coordinate": "1.7.112.0.0.0.0.0.0.0",
                    "vectorId": 1864634477,
                    "vectorDataPoint": [
                        _point("2025-12-01", 2.7),
                        _point("2026-01-01", 2.4),
                        _point("2026-02-01", 2.3),
                        _point("2026-03-01", None, status=1),
                    ],
                },
            }
        ],
    )
    result = await vintage.get_series_as_of(18100256, "1.3", "2026-03-20", latest_n=2)

    assert result.release_date.isoformat() == "2026-03-16"
    # Matched on the member's name, not its id (3 in one table, 7 in the other).
    assert result.real_time_coordinate == "1.7.112.0.0.0.0.0.0.0"
    assert [(o.ref_period.isoformat(), o.value) for o in result.observations] == [
        ("2026-01-01", 2.4),
        ("2026-02-01", 2.3),
    ]
    assert result.earliest_release.isoformat() == "2016-12-22"
    assert result.latest_release.isoformat() == "2026-04-20"
    assert "2026-03-16" in result.notes[0]
    body = json.loads(httpx_mock.get_requests(url=DATA_URL)[0].content)
    assert body[0]["productId"] == 18100259
    assert body[0]["latestN"] >= 2


async def test_a_table_with_no_real_time_pair_is_an_error(httpx_mock):
    with pytest.raises(NotFound, match="no revision history"):
        await vintage.get_series_as_of(18100004, "1.2", "2025-01-01")


async def test_a_real_time_table_is_refused():
    with pytest.raises(InvalidInput, match="itself a real-time table"):
        await vintage.get_series_as_of(18100259, "1.1", "2025-01-01")


async def test_a_date_before_the_first_release_is_an_error(httpx_mock):
    _metadata(httpx_mock)
    with pytest.raises(NotFound, match="starts with the release of 2016-12-22"):
        await vintage.get_series_as_of(18100256, "1.3", "2010-01-01")


async def test_a_member_the_real_time_table_lacks_is_an_error(httpx_mock):
    _metadata(httpx_mock)
    with pytest.raises(NotFound, match="has no revision history"):
        await vintage.get_series_as_of(18100256, "1.9", "2026-01-01")


async def test_as_of_must_be_a_date():
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        await vintage.get_series_as_of(18100256, "1.3", "March 2026")
