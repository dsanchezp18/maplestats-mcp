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


# Members that share a name. The real-time table numbers its members differently, so the
# name is all that links the two tables; when it is not unique the parent member (the
# hierarchy position) has to decide, and when that cannot either, the answer is an error
# listing the candidates, not the first hit.
def _child(member_id, name, parent):
    return {**_member(member_id, name), "parentMemberId": parent}


def _release_dimension(position):
    return _dimension(position, "Release", [_member(112, "March 16, 2026")])


def _serve_metadata(httpx_mock, regular_dims, rt_dims):
    regular = {**REGULAR, "dimension": regular_dims}
    real_time = {**REAL_TIME, "dimension": rt_dims}

    def respond(request):
        pid = json.loads(request.content)[0]["productId"]
        obj = real_time if pid == 18100259 else regular
        return httpx.Response(200, json=[{"status": "SUCCESS", "object": obj}])

    httpx_mock.add_callback(respond, url=METADATA_URL, method="POST", is_reusable=True)


def _data_response(httpx_mock, coordinate):
    httpx_mock.add_response(
        url=DATA_URL,
        method="POST",
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "productId": 18100259,
                    "coordinate": coordinate,
                    "vectorId": 1,
                    "vectorDataPoint": [_point("2026-02-01", 2.3)],
                },
            }
        ],
    )


_SECTORS = [
    _dimension(
        1,
        "Sector",
        [
            _member(1, "Goods"),
            _member(2, "Services"),
            _child(3, "Other", 1),
            _child(4, "Other", 2),
        ],
    )
]


async def test_a_name_under_two_parents_is_matched_through_its_parent(httpx_mock):
    # Real-time ids 10 and 11 are swapped against the regular table's 1 and 2, and
    # both "Other" members carry the same name: the first hit would be the Services one.
    rt_dims = [
        _dimension(
            1,
            "Sector",
            [
                _member(10, "Services"),
                _member(11, "Goods"),
                _child(12, "Other", 10),
                _child(13, "Other", 11),
            ],
        ),
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, _SECTORS, rt_dims)
    _data_response(httpx_mock, "13.112.0.0.0.0.0.0.0.0")

    result = await vintage.get_series_as_of(18100256, "3", "2026-03-20", latest_n=1)

    # Regular member 3 is "Other" under Goods: real-time member 13, not 12.
    assert result.real_time_coordinate == "13.112.0.0.0.0.0.0.0.0"
    body = json.loads(httpx_mock.get_requests(url=DATA_URL)[0].content)
    assert body[0]["coordinate"] == "13.112.0.0.0.0.0.0.0.0"


async def test_a_name_no_parent_can_tell_apart_lists_the_candidates(httpx_mock):
    rt_dims = [
        _dimension(
            1, "Sector", [_member(20, "Goods"), _member(21, "Goods"), _member(22, "Services")]
        ),
        _release_dimension(2),
    ]
    regular_dims = [_dimension(1, "Sector", [_member(1, "Goods"), _member(2, "Services")])]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)

    with pytest.raises(InvalidInput, match="20.*21"):
        await vintage.get_series_as_of(18100256, "1", "2026-03-20")


async def test_a_name_the_real_time_table_carries_only_under_another_parent_is_refused(
    httpx_mock,
):
    # The regular table has "Other" under Goods and under Services; the real-time table
    # keeps only the Services one. Asking for the Goods one must not read Services' series.
    rt_dims = [
        _dimension(
            1,
            "Sector",
            [_member(10, "Services"), _member(11, "Goods"), _child(12, "Other", 10)],
        ),
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, _SECTORS, rt_dims)

    with pytest.raises(InvalidInput, match="Other"):
        await vintage.get_series_as_of(18100256, "3", "2026-03-20")

    # The Services one is the same member in both tables.
    _data_response(httpx_mock, "12.112.0.0.0.0.0.0.0.0")
    result = await vintage.get_series_as_of(18100256, "4", "2026-03-20", latest_n=1)
    assert result.real_time_coordinate == "12.112.0.0.0.0.0.0.0.0"


