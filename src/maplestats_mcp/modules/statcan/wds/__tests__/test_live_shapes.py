"""WDS behaviour reproduced from live responses captured 2026-10-02.

Every payload below is the shape the real service sent (status codes, JSON
bodies, header-free 404s), so these tests fail on the bugs the live review
found, not just on assumptions the code shares with its mocks.
"""

from __future__ import annotations

import json

import pytest

from maplestats_mcp.modules.statcan.wds import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)

BASE = constants.BASE_URL

# getSeriesInfoFromCubePidCoord for 18100004 / 2.2 (live).
SERIES_INFO_OK = [
    {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": 18100004,
            "coordinate": "2.2.0.0.0.0.0.0.0.0",
            "vectorId": 41690973,
            "frequencyCode": 6,
            "scalarFactorCode": 0,
            "decimals": 1,
            "terminated": 0,
            "SeriesTitleEn": "Canada;All-items",
            "SeriesTitleFr": "Canada;Ensemble",
            "memberUomCode": 17,
        },
    }
]

# getChangedSeriesDataFromVector for a vector that did not change (live: HTTP 404).
NO_CHANGE_404 = {"message": "No changed data found for vector(s). Error code = 3"}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _cube(pid: int, cansim: str, en: str, fr: str = "") -> dict:
    return {
        "productId": pid,
        "cansimId": cansim,
        "cubeTitleEn": en,
        "cubeTitleFr": fr or en,
        "cubeStartDate": "1914-01-01T05:00:00Z",
        "cubeEndDate": "2026-08-01T04:00:00Z",
        "releaseTime": "2026-09-14T12:30:00Z",
        "archived": "2",
        "subjectCode": ["18"],
        "surveyCode": None,
        "frequencyCode": 6,
    }


CUBES = [
    _cube(
        18100004,
        "326-0020",
        "Consumer Price Index, monthly, not seasonally adjusted",
        "Indice des prix à la consommation mensuel, non désaisonnalisé",
    ),
    _cube(
        18100259,
        "326-8023",
        "Historical (real-time) releases of Consumer Price Index (CPI) statistics, "
        "measures of core inflation",
    ),
    _cube(36100431, "", "Vintages of releases of gross domestic product, expenditure-based"),
    _cube(
        14100287,
        "282-0087",
        "Labour force characteristics, monthly, seasonally adjusted",
        "Caractéristiques de la population active, mensuel, désaisonnalisé",
    ),
]


def _mock_cubes(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{BASE}getAllCubesListLite", json=CUBES)


# H1 ---------------------------------------------------------------------


async def test_changed_data_by_coordinate_goes_through_the_vector_endpoint(httpx_mock):
    """Live: {"productId": 18100004, "coordinate": "2.2"} sent to
    getChangedSeriesDataFromCubePidCoord returned vector 74740 of table 23100066.
    The coordinate is now resolved to its vector, so another table's series
    cannot come back; an unchanged series is NotFound."""
    httpx_mock.add_response(url=f"{BASE}getSeriesInfoFromCubePidCoord", json=SERIES_INFO_OK)
    httpx_mock.add_response(
        url=f"{BASE}getChangedSeriesDataFromVector", status_code=404, json=NO_CHANGE_404
    )
    with pytest.raises(NotFound, match="No changed data found"):
        await client.get_changed_series_data_from_cube_pid_coord(18100004, "2.2")
    called = [r.url.path.rsplit("/", 1)[-1] for r in httpx_mock.get_requests()]
    assert called == ["getSeriesInfoFromCubePidCoord", "getChangedSeriesDataFromVector"]
    sent = json.loads(httpx_mock.get_requests()[1].content)
    assert sent == [{"vectorId": 41690973}]


async def test_changed_data_for_another_table_is_refused(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getSeriesInfoFromCubePidCoord", json=SERIES_INFO_OK)
    wrong = {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": 23100066,
            "coordinate": "1.2.0.0.0.0.0.0.0.0",
            "vectorId": 41690973,
            "vectorDataPoint": [],
        },
    }
    httpx_mock.add_response(url=f"{BASE}getChangedSeriesDataFromVector", json=[wrong])
    with pytest.raises(UpstreamError, match="table 23100066"):
        await client.get_changed_series_data_from_cube_pid_coord(18100004, "2.2")


# M1 ---------------------------------------------------------------------


async def test_changed_data_for_unchanged_vector_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}getChangedSeriesDataFromVector", status_code=404, json=NO_CHANGE_404
    )
    with pytest.raises(NotFound):
        await client.get_changed_series_data_from_vector(41690973)


async def test_changed_cube_list_rejects_a_slash_date_before_any_request():
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        await client.get_changed_cube_list("16/09/2026")


async def test_changed_cube_list_rejects_an_impossible_date():
    with pytest.raises(InvalidInput):
        await client.get_changed_cube_list("2026-02-31")


