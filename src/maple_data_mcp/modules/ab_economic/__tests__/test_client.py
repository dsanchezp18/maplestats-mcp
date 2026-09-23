"""Tests for modules/ab_economic/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maple_data_mcp.modules.ab_economic import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_TABLES_URL = f"{constants.BASE_URL}/api/chart-editor/data-tables"
_TABLES = [
    {"tableName": "UnemploymentRates_14100287"},
    {"tableName": "AESO_PowerGen"},
    {"tableName": "CPI_18100004"},
]


def _row(date: str, value: float) -> dict[str, object]:
    return {"Date": f"{date}T00:00:00", "GeoName": "Alberta", "Value": value}


async def test_list_tables(httpx_mock):
    httpx_mock.add_response(url=_TABLES_URL, json=_TABLES)
    result = await client.list_tables("unemployment")
    assert [t.table for t in result.tables] == ["UnemploymentRates_14100287"]
    assert result.tables[0].statcan_pid == "14100287"
    by_pid = await client.list_tables("18100004")
    assert by_pid.tables[0].table == "CPI_18100004"
    assert (await client.list_tables()).tables[1].statcan_pid is None


async def test_get_table_fields_reads_misspelled_indicator_key(httpx_mock):
    httpx_mock.add_response(url=_TABLES_URL, json=_TABLES)
    httpx_mock.add_response(
        url=re.compile(r".*/field-info/UnemploymentRates_14100287$"),
        json=[
            {"columnName": "GeoName", "dataType": "nvarchar", "values": ["Alberta", "Ontario"]},
            {"columnName": "Value", "dataType": "decimal", "values": [str(i) for i in range(150)]},
        ],
    )
    httpx_mock.add_response(
        url=re.compile(r".*/indicator-info/UnemploymentRates_14100287$"),
        json={"indicaorName": "Unemployment Rate", "period": "Monthly"},
    )
    fields = await client.get_table_fields("unemploymentrates_14100287")
    assert fields.indicator_name == "Unemployment Rate"
    assert fields.period == "Monthly"
    assert fields.columns[0].values == ["Alberta", "Ontario"]
    assert fields.columns[1].values_truncated is True
    assert len(fields.columns[1].values) == constants.FIELD_VALUES_MAX


async def test_get_data_passes_filters_and_trims_to_recent(httpx_mock):
    httpx_mock.add_response(url=_TABLES_URL, json=_TABLES)
    httpx_mock.add_response(
        json=[_row("2026-06-01", 7.1), _row("2026-08-01", 7.4), _row("2026-07-01", 7.3)]
    )
    result = await client.get_data(
        "UnemploymentRates_14100287", {"GeoName": "Alberta"}, start_date="2026-07-01", limit=5
    )
    assert [r["Value"] for r in result.rows] == [7.3, 7.4]
    assert result.total_rows == 2
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params == {"table": ["UnemploymentRates_14100287"], "GeoName": ["Alberta"]}

    httpx_mock.add_response(json=[_row("2026-06-01", 7.1), _row("2026-08-01", 7.4)])
    latest = await client.get_data("UnemploymentRates_14100287", {"Sex": "Both sexes"}, limit=1)
    assert latest.rows[0]["Value"] == 7.4
    assert latest.total_rows == 2


async def test_get_data_validates_inputs(httpx_mock):
    httpx_mock.add_response(url=_TABLES_URL, json=_TABLES)
    with pytest.raises(NotFound):
        await client.get_data("Nope_1")
    with pytest.raises(InvalidInput):
        await client.get_data("CPI_18100004", {"Geo Name; drop": "x"})
    with pytest.raises(InvalidInput):
        await client.get_data("CPI_18100004", limit=0)
    with pytest.raises(InvalidInput):
        await client.get_data("CPI_18100004", start_date="2026-09-01", end_date="2026-01-01")


async def test_unknown_column_400_is_invalid_input(httpx_mock):
    httpx_mock.add_response(url=_TABLES_URL, json=_TABLES)
    httpx_mock.add_response(status_code=400, text="Invalid column name ")
    with pytest.raises(InvalidInput, match="Invalid column"):
        await client.get_data("CPI_18100004", {"Bogus": "x"})


async def test_list_indicators_flattens_topics(httpx_mock):
    httpx_mock.add_response(
        json={
            "data": [
                {
                    "name": "Agriculture",
                    "indicators": [
                        {"name": "Farm Cash Receipts", "updatedAt": "2026-08-31T14:11:30.1298585"}
                    ],
                },
                {"name": "Jobs", "indicators": [{"name": "Unemployment Rate", "updatedAt": None}]},
            ]
        }
    )
    result = await client.list_indicators()
    assert result.topics == ["Agriculture", "Jobs"]
    assert result.indicators[0].topic == "Agriculture"
    assert result.indicators[1].updated_at is None
