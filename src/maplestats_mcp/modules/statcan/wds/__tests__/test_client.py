"""Tests for the real gaps this module fixes that every benchmark reviewed
either got wrong or skipped: the 409 lock-window signal, and never
auto-applying scalarFactorCode."""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.statcan.wds import client, constants
from maplestats_mcp.modules.statcan.wds.schemas import apply_scalar_factor
from maplestats_mcp.shared.errors import DataLocked, InvalidInput, UpstreamUnavailable


async def test_get_cube_metadata_raises_data_locked_on_409(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata", method="POST", status_code=409
    )
    with pytest.raises(DataLocked):
        await client.get_cube_metadata(18100004)


async def test_get_all_cubes_list_raises_data_locked_on_409(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}getAllCubesListLite", status_code=409)
    with pytest.raises(DataLocked):
        await client.get_all_cubes_list(lite=True)


async def test_observation_value_is_not_auto_scaled():
    obj = {
        "productId": 18100004,
        "coordinate": "2.2.0.0.0.0.0.0.0.0",
        "vectorId": 41690973,
        "vectorDataPoint": [
            {
                "refPer": "2026-07-01",
                "value": 169.9,
                "decimals": 1,
                "scalarFactorCode": 3,  # "thousands" — must NOT be applied to value below
                "symbolCode": 0,
                "statusCode": 0,
                "securityLevelCode": 0,
            }
        ],
    }
    result = client._vector_data_from_json(obj, source_url="https://example.invalid", cached=False)
    obs = result.observations[0]
    assert obs.value == 169.9  # unscaled, exactly as StatCan returned it
    assert obs.scalar_factor_code == 3
    assert obs.value is not None
    assert apply_scalar_factor(obs.value, obs.scalar_factor_code) == 169900.0


async def test_observation_handles_explicit_null_scalar_fields():
    """WDS sends explicit JSON null (not an absent key) for these fields on
    some cubes — `.get(key, 0)` alone doesn't catch that, since the
    default only applies when the key is missing."""
    obj = {
        "productId": 18100004,
        "coordinate": "2.2.0.0.0.0.0.0.0.0",
        "vectorId": 41690973,
        "vectorDataPoint": [
            {
                "refPer": "2026-07-01",
                "value": None,
                "decimals": None,
                "scalarFactorCode": None,
                "symbolCode": None,
                "statusCode": None,
                "securityLevelCode": None,
            }
        ],
    }
    result = client._vector_data_from_json(obj, source_url="https://example.invalid", cached=False)
    obs = result.observations[0]
    assert obs.value is None
    assert obs.decimals == 0
    assert obs.scalar_factor_code == 0
    assert obs.symbol_code == 0
    assert obs.status_code == 0
    assert obs.security_level_code == 0


def test_pad_coordinate_pads_short_coordinate_to_ten_positions():
    assert client._pad_coordinate("2.2") == "2.2.0.0.0.0.0.0.0.0"


def test_pad_coordinate_rejects_too_many_dimensions():
    with pytest.raises(InvalidInput):
        client._pad_coordinate("1.2.3.4.5.6.7.8.9.10.11")


def test_pad_coordinate_rejects_non_numeric_part():
    with pytest.raises(InvalidInput):
        client._pad_coordinate("2.abc.0")


def test_pad_coordinate_rejects_empty_part():
    with pytest.raises(InvalidInput):
        client._pad_coordinate("1..2")


async def test_get_cube_metadata_parses_real_footnote_shape(httpx_mock):
    """Footnotes are {footnoteId, footnotesEn, footnotesFr, link} objects,
    not plain strings — a real gap found by exercising this live."""
    httpx_mock.add_response(
        json=[
            {
                "status": "SUCCESS",
                "object": {
                    "productId": 18100004,
                    "cubeTitleEn": "CPI",
                    "cubeTitleFr": "IPC",
                    "cubeStartDate": "1914-01-01",
                    "cubeEndDate": "2026-08-01",
                    "frequencyCode": 6,
                    "nbSeriesCube": 2139,
                    "nbDatapointsCube": 1152913,
                    "releaseTime": "2026-09-14T08:30",
                    "footnote": [
                        {"footnoteId": 1, "footnotesEn": "note en", "footnotesFr": "note fr"}
                    ],
                    "dimension": [],
                },
            }
        ]
    )
    result = await client.get_cube_metadata(18100004)
    assert len(result.footnotes) == 1
    assert result.footnotes[0].text_en == "note en"
    assert result.footnotes[0].text_fr == "note fr"


