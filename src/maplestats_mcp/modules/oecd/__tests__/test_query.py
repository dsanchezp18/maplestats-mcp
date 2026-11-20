"""oecd_query_dataset (oecd/query.py) on the recorded Economic Outlook answers.

Checked live on 2026-11-20 against DSD_LFS@DF_IALFS_INDIC and DSD_PRICES@DF_PRICES_ALL:
a ranking of unemployment rates answered; a sum of the G7 with its members, of a total
sex with its parts, and of adjusted with unadjusted values refused; a FILTER clause
not refused.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.oecd import client, query
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

FIXTURES = Path(__file__).parent / "fixtures"
CATALOGUE = "https://sdmx.oecd.org/public/rest/dataflow/all"
STRUCTURE = re.compile(
    r"https://sdmx\.oecd\.org/public/rest/dataflow/OECD\.ECO\.MAD/DSD_EO@DF_EO/latest\?.*"
)
DATA = re.compile(r"https://sdmx\.oecd\.org/public/rest/data/OECD\.ECO\.MAD,DSD_EO@DF_EO,/.*")
HEADER = (
    "STRUCTURE,STRUCTURE_ID,ACTION,REF_AREA: Reference area,MEASURE: Measure,FREQ: Frequency "
    "of observation,TIME_PERIOD: Time period,OBS_VALUE: Observation value,OBS_STATUS: "
    "Observation status,UNIT_MEASURE: Unit of measure,UNIT_MULT: Unit multiplier\n"
)


@pytest.fixture(autouse=True)
def _reset_state():
    cache_module._caches.clear()
    client.BUDGET.reset()
    yield
    client.BUDGET.reset()


def _mock(httpx_mock, csv_text: str | None = None) -> None:
    httpx_mock.add_response(
        url=CATALOGUE,
        json=json.loads((FIXTURES / "dataflows.json").read_text(encoding="utf-8")),
        is_optional=True,
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=STRUCTURE,
        json=json.loads((FIXTURES / "structure_eo.json").read_text(encoding="utf-8")),
        is_optional=True,
        is_reusable=True,
    )
    if csv_text is not None:
        httpx_mock.add_response(url=DATA, text=csv_text)


async def test_a_query_over_the_recorded_slice(httpx_mock):
    _mock(httpx_mock, (FIXTURES / "data_eo_en.csv").read_text(encoding="utf-8"))
    result = await query.query_dataset(
        "DSD_EO@DF_EO",
        "SELECT ref_area, ref_area_label, max(value) AS peak FROM obs "
        "WHERE measure = 'GDPV_ANNPCT' GROUP BY ALL ORDER BY ref_area",
        filters={"REF_AREA": ["CAN", "USA", "GBR"], "MEASURE": ["GDPV_ANNPCT"], "FREQ": ["A"]},
        start_period="2024",
    )
    assert [r[0] for r in result.rows] == ["CAN", "GBR", "USA"]
    assert result.rows[0][1] == "Canada"
    request = next(r for r in httpx_mock.get_requests() if "/rest/data/" in str(r.url))
    assert "/CAN+USA+GBR.GDPV_ANNPCT.A" in str(request.url)
    assert result.citation.startswith("OECD (")
    assert result.filters == {"REF_AREA": ["CAN", "USA", "GBR"], "MEASURE": ["GDPV_ANNPCT"],
                              "FREQ": ["A"]}  # fmt: skip


async def test_the_oecd_summed_with_its_members_is_refused(httpx_mock):
    rows = "".join(
        f"DATAFLOW,OECD.ECO.MAD:DSD_EO@DF_EO(1.5),I,{area},UNR: Unemployment rate,A: Annual,"
        f"{year},{value},,PC: Percentage,0: Units\n"
        for area, value in (("OECD: OECD total", 4.9), ("CAN: Canada", 6.5), ("JPN: Japan", 2.5))
        for year in (2024, 2025)
    )
    _mock(httpx_mock, HEADER + rows)
    with pytest.raises(
        InvalidInput, match="total_with_parts.*'OECD; Unemployment rate; Annual' includes 'Canada"
    ):
        await query.query_dataset(
            "DSD_EO@DF_EO",
            "SELECT period, sum(value) FROM obs GROUP BY period",
            filters={"REF_AREA": ["OECD", "CAN", "JPN"], "MEASURE": ["UNR"]},
        )


async def test_a_unit_multiplier_and_confidential_values_reach_obs(httpx_mock):
    rows = (
        "DATAFLOW,OECD.ECO.MAD:DSD_EO@DF_EO(1.5),I,CAN: Canada,UNR: Unemployment rate,"
        "A: Annual,2024,1500,,PS: Persons,3: Thousands\n"
        "DATAFLOW,OECD.ECO.MAD:DSD_EO@DF_EO(1.5),I,CAN: Canada,UNR: Unemployment rate,"
        "A: Annual,2025,,U: Low reliability,PS: Persons,3: Thousands\n"
        "DATAFLOW,OECD.ECO.MAD:DSD_EO@DF_EO(1.5),I,CAN: Canada,UNR: Unemployment rate,"
        "A: Annual,2026,,,PS: Persons,3: Thousands\n"
    )
    _mock(httpx_mock, HEADER + rows)
    result = await query.query_dataset(
        "DSD_EO@DF_EO",
        "SELECT period, value, scale_multiplier, scale, unit, status, quality FROM obs "
        "ORDER BY period",
        filters={"REF_AREA": ["CAN"], "MEASURE": ["UNR"]},
    )
    # An empty value with no status (2026) is not an observation.
    assert result.rows == [
        ["2024", 1500.0, 1000, "Thousands", "Persons", None, None],
        ["2025", None, 1000, "Thousands", "Persons", "Low reliability", "E"],
    ]


async def test_an_unknown_dimension_or_code_is_refused_before_the_download(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(InvalidInput, match="no dimension 'SEX'"):
        await query.query_dataset("DSD_EO@DF_EO", "SELECT 1 FROM obs", filters={"SEX": ["F"]})
    with pytest.raises(InvalidInput, match="ref_area = 'ZZZ' matches no row"):
        await query.query_dataset("DSD_EO@DF_EO", "SELECT * FROM obs WHERE ref_area = 'ZZZ'")
    assert not [r for r in httpx_mock.get_requests() if "/rest/data/" in str(r.url)]