async def test_server_errors_after_retries_are_unavailable_not_raw_httpx(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=f"{BASE}getChangedSeriesList", status_code=502)
    with pytest.raises(UpstreamUnavailable, match="HTTP 502"):
        await client.get_changed_series_list()


# M2 ---------------------------------------------------------------------


async def test_406_message_from_upstream_is_in_the_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}getBulkVectorDataByRange",
        method="POST",
        status_code=406,
        json={"message": "Wrong date format, check manual"},
    )
    with pytest.raises(InvalidInput, match="Wrong date format"):
        await client.get_bulk_vector_data_by_range(
            [41690973], "2024-01-01T08:30", "2024-02-01T08:30"
        )


async def test_bare_dates_are_widened_to_the_full_day(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}getBulkVectorDataByRange",
        method="POST",
        json=[{"status": "SUCCESS", "object": _vector_object()}],
    )
    await client.get_bulk_vector_data_by_range([41690973], "2024-01-01", "2024-02-01")
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent["startDataPointReleaseDate"] == "2024-01-01T00:00"
    assert sent["endDataPointReleaseDate"] == "2024-02-01T23:59"


@pytest.mark.parametrize("bad", ["01/02/2024", "2024-13-01", "2024-01-01 08:30", ""])
async def test_bad_release_datetime_is_rejected_client_side(bad):
    with pytest.raises(InvalidInput, match="start_release_datetime"):
        await client.get_bulk_vector_data_by_range([1], bad, "2024-02-01")


async def test_reference_months_are_widened_to_first_and_last_day(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{BASE}getDataFromVectorByReferencePeriodRange?vectorIds=41690973"
            "&startRefPeriod=2024-01-01&endReferencePeriod=2024-03-31"
        ),
        json=[{"status": "SUCCESS", "object": _vector_object()}],
    )
    result = await client.get_data_from_vector_by_reference_period_range(
        [41690973], "2024-01", "2024-03"
    )
    assert result.series[0].vector_id == 41690973


# M3 ---------------------------------------------------------------------


@pytest.mark.parametrize("given", [18100004, "18100004", 1810000401, "18-10-0004", "18-10-0004-01"])
def test_every_way_of_writing_a_table_number_gives_eight_digits(given):
    assert client.normalize_product_id(given) == 18100004


@pytest.mark.parametrize("bad", [123, "18-10", "abcdefgh", 999999999, ""])
def test_a_non_table_number_is_rejected(bad):
    with pytest.raises(InvalidInput, match="productId"):
        client.normalize_product_id(bad)


async def test_unknown_table_is_not_found_not_an_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}getCubeMetadata",
        method="POST",
        json=[
            {
                "status": "FAILED",
                "object": "The cube product ID 99999999 does not exist. "
                "Error code = CUBE_NOT_AVAILABLE",
            }
        ],
    )
    with pytest.raises(NotFound, match="does not exist"):
        await client.get_cube_metadata(99999999)


async def test_download_link_for_a_table_that_does_not_exist_is_not_returned(httpx_mock):
    """Live: getFullTableDownloadCSV/99999999/en answers with a URL that 404s."""
    _mock_cubes(httpx_mock)
    with pytest.raises(NotFound, match="99999999"):
        await client.get_full_table_download_csv(99999999)
    assert len(httpx_mock.get_requests()) == 1  # only the inventory, no link request


async def test_download_link_for_a_known_table(httpx_mock):
    _mock_cubes(httpx_mock)
    httpx_mock.add_response(
        url=f"{BASE}getFullTableDownloadCSV/18100004/en",
        json={
            "status": "SUCCESS",
            "object": "https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip",
        },
    )
    link = await client.get_full_table_download_csv("18-10-0004-01")
    assert link.product_id == 18100004
    assert link.download_url.endswith("18100004-eng.zip")


# M4 ---------------------------------------------------------------------


def _vector_object(vector_id: int = 41690973) -> dict:
    return {
        "responseStatusCode": 0,
        "productId": 18100004,
        "coordinate": "2.2.0.0.0.0.0.0.0.0",
        "vectorId": vector_id,
        "vectorDataPoint": [
            {
                "refPer": "2026-08-01",
                "refPer2": "",
                "refPerRaw": "2026-08-01",
                "refPerRaw2": "",
                "value": 169.8,
                "decimals": 1,
                "scalarFactorCode": 0,
                "symbolCode": 0,
                "statusCode": 0,
                "securityLevelCode": 0,
                "releaseTime": "2026-09-14T08:30",
                "frequencyCode": 6,
            }
        ],
    }