async def test_get_code_sets_parses_all_real_field_name_variants(httpx_mock):
    """survey/subject/classificationType have no "Desc" infix and
    terminated uses an entirely different key set (codeId/codeTextEn/Fr)
    — both confirmed live, both wrong in the first implementation."""
    httpx_mock.add_response(
        json={
            "object": {
                "scalar": [
                    {
                        "scalarFactorCode": 0,
                        "scalarFactorDescEn": "units",
                        "scalarFactorDescFr": "unites",
                    }
                ],
                "frequency": [
                    {
                        "frequencyCode": 1,
                        "frequencyDescEn": "Daily",
                        "frequencyDescFr": "Quotidienne",
                    }
                ],
                "symbol": [{"symbolCode": 0, "symbolDescEn": "normal", "symbolDescFr": "normal"}],
                "status": [{"statusCode": 0, "statusDescEn": "normal", "statusDescFr": "normal"}],
                "uom": [{"memberUomCode": 0, "memberUomEn": None, "memberUomFr": None}],
                "survey": [{"surveyCode": 1, "surveyEn": "Labour Force Survey", "surveyFr": "EPA"}],
                "subject": [{"subjectCode": 1, "subjectEn": "Economy", "subjectFr": "Economie"}],
                "classificationType": [
                    {
                        "classificationTypeCode": 1,
                        "classificationTypeEn": "Geography",
                        "classificationTypeFr": "Geographie",
                    }
                ],
                "securityLevel": [
                    {
                        "securityLevelCode": 0,
                        "securityLevelDescEn": "public",
                        "securityLevelDescFr": "public",
                    }
                ],
                "terminated": [{"codeId": 0, "codeTextEn": "active", "codeTextFr": "actif"}],
            }
        }
    )
    result = await client.get_code_sets()
    assert result.survey[0].description_en == "Labour Force Survey"
    assert result.subject[0].description_en == "Economy"
    assert result.classification_type[0].description_en == "Geography"
    assert result.terminated[0].code == 0
    assert result.terminated[0].description_en == "active"
    # uom code 0 legitimately has no description in either language.
    assert result.uom[0].description_en is None


async def test_get_changed_cube_list_defaults_to_todays_date_when_omitted(httpx_mock):
    """A bare call with no date returns HTTP 404 from WDS — confirmed
    live. Must default client-side to today's ET date, not omit it."""
    httpx_mock.add_response(json={"status": "SUCCESS", "object": []})
    await client.get_changed_cube_list()
    request = httpx_mock.get_requests()[0]
    assert str(request.url).rstrip("/") != f"{constants.BASE_URL}getChangedCubeList".rstrip("/")
    assert "getChangedCubeList/" in str(request.url)


async def test_get_changed_series_list_never_appends_a_date(httpx_mock):
    """WDS documents this method as never accepting a date parameter,
    unlike getChangedCubeList — confirmed live (appending one 404s)."""
    httpx_mock.add_response(json={"status": "SUCCESS", "object": []})
    await client.get_changed_series_list()
    request = httpx_mock.get_requests()[0]
    assert str(request.url) == f"{constants.BASE_URL}getChangedSeriesList"


async def test_get_bulk_vector_data_by_range_sends_flat_body_not_list(httpx_mock):
    """Confirmed live: wrapping the body in a one-item list (the pattern
    every other WDS POST method uses) gets HTTP 406 from this specific
    endpoint — it wants a flat object."""
    httpx_mock.add_response(
        json=[
            {
                "status": "SUCCESS",
                "object": {"productId": 1, "coordinate": "1", "vectorId": 1, "vectorDataPoint": []},
            }
        ]
    )
    await client.get_bulk_vector_data_by_range([41690973], "2024-01-01T08:30", "2024-06-01T08:30")
    request = httpx_mock.get_requests()[0]
    import json

    sent_body = json.loads(request.content)
    assert isinstance(sent_body, dict)
    assert sent_body["vectorIds"] == ["41690973"]


async def test_get_cube_metadata_raises_invalid_input_on_406(httpx_mock):
    """Confirmed live: WDS returns 406, not 404, for a nonexistent
    productId."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata", method="POST", status_code=406
    )
    with pytest.raises(InvalidInput):
        await client.get_cube_metadata(999999999)


async def test_timeout_raises_upstream_unavailable_with_clear_message(httpx_mock):
    """getChangedSeriesList is confirmed live to sometimes not respond at
    all within a generous timeout (a real upstream reliability issue,
    reproduced independently via curl with a 60s timeout). Whatever the
    cause, a bare message-less ReadTimeout is a poor error for an agent
    to receive — it must translate to a clear UpstreamUnavailable."""
    # shared/http.py retries up to 3 times on ReadTimeout — the mock must
    # supply it for every attempt, not just the first.
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.get_changed_series_list()
