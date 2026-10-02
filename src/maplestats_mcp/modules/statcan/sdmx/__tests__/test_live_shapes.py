"""SDMX client cases shaped like what www150.statcan.gc.ca really returned
when probed on 2026-10-02: empty and truncated structure documents, a key
that matches nothing (HTTP 200 with malformed XML), 406 bodies, 404/5xx and
network failures. The well-formed fixtures in test_client.py cannot catch
these."""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.statcan.sdmx import client, constants
from maplestats_mcp.modules.statcan.sdmx.__tests__.test_client import (
    _DATA_XML,
    _STRUCTURE_XML,
    _parse,
)
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


_DATA_URL = f"{constants.BASE_URL}data/DF_18100004/2"
_STRUCTURE_URL = f"{constants.BASE_URL}structure/Data_Structure_14100063"
_WDS_METADATA_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getCubeMetadata"

# HTTP 200 whose only Series tag is a stray closing one: what StatCan returns
# for a key matching no series (the parser reported "mismatched tag").
_NO_MATCH_XML = (
    "<?xml version='1.0' encoding='UTF-8'?><message:GenericData "
    'xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
    'xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic">'
    "<message:DataSet></generic:Series> </message:DataSet> </message:GenericData>"
)


def _member(member_id: int, parent: int | None, name: str) -> dict:
    return {
        "memberId": member_id,
        "parentMemberId": parent,
        "memberNameEn": name,
        "memberNameFr": name,
    }


_WDS_METADATA = [
    {
        "status": "SUCCESS",
        "object": {
            "productId": 14100063,
            "cansimId": "282-0073",
            "cubeTitleEn": "Employee wages",
            "cubeTitleFr": "Salaires",
            "cubeStartDate": "1997-01-01",
            "cubeEndDate": "2026-08-01",
            "frequencyCode": 6,
            "nbSeriesCube": 10,
            "nbDatapointsCube": 100,
            "releaseTime": "2026-09-05T08:30",
            "archiveStatusEn": "CURRENT",
            "archiveStatusFr": "ACTIF",
            "subjectCode": None,
            "surveyCode": None,
            "dimension": [
                {
                    "dimensionPositionId": 1,
                    "dimensionNameEn": "Geography",
                    "dimensionNameFr": "Geographie",
                    "hasUom": False,
                    "member": [_member(1, None, "Canada"), _member(2, 1, "Ontario")],
                },
                {
                    "dimensionPositionId": 2,
                    "dimensionNameEn": "North American Industry Classification System (NAICS)",
                    "dimensionNameFr": "SCIAN",
                    "hasUom": False,
                    "member": [_member(7, None, "Total")],
                },
            ],
        },
    }
]


def _many_obs_xml(n: int) -> str:
    obs = "".join(
        f'<generic:Obs><generic:ObsDimension value="{2000 + i // 12}-{i % 12 + 1:02d}"/>'
        f'<generic:ObsValue value="{i}"/></generic:Obs>'
        for i in range(n)
    )
    head = _DATA_XML.split("<generic:Obs>")[0]
    return head + obs + "</generic:Series></message:DataSet></message:GenericData>"


def test_parse_data_cap_keeps_the_newest_observations():
    series, truncated = client._parse_data(_parse(_many_obs_xml(10)), max_rows=3)
    assert [o.value for o in series[0].observations] == [7.0, 8.0, 9.0]
    assert truncated is True


async def test_get_data_defaults_to_latest_observations_without_fetching_structure(httpx_mock):
    # Only the data URL is mocked: a structure request would fail the test.
    httpx_mock.add_response(url=f"{_DATA_URL}?lastNObservations=100", content=_DATA_XML.encode())
    result = await client.get_data(18100004, "2")
    assert result.dataflow_id == "DF_18100004"
    assert "latest 100 observations" in (result.provenance.limits or "")


async def test_get_data_with_period_range_sends_no_default_last_n(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}?startPeriod=2026-01&endPeriod=2026-03", content=_DATA_XML.encode()
    )
    result = await client.get_data(18100004, "2", start_period="2026-01", end_period="2026-03")
    assert result.provenance.limits is None


async def test_get_data_rejects_bad_period_before_calling_upstream():
    with pytest.raises(InvalidInput, match="SDMX period"):
        await client.get_data(18100004, "2", start_period="2026/03")


async def test_get_data_key_matching_nothing_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_18100004/999.999?lastNObservations=100",
        content=_NO_MATCH_XML.encode(),
    )
    with pytest.raises(NotFound, match="matched no series"):
        await client.get_data(18100004, "999.999")