# getDataFromVectorsAndLatestNPeriods for [41690973, 999999999] (live).
BATCH_PARTIAL = [
    {"status": "SUCCESS", "object": _vector_object()},
    {
        "status": "FAILED",
        "object": {
            "responseStatusCode": 3,
            "productId": 0,
            "coordinate": ".........",
            "vectorId": 999999999,
            "vectorDataPoint": [],
        },
    },
]


async def test_one_bad_vector_does_not_fail_the_batch(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getDataFromVectorsAndLatestNPeriods", json=BATCH_PARTIAL)
    result = await client.get_data_from_vectors_and_latest_n_periods([41690973, 999999999], 1)
    assert [s.vector_id for s in result.series] == [41690973]
    assert [f.vector_id for f in result.failed] == [999999999]
    assert result.series[0].observations[0].scale_multiplier == 1
    assert result.provenance.limits is not None and "1 vector" in result.provenance.limits


async def test_a_batch_of_only_bad_vectors_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}getDataFromVectorsAndLatestNPeriods", json=[BATCH_PARTIAL[1]]
    )
    with pytest.raises(NotFound, match="999999999"):
        await client.get_data_from_vectors_and_latest_n_periods([999999999], 1)


# M5 ---------------------------------------------------------------------


async def test_search_matches_a_table_number_in_every_written_form(httpx_mock):
    _mock_cubes(httpx_mock)
    for query in ("18-10-0004", "18100004", "1810000401", "326-0020"):
        found = await client.search_cubes(query)
        assert [c.product_id for c in found.cubes] == [18100004], query


async def test_search_requires_every_content_word_and_ignores_stopwords(httpx_mock):
    _mock_cubes(httpx_mock)
    found = await client.search_cubes("monthly labour force characteristics for the")
    assert [c.product_id for c in found.cubes] == [14100287]
    assert found.provenance.coverage == "4 tables searched"


async def test_search_is_accent_insensitive_across_languages(httpx_mock):
    _mock_cubes(httpx_mock)
    found = await client.search_cubes("population active desaisonnalise")
    assert [c.product_id for c in found.cubes] == [14100287]


async def test_search_falls_back_to_the_best_partial_match_and_says_so(httpx_mock):
    """Live: "consumer price index alberta" returned 0 because Alberta is a
    dimension member, not a title word."""
    _mock_cubes(httpx_mock)
    found = await client.search_cubes("consumer price index alberta")
    assert [c.product_id for c in found.cubes] == [18100004, 18100259]
    assert found.provenance.coverage is not None
    assert "3 of them" in found.provenance.coverage


async def test_real_time_tables_are_flagged(httpx_mock):
    _mock_cubes(httpx_mock)
    found = await client.search_cubes(limit=10)
    flags = {c.product_id: c.real_time for c in found.cubes}
    assert flags == {18100004: False, 18100259: True, 36100431: True, 14100287: False}


async def test_search_pages_with_limit_and_offset(httpx_mock):
    _mock_cubes(httpx_mock)
    first = await client.search_cubes(limit=2)
    assert (first.total_count, first.returned_count) == (4, 2)
    assert first.provenance.limits is not None and "2 of 4" in first.provenance.limits
    second = await client.search_cubes(limit=2, offset=2)
    assert [c.product_id for c in second.cubes] == [36100431, 14100287]
    assert second.provenance.limits is None


async def test_search_limit_is_bounded():
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_cubes("cpi", limit=constants.SEARCH_LIMIT_MAX + 1)


# M6 ---------------------------------------------------------------------


async def test_series_info_keeps_the_fields_wds_returns(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getSeriesInfoFromVector", json=SERIES_INFO_OK)
    info = await client.get_series_info_from_vector(41690973)
    assert info.series_title_en == "Canada;All-items"
    assert info.series_title_fr == "Canada;Ensemble"
    assert (info.frequency_code, info.scalar_factor_code, info.decimals) == (6, 0, 1)
    assert info.terminated is False
    assert info.member_uom_code == 17


async def test_unknown_vector_is_not_found_not_vector_zero(httpx_mock):
    """Live: SUCCESS with responseStatusCode 4 and empty fields for vector 999999999."""
    httpx_mock.add_response(
        url=f"{BASE}getSeriesInfoFromVector",
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "responseStatusCode": 4,
                    "productId": 0,
                    "coordinate": ".........",
                    "vectorId": 999999999,
                    "frequencyCode": None,
                    "scalarFactorCode": None,
                    "decimals": None,
                    "terminated": None,
                    "SeriesTitleEn": None,
                    "SeriesTitleFr": None,
                    "memberUomCode": None,
                },
            }
        ],
    )
    with pytest.raises(NotFound):
        await client.get_series_info_from_vector(999999999)


# H5 ---------------------------------------------------------------------