async def test_two_dimensions_with_one_name_are_told_apart_by_position(httpx_mock):
    # Both tables have two dimensions named "Measure"; matching by name alone sent the
    # first one to the last one's members and failed, or read the wrong one.
    regular_dims = [
        _dimension(1, "Measure", [_member(1, "Rate")]),
        _dimension(2, "Geography", [_member(1, "Canada")]),
        _dimension(3, "Measure", [_member(1, "Level")]),
    ]
    rt_dims = [
        _dimension(1, "Measure", [_member(5, "Rate")]),
        _dimension(2, "Geography", [_member(1, "Canada")]),
        _dimension(3, "Measure", [_member(6, "Level")]),
        _release_dimension(4),
    ]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)
    _data_response(httpx_mock, "5.1.6.112.0.0.0.0.0.0")

    result = await vintage.get_series_as_of(18100256, "1.1.1", "2026-03-20", latest_n=1)

    assert result.real_time_coordinate == "5.1.6.112.0.0.0.0.0.0"


def _bilingual(member_id, name_en, name_fr, parent=None):
    return {
        "memberId": member_id,
        "memberNameEn": name_en,
        "memberNameFr": name_fr,
        "parentMemberId": parent,
    }


def _ambiguous_other(httpx_mock):
    """'Other' twice under one parent in the real-time table, once in the regular one."""
    regular_dims = [
        {
            **_dimension(
                1,
                "Sector",
                [_bilingual(1, "Goods", "Biens"), _bilingual(3, "Other", "Autres", 1)],
            ),
            "dimensionNameFr": "Secteur",
        }
    ]
    rt_dims = [
        {
            **_dimension(
                1,
                "Sector",
                [
                    _bilingual(10, "Goods", "Biens"),
                    _bilingual(11, "Other", "Autres", 10),
                    _bilingual(12, "Other", "Autres", 10),
                ],
            ),
            "dimensionNameFr": "Secteur",
        },
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)


async def test_the_candidates_are_listed_in_english_for_an_english_call(httpx_mock):
    _ambiguous_other(httpx_mock)
    with pytest.raises(InvalidInput) as raised:
        await vintage.get_series_as_of(18100256, "3", "2026-03-20")
    message = str(raised.value)
    assert "11 ('Other', under 'Goods')" in message and "12 ('Other', under 'Goods')" in message


async def test_the_candidates_are_listed_in_french_for_a_french_call(httpx_mock):
    _ambiguous_other(httpx_mock)
    token = vintage._LANG.set("fr")
    try:
        with pytest.raises(InvalidInput) as raised:
            await vintage.get_series_as_of(18100256, "3", "2026-03-20")
    finally:
        vintage._LANG.reset(token)
    message = str(raised.value).replace(" ", " ")
    # Names, parents and the connecting word are French; no English text is left in it.
    assert "11 (« Autres », sous « Biens »)" in message
    assert "12 (« Autres », sous « Biens »)" in message
    assert "Other" not in message and "Goods" not in message and "under" not in message


def _coded(member_id, name, code, parent=None):
    return {**_member(member_id, name), "parentMemberId": parent, "classificationCode": code}


def _two_others_with_codes():
    """'Other' under Goods (code A1) and under Services (code B2) in the regular table; the
    real-time table words the two parents differently."""
    regular_dims = [
        _dimension(
            1,
            "Sector",
            [
                _member(1, "Goods"),
                _member(2, "Services"),
                _coded(3, "Other", "A1", 1),
                _coded(4, "Other", "B2", 2),
            ],
        )
    ]
    return regular_dims


