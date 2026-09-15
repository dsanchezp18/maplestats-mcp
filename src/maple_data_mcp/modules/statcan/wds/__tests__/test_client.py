"""Tests for the real gaps this module fixes that every benchmark reviewed
either got wrong or skipped: the 409 lock-window signal, and never
auto-applying scalarFactorCode."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.wds import client, constants
from maple_data_mcp.modules.statcan.wds.schemas import apply_scalar_factor
from maple_data_mcp.shared.errors import DataLocked, InvalidInput


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


def test_pad_coordinate_pads_short_coordinate_to_ten_positions():
    assert client._pad_coordinate("2.2") == "2.2.0.0.0.0.0.0.0.0"


def test_pad_coordinate_truncates_long_coordinate_to_ten_positions():
    assert client._pad_coordinate("1.2.3.4.5.6.7.8.9.10.11") == "1.2.3.4.5.6.7.8.9.10"


def test_pad_coordinate_rejects_non_numeric_part():
    with pytest.raises(InvalidInput):
        client._pad_coordinate("2.abc.0")