def _metadata(n_members: int, n_footnotes: int) -> list[dict]:
    members = [
        {
            "memberId": i,
            "parentMemberId": None,
            "memberNameEn": f"Place {i}",
            "memberNameFr": f"Lieu {i}",
            "classificationCode": "1",
            "classificationTypeCode": "1",
            "geoLevel": 2,
            "vintage": None,
            "terminated": 0,
            "memberUomCode": None,
        }
        for i in range(1, n_members + 1)
    ]
    return [
        {
            "status": "SUCCESS",
            "object": {
                "responseStatusCode": 0,
                "productId": 98100002,
                "cansimId": None,
                "cubeTitleEn": "Population and dwelling counts",
                "cubeTitleFr": "Chiffres de population et des logements",
                "cubeStartDate": "2021-01-01",
                "cubeEndDate": "2021-01-01",
                "frequencyCode": 18,
                "nbSeriesCube": 1,
                "nbDatapointsCube": 1,
                "releaseTime": "2022-02-09T08:30",
                "archiveStatusCode": "2",
                "archiveStatusEn": "CURRENT",
                "archiveStatusFr": "ACTIF",
                "subjectCode": ["17"],
                "surveyCode": None,
                "cubeNotes": None,
                "dimension": [
                    {
                        "dimensionPositionId": 1,
                        "dimensionNameEn": "Geography",
                        "dimensionNameFr": "Géographie",
                        "hasUom": False,
                        "member": members,
                    },
                    {
                        "dimensionPositionId": 2,
                        "dimensionNameEn": "Population and dwelling counts",
                        "dimensionNameFr": "Population et logements",
                        "hasUom": True,
                        "member": members[:2],
                    },
                ],
                "footnote": [
                    {"footnoteId": i, "footnotesEn": f"Note {i}", "footnotesFr": f"Note {i}"}
                    for i in range(1, n_footnotes + 1)
                ],
                "correction": [],
            },
        }
    ]


async def test_metadata_caps_members_and_footnotes_and_says_so(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getCubeMetadata", method="POST", json=_metadata(5000, 60))
    meta = await client.get_cube_metadata(98100002)
    geography = meta.dimensions[0]
    assert (geography.member_count, len(geography.members)) == (5000, 100)
    assert len(meta.dimensions[1].members) == 2
    assert (len(meta.footnotes), meta.footnote_count) == (25, 60)
    assert meta.provenance.limits is not None
    assert "dimension 1: 100 of 5000" in meta.provenance.limits
    assert "footnotes: 25 of 60" in meta.provenance.limits


async def test_metadata_can_page_filter_and_pick_a_dimension(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getCubeMetadata", method="POST", json=_metadata(5000, 0))
    meta = await client.get_cube_metadata(
        98100002, dimension=1, member_query="place 42", member_limit=5
    )
    # Each word must occur somewhere in the name: "42" is in 199 of the numbers 1-5000.
    assert meta.dimensions[0].members_matched == sum("42" in str(i) for i in range(1, 5001))
    assert len(meta.dimensions[0].members) == 5
    assert meta.dimensions[1].members == []  # not the chosen dimension
    paged = await client.get_cube_metadata(98100002, dimension=1, member_offset=4990)
    assert [m.member_id for m in paged.dimensions[0].members][-1] == 5000
    assert paged.provenance.limits is None


async def test_metadata_unknown_dimension_is_invalid(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}getCubeMetadata", method="POST", json=_metadata(3, 0))
    with pytest.raises(InvalidInput, match="no dimension 9"):
        await client.get_cube_metadata(98100002, dimension=9)


async def test_code_sets_are_capped_per_category(httpx_mock):
    subjects = [
        {"subjectCode": str(i), "subjectEn": f"Subject {i}", "subjectFr": f"Sujet {i}"}
        for i in range(300)
    ]
    httpx_mock.add_response(
        url=f"{BASE}getCodeSets", json={"status": "SUCCESS", "object": {"subject": subjects}}
    )
    capped = await client.get_code_sets()
    assert len(capped.subject) == constants.CODE_SET_LIMIT_DEFAULT
    assert capped.counts["subject"] == 300
    assert (
        capped.provenance.limits is not None and "subject: 100 of 300" in capped.provenance.limits
    )
    one = await client.get_code_sets(category="subject", query="sujet 29", limit=50)
    assert len(one.subject) == sum("29" in str(i) for i in range(300)) and one.scalar == []


# L3 ---------------------------------------------------------------------


async def test_error_text_follows_lang(httpx_mock):
    client.use_lang("fr")
    try:
        with pytest.raises(InvalidInput, match="Aucun|AAAA-MM-JJ"):
            await client.get_changed_cube_list("16/09/2026")
        httpx_mock.add_response(url=f"{BASE}getChangedSeriesList", status_code=409)
        with pytest.raises(Exception, match="verrouillée"):
            await client.get_changed_series_list()
    finally:
        client.use_lang("en")