async def test_get_data_406_reports_the_upstream_message(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_14100355/1.1?lastNObservations=100",
        status_code=406,
        json={"message": "Wrong date format or value, check manual"},
    )
    with pytest.raises(InvalidInput, match="Wrong date format or value") as exc_info:
        await client.get_data(14100355, "1.1")
    assert "lastNObservations combined" not in str(exc_info.value)


async def test_get_data_error_text_follows_lang(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_14100355/1.1?lastNObservations=100",
        status_code=406,
        json={"message": "Wrong date format or value, check manual"},
    )
    with pytest.raises(InvalidInput, match="a rejeté la requête"):
        await client.get_data(14100355, "1.1", lang="fr")


async def test_get_data_404_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_1/1?lastNObservations=100", status_code=404
    )
    with pytest.raises(NotFound):
        await client.get_data(1, "1")


async def test_get_data_5xx_is_unavailable_not_raw_httpx(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_1/1?lastNObservations=100",
        status_code=503,
        is_reusable=True,
    )
    with pytest.raises(UpstreamUnavailable, match="503"):
        await client.get_data(1, "1")


async def test_get_data_network_failure_is_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.get_data(1, "1")


async def test_get_data_caps_series_count(httpx_mock):
    one = _DATA_XML.split("<generic:Series>")[1].split("</generic:Series>")[0]
    many = _DATA_XML.replace(
        "<generic:Series>" + one + "</generic:Series>",
        "".join(f"<generic:Series>{one}</generic:Series>" for _ in range(constants.MAX_SERIES + 3)),
    )
    httpx_mock.add_response(url=f"{_DATA_URL}?lastNObservations=100", content=many.encode())
    result = await client.get_data(18100004, "2")
    assert len(result.series) == constants.MAX_SERIES
    assert result.series_total == constants.MAX_SERIES + 3
    assert "first 200 of 203 series" in (result.provenance.limits or "")


@pytest.mark.parametrize(
    "body", [b"", _STRUCTURE_XML.encode()[:200]], ids=["empty-200", "truncated"]
)
async def test_structure_falls_back_to_wds_when_sdmx_body_is_unusable(httpx_mock, body):
    """Live: Data_Structure_14100063 answers HTTP 200 with zero bytes; others are cut off."""
    httpx_mock.add_response(url=_STRUCTURE_URL, content=body)
    httpx_mock.add_response(url=_WDS_METADATA_URL, method="POST", json=_WDS_METADATA)
    result = await client.get_structure(14100063)
    assert result.dataflow_id == "DF_14100063"
    assert [d.dimension_id for d in result.dimensions] == [
        "Geography",
        "North_American_Industry_Classification_System__NAICS_",
    ]
    ontario = result.dimensions[0].codes[1]
    assert (ontario.id, ontario.parent_id) == ("2", "1")
    assert "WDS getCubeMetadata" in (result.provenance.coverage or "")


async def test_structure_is_cached_after_first_call(httpx_mock):
    httpx_mock.add_response(url=_STRUCTURE_URL, content=b"")
    httpx_mock.add_response(url=_WDS_METADATA_URL, method="POST", json=_WDS_METADATA)
    await client.get_structure(14100063)
    await client.get_structure(14100063, dimension_position=1)  # no second request


async def test_structure_pages_codes_and_reports_it(httpx_mock):
    httpx_mock.add_response(url=_STRUCTURE_URL, content=b"")
    httpx_mock.add_response(url=_WDS_METADATA_URL, method="POST", json=_WDS_METADATA)
    result = await client.get_structure(14100063, dimension_position=1, limit=1)
    assert len(result.dimensions) == 1
    assert result.dimensions[0].code_count == 2
    assert len(result.dimensions[0].codes) == 1
    assert "1 of 2 codes" in (result.provenance.limits or "")
    filtered = await client.get_structure(14100063, dimension_position=1, code_query="ontar")
    assert [c.id for c in filtered.dimensions[0].codes] == ["2"]


async def test_structure_unknown_table_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}structure/Data_Structure_99999999",
        status_code=406,
        json={"message": "The parameter is not valid"},
    )
    with pytest.raises(NotFound, match="99999999"):
        await client.get_structure(99999999)


async def test_vector_data_takes_dimension_count_from_wds_not_sdmx_structure(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromVector",
        method="POST",
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "productId": 14100063,
                    "coordinate": "2.7.0.0.0.0.0.0.0.0",
                    "vectorId": 5,
                },
            }
        ],
    )
    httpx_mock.add_response(url=_WDS_METADATA_URL, method="POST", json=_WDS_METADATA)
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}data/DF_14100063/2.7?lastNObservations=2",
        content=_DATA_XML.encode(),
    )
    result = await client.get_vector_data(5, last_n_observations=2)
    assert result.key == "2.7"