async def test_a_parent_worded_differently_is_decided_by_the_classification_code(httpx_mock):
    # "Goods" is "Goods-producing industries" in the real-time table, so no "Other" sits
    # under a parent of the same name; exactly one of them has the code A1.
    rt_dims = [
        _dimension(
            1,
            "Sector",
            [
                _member(10, "Goods-producing industries"),
                _member(11, "Service-producing industries"),
                _coded(12, "Other", "B2", 11),
                _coded(13, "Other", "A1", 10),
            ],
        ),
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, _two_others_with_codes(), rt_dims)
    _data_response(httpx_mock, "13.112.0.0.0.0.0.0.0.0")

    result = await vintage.get_series_as_of(18100256, "3", "2026-03-20", latest_n=1)

    assert result.real_time_coordinate == "13.112.0.0.0.0.0.0.0.0"


async def test_a_parent_worded_differently_and_no_matching_code_is_still_refused(httpx_mock):
    rt_dims = [
        _dimension(
            1,
            "Sector",
            [
                _member(10, "Goods-producing industries"),
                _member(11, "Service-producing industries"),
                _coded(12, "Other", "Z8", 11),
                _coded(13, "Other", "Z9", 10),
            ],
        ),
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, _two_others_with_codes(), rt_dims)

    with pytest.raises(InvalidInput, match="12.*13"):
        await vintage.get_series_as_of(18100256, "3", "2026-03-20")


async def _in_french(call):
    token = vintage._LANG.set("fr")
    try:
        await call
    finally:
        vintage._LANG.reset(token)


def _no_french(member_id, name, parent=None):
    """A member as WDS sometimes sends it: no French name at all."""
    return {"memberId": member_id, "memberNameEn": name, "parentMemberId": parent}


async def test_a_shared_name_without_a_french_name_is_refused_in_french(httpx_mock):
    regular_dims = [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Sector",
            "member": [_no_french(1, "Goods"), _no_french(3, "Other", 1)],
        }
    ]
    rt_dims = [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Sector",
            "member": [
                _no_french(10, "Goods"),
                _no_french(11, "Other", 10),
                _no_french(12, "Other", 10),
            ],
        },
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)

    with pytest.raises(InvalidInput, match="nom partagé") as raised:
        await _in_french(vintage.get_series_as_of(18100256, "3", "2026-03-20"))

    # The English names stand in for the missing French ones.
    assert "« Other » (Sector)" in str(raised.value).replace(" ", " ")


async def test_a_member_the_real_time_table_lacks_is_explained_without_a_french_name(httpx_mock):
    regular_dims = [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Sector",
            "member": [_no_french(1, "Goods"), _no_french(2, "Only here")],
        }
    ]
    rt_dims = [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Sector",
            "member": [_no_french(10, "Goods")],
        },
        _release_dimension(2),
    ]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)

    with pytest.raises(NotFound, match="n'a pas d'historique") as raised:
        await _in_french(vintage.get_series_as_of(18100256, "2", "2026-03-20"))
    assert "« Only here » (Sector)" in str(raised.value).replace(" ", " ")

    with pytest.raises(NotFound, match="n'a pas de membre 9") as raised:
        await _in_french(vintage.get_series_as_of(18100256, "9", "2026-03-20"))
    assert "dimension 1 (Sector)" in str(raised.value)


async def test_two_dimensions_that_cannot_be_told_apart_are_explained_without_a_french_name(
    httpx_mock,
):
    def dim(position, name):
        return {
            "dimensionPositionId": position,
            "dimensionNameEn": name,
            "member": [_no_french(1, "Rate")],
        }

    # Regular dimension 3 is "Measure"; the real-time table has two of them, at 1 and 4.
    regular_dims = [dim(1, "Measure"), dim(2, "Geography"), dim(3, "Measure")]
    rt_dims = [dim(1, "Measure"), dim(2, "Geography"), dim(4, "Measure"), _release_dimension(5)]
    _serve_metadata(httpx_mock, regular_dims, rt_dims)

    with pytest.raises(InvalidInput, match="2 dimensions") as raised:
        await _in_french(vintage.get_series_as_of(18100256, "1.1.1", "2026-03-20"))
    assert "nommées 'Measure'" in str(raised.value)
