"""Tests for bea/client.py.

fixtures/error_invalid_userid_live.json was recorded live on 2026-11-07 (a
request without a UserID). The guide_* fixtures are the BEA API user guide's
own examples (April 2026): the Regional CAINC1 Delaware answer, the
filtered LineCode list, the dataset list and the throttling error, verbatim;
the NIPA and ITA files follow the guide's field lists with illustrative
values, since no UserID was available to record real ones.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.bea import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable
from maplestats_mcp.shared.http import recording

FIXTURES = Path(__file__).parent / "fixtures"
API = re.compile(r"https://apps\.bea\.gov/api/data/.*")
KEY = "00000000-test-bea-key-000000000000"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("MAPLE_BEA_API_KEY", KEY)


def _params(httpx_mock) -> dict[str, str]:
    return dict(httpx_mock.get_requests()[-1].url.params)


async def test_without_key_says_a_key_is_needed(monkeypatch, httpx_mock):
    monkeypatch.delenv("MAPLE_BEA_API_KEY", raising=False)
    with pytest.raises(UpstreamUnavailable, match="MAPLE_BEA_API_KEY") as caught:
        await client.get_nipa()
    assert "Fix:" in str(caught.value)
    with pytest.raises(UpstreamUnavailable, match="MAPLE_BEA_API_KEY"):
        await client.list_datasets(lang="fr")
    assert not httpx_mock.get_requests()


async def test_rejected_key(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("error_invalid_userid_live.json"))
    with pytest.raises(UpstreamUnavailable, match="Invalid API UserId"):
        await client.get_nipa("T10101", years=[2026])


async def test_throttled(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_error_throttled.json"))
    with pytest.raises(UpstreamUnavailable, match="quota"):
        await client.list_datasets()


async def test_regional_rows_notes_and_key_never_exposed(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_regional_cainc1_de.json"))
    with recording() as requests:
        result = await client.get_regional("CAINC1", "3", "DE", years=[2014])

    params = _params(httpx_mock)
    assert params["UserID"] == KEY
    assert params["method"] == "GetData" and params["DataSetName"] == "Regional"
    assert (params["TableName"], params["LineCode"], params["GeoFips"], params["Year"]) == (
        "CAINC1",
        "3",
        "DE",
        "2014",
    )
    assert KEY not in requests[0].url and "YOUR_BEA_API_KEY" in requests[0].url
    dumped = result.model_dump_json()
    assert KEY not in dumped
    assert "UserID" not in result.query
    assert "YOUR_BEA_API_KEY" in result.provenance.url

    delaware = result.rows[0]
    assert (delaware.geo_fips, delaware.geo_name, delaware.value) == ("10000", "Delaware", 45359)
    assert delaware.unit == "Dollars" and delaware.unit_multiplier == 0
    assert delaware.series == "CAINC1-3"
    assert delaware.notes[0].startswith("Per capita personal income is")
    assert result.title and result.title.startswith("CAINC1")
    assert result.production_time and result.production_time.year == 2026
    assert result.provenance.as_of == result.production_time
    assert "not endorsed or certified by BEA" in (result.provenance.licence or "")


async def test_nipa_periods_values_and_defaults(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_nipa_t10101_shape.json"))
    result = await client.get_nipa("t10101", frequency="q", lang="fr")

    params = _params(httpx_mock)
    assert params["TableName"] == "T10101" and params["Frequency"] == "Q"
    assert len(params["Year"].split(",")) == 5
    gdp = result.rows[1]
    assert (gdp.date, gdp.value, gdp.series, gdp.line_number) == ("2026-Q2", 2.5, "A191RL", "1")
    assert gdp.metric == "Fisher Quantity Index"
    pce = result.rows[2]
    assert pce.value is None and pce.value_text == "(NA)"
    assert len(pce.notes) == 2
    assert result.title and result.title.startswith("Variation en pourcentage")
    assert any("annualis" in n for n in result.notes)


async def test_ita_canada_defaults(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_ita_canada_shape.json"))
    result = await client.get_international_transactions()

    params = _params(httpx_mock)
    assert params["AreaOrCountry"] == "Canada" and params["Frequency"] == "QSA"
    assert params["Indicator"].split(",")[:3] == ["ExpGdsServ", "ImpGdsServ", "BalGdsServ"]
    exports, balance = result.rows
    assert exports.value == 90123 and exports.unit_multiplier == 6
    assert balance.value == -15432 and balance.indicator == "BalGds"
    assert any("QSA" in n for n in result.notes)


async def test_parameter_values_filtered(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_linecode_sainc1.json"))
    result = await client.list_parameter_values("Regional", "LineCode", {"TableName": "SAINC1"})
    params = _params(httpx_mock)
    assert params["method"] == "GetParameterValuesFiltered"
    assert params["TargetParameter"] == "LineCode" and params["TableName"] == "SAINC1"
    assert [v.key for v in result.values] == ["1", "2", "3"]
    assert result.values[2].description.endswith("Per capita personal income")


async def test_datasets(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json=_fixture("guide_datasets.json"))
    result = await client.list_datasets()
    assert [d.name for d in result.datasets] == ["NIPA", "ITA", "Regional"]
    assert _params(httpx_mock)["method"] == "GetDatasetList"


async def test_no_rows_and_bad_parameter(with_key, httpx_mock):
    httpx_mock.add_response(url=API, json={"BEAAPI": {"Results": {"Data": [], "Notes": []}}})
    with pytest.raises(NotFound):
        await client.get_regional("SAINC1", "1", "53000", years=[2020])
    httpx_mock.add_response(
        url=API,
        json={
            "BEAAPI": {
                "Results": {
                    "Error": {
                        "APIErrorCode": "40",
                        "APIErrorDescription": "The dataset requested requires parameter TableName.",
                    }
                }
            }
        },
    )
    with pytest.raises(InvalidInput, match="bea_list_parameter_values"):
        await client.get_nipa("T99999", years=[2020])


async def test_input_checks(with_key):
    with pytest.raises(InvalidInput):
        await client.get_nipa(frequency="W")
    with pytest.raises(InvalidInput):
        await client.get_international_transactions(frequency="Q")
    with pytest.raises(InvalidInput):
        await client.get_international_transactions(area_or_country="AllCountries")
    with pytest.raises(InvalidInput):
        await client.get_regional(table="SAINC1;DROP")
    with pytest.raises(InvalidInput):
        await client.get_nipa(years=[1800])
