"""eurostat_query_dataset (eurostat/query.py) on the recorded namq_10_gdp answers.

The slice is the EU27, the euro area and Germany (fixtures/data_namq_10_gdp.json, as
test_client.py uses it). Checked live on 2026-11-20 against nama_10_gdp, une_rt_m and
demo_r_pjangroup: rankings answered, and a sum of the EU with its members, of a country
with its NUTS regions, of a total sex or age band with its parts, and of seasonally
adjusted with unadjusted values refused.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.eurostat import query
from maplestats_mcp.shared.errors import InvalidInput

FIXTURES = Path(__file__).parent / "fixtures"
STRUCTURE = re.compile(
    r"https://ec\.europa\.eu/eurostat/api/dissemination/sdmx/2\.1/dataflow/ESTAT/NAMQ_10_GDP/latest\?.*"
)
DATA = re.compile(
    r"https://ec\.europa\.eu/eurostat/api/dissemination/statistics/1\.0/data/namq_10_gdp\?.*"
)
FILTERS = {"unit": ["CLV_PCH_PRE"], "s_adj": ["SCA"], "na_item": ["B1GQ"]}
GEO = ["EU27_2020", "EA21", "DE"]


def _mock(httpx_mock, data: bool = True) -> None:
    httpx_mock.add_response(
        url=STRUCTURE,
        content=(FIXTURES / "structure_namq_10_gdp.xml").read_bytes(),
        headers={"content-type": "application/vnd.sdmx.structure+xml;version=2.1"},
        is_reusable=True,
    )
    if data:
        httpx_mock.add_response(url=DATA, content=(FIXTURES / "data_namq_10_gdp.json").read_bytes())


async def test_a_query_over_the_slice(httpx_mock):
    _mock(httpx_mock)
    result = await query.query_dataset(
        "namq_10_gdp",
        "SELECT geo, geo_label, count(*) AS quarters FROM obs GROUP BY ALL ORDER BY geo",
        filters=FILTERS,
        geo=GEO,
        start_period="2026-Q1",
    )
    assert result.rows == [
        ["DE", "Germany", 3],
        ["EA21", result.rows[1][1], 3],
        ["EU27_2020", result.rows[2][1], 3],
    ]
    assert result.input_rows == 9
    assert result.dimension_columns == {
        "freq": "freq",
        "unit": "unit_code",
        "s_adj": "s_adj",
        "na_item": "na_item",
        "geo": "geo",
    }
    assert result.filters["geo"] == GEO
    assert result.citation.startswith("Eurostat, ") and "(namq_10_gdp)" in result.citation
    request = next(r for r in httpx_mock.get_requests() if "/statistics/" in str(r.url))
    assert request.url.params["sinceTimePeriod"] == "2026-Q1"
    assert "lastTimePeriod" not in request.url.params


async def test_the_eu_summed_with_its_members_is_refused(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(InvalidInput, match="total_with_parts"):
        await query.query_dataset(
            "namq_10_gdp",
            "SELECT period, sum(value) FROM obs GROUP BY period",
            filters=FILTERS,
            geo=GEO,
        )


async def test_an_average_over_the_eu_and_members_warns(httpx_mock):
    _mock(httpx_mock)
    result = await query.query_dataset(
        "namq_10_gdp",
        "SELECT period, avg(value) FROM obs GROUP BY period ORDER BY period",
        filters=FILTERS,
        geo=GEO,
    )
    assert result.row_count == 3
    kinds = {w.split(":")[0] for w in result.warnings}
    assert {"average_with_parts", "average_of_rates"} <= kinds
    # Seasonally and calendar adjusted (SCA) reads as seasonally adjusted.
    httpx_mock.add_response(url=DATA, content=(FIXTURES / "data_namq_10_gdp.json").read_bytes())
    check = await query.query_dataset(
        "namq_10_gdp", "SELECT DISTINCT adjustment FROM obs", filters=FILTERS, geo=GEO
    )
    assert check.rows == [["seasonally adjusted"]]


async def test_an_unknown_code_is_refused_before_the_download(httpx_mock):
    _mock(httpx_mock, data=False)
    with pytest.raises(InvalidInput, match="geo = 'XX' matches no row"):
        await query.query_dataset(
            "namq_10_gdp", "SELECT * FROM obs WHERE geo = 'XX'", filters=FILTERS, geo=GEO
        )
    assert not [r for r in httpx_mock.get_requests() if "/statistics/" in str(r.url)]


async def test_a_slice_past_the_series_limit_is_refused(httpx_mock, monkeypatch):
    _mock(httpx_mock, data=False)
    monkeypatch.setattr(query, "MAX_QUERY_SERIES", 2)
    with pytest.raises(InvalidInput, match="limit 2"):
        await query.query_dataset("namq_10_gdp", "SELECT 1 FROM obs", filters=FILTERS, geo=GEO)
