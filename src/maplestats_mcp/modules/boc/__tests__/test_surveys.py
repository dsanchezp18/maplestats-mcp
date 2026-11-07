"""Tests for boc/surveys.py: period parsing, and group resolution against
mocked Valet payloads shaped like the live ones of 2026-11-07 (see the
module docstring): per-series `recent=1` answers where a dropped question
carries an old date, release groups named for their quarter (CSCE_ and the
older CES_ prefix), a Report with no projection tables (2025M04), shares of
world GDP dated the Report's quarter, and staff vintages whose observations
are dated each quarter's last day."""

from __future__ import annotations

import re
from datetime import date

import pytest

from maplestats_mcp.modules.boc import constants, surveys
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = constants.BASE_URL


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    cache_module._caches.clear()
    yield


def _groups(*names: str) -> dict:
    return {"groups": {n: {"label": f"label {n}", "description": "", "link": ""} for n in names}}


def _group_detail(name: str, label: str, members: list[str], link: str = "https://x/?p=1"):
    return {
        "groupDetail": {
            "name": name,
            "label": label,
            "description": label,
            "link": link,
            "groupSeries": {m: {"label": m, "link": ""} for m in members},
        }
    }


def _obs(series: dict[str, tuple[str, str]], rows: list[dict]) -> dict:
    return {
        "seriesDetail": {
            code: {"label": label, "description": description}
            for code, (label, description) in series.items()
        },
        "observations": rows,
        "groupDetail": {"label": "g", "description": "", "link": ""},
    }


@pytest.mark.parametrize(
    ("text", "quarter"),
    [
        ("2026Q3", "2026Q3"),
        ("2026-q3", "2026Q3"),
        ("Q3 2026", "2026Q3"),
        ("2026T3", "2026Q3"),
        ("2026-08", "2026Q3"),
        ("2026-12-31", "2026Q4"),
    ],
)
def test_parse_quarter(text, quarter):
    assert surveys.parse_quarter(text) == quarter


@pytest.mark.parametrize(
    ("text", "report"),
    [
        ("2026M10", "2026M10"),
        ("2026-10", "2026M10"),
        ("2026-7", "2026M07"),
        ("October 2026", "2026M10"),
        ("octobre 2026", "2026M10"),
        ("2026-10-29", "2026M10"),
    ],
)
def test_parse_report(text, report):
    assert surveys.parse_report(text) == report


def test_bad_period_text_is_invalid_input_in_french():
    with pytest.raises(InvalidInput, match="trimestre"):
        surveys.parse_quarter("autumn", "fr")
    with pytest.raises(InvalidInput):
        surveys.parse_report("2026M13")


def test_quarter_end_handles_the_fourth_quarter():
    assert surveys._quarter_end("2026Q4") == date(2026, 12, 31)
    assert surveys._quarter_end("2026Q1") == date(2026, 3, 31)
    assert surveys._shift_quarters("2019Q4", -5) == "2018Q3"


def _mock_bos(httpx_mock, *, release=True):
    httpx_mock.add_response(
        url=f"{BASE}lists/groups/json",
        json=_groups("bos", "BOS_2026Q2", "BOS_2026Q3", "BOS_2026Q3_C1", "BOS_2026Q3_C9")
        if release
        else _groups("bos"),
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}observations/group/bos/json.*"),
        is_reusable=True,
        json=_obs(
            {
                "FUTURESALES": ("Balance of Opinion", "Future sales growth - Over the next ..."),
                "ABOVE3": ("Above 3 per cent (% of firms)", "Inflation Expectations - Over ..."),
                "PASTSALES": ("Balance of Opinion", "Past sales growth - Over the past ..."),
            },
            [
                {"d": "2023-01-01", "PASTSALES": {"v": "5"}},
                {"d": "2026-07-01", "FUTURESALES": {"v": "9"}, "ABOVE3": {"v": "41"}},
            ],
        ),
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}observations/PC1,.*"),
        is_reusable=True,
        json=_obs(
            {"PC1": ("BOS Indicator", "The BOS indicator is re-estimated ...")},
            [{"d": "2026-07-01", "PC1": {"v": "-0.33"}}],
        ),
    )
    if release:
        httpx_mock.add_response(
            url=f"{BASE}groups/BOS_2026Q3/json",
            json=_group_detail("BOS_2026Q3", "October 2026 Business Outlook Survey", []),
        )


async def test_business_outlook_keeps_the_newest_quarter_only(httpx_mock):
    _mock_bos(httpx_mock)
    result = await surveys.get_survey("bos")
    assert result.quarter == "2026Q3"
    codes = {r.series: r for r in result.rows}
    # PASTSALES was dropped in 2023: its recent=1 answer is not this quarter's.
    assert set(codes) == {"FUTURESALES", "ABOVE3", "PC1"}
    assert codes["FUTURESALES"].label == "Future sales growth: Balance of Opinion"
    assert (codes["FUTURESALES"].unit or "").startswith("balance of opinion")
    assert codes["ABOVE3"].unit == "percent of firms"
    assert codes["PC1"].value == -0.33
    assert result.release is not None
    assert result.release.released == "2026-10"
    assert result.release.link == "https://x/?p=1"
    assert [g.name for g in result.release.chart_groups] == ["BOS_2026Q3_C1", "BOS_2026Q3_C9"]
    assert result.recent_quarters == ["2026Q3", "2026Q2"]


async def test_business_outlook_without_a_release_group(httpx_mock):
    _mock_bos(httpx_mock, release=False)
    result = await surveys.get_survey("bos")
    assert result.release is None
    assert result.rows


async def test_named_quarter_is_fetched_by_date_range(httpx_mock):
    _mock_bos(httpx_mock)
    await surveys.get_survey("bos", "2026Q3")
    # The client's newer-data check adds a recent=1 request for a past range.
    urls = [
        str(r.url)
        for r in httpx_mock.get_requests()
        if "observations" in str(r.url) and "recent=1" not in str(r.url)
    ]
    assert urls and all("start_date=2026-07-01" in u and "end_date=2026-09-30" in u for u in urls)


async def test_quarter_with_no_rows_is_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}lists/groups/json", json=_groups("CES_2020Q2"))
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}observations/CES_C1_SHORT_TERM.*"),
        json=_obs({}, []),
        is_reusable=True,
    )
    with pytest.raises(NotFound, match="2019Q1.*2020Q2"):
        await surveys.get_survey("csce", "2019Q1")


async def test_csce_prefers_the_csce_release_name(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}lists/groups/json", json=_groups("CES_2026Q3", "CSCE_2026Q3")
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}observations/CES_C1_SHORT_TERM.*"),
        json=_obs(
            {
                "CES_C1_SHORT_TERM": ("1-year-ahead inflation expectations", "What do ..."),
                "CES_C4_LOSE_JOB": ("Probability of losing job", "..."),
            },
            [
                {
                    "d": "2026-07-01",
                    "CES_C1_SHORT_TERM": {"v": "4.03"},
                    "CES_C4_LOSE_JOB": {"v": "15"},
                }
            ],
        ),
    )
    httpx_mock.add_response(
        url=f"{BASE}groups/CSCE_2026Q3/json",
        json=_group_detail(
            "CSCE_2026Q3", "October 2026 Canadian Survey of Consumer Expectations", []
        ),
    )
    result = await surveys.get_survey("csce")
    assert result.release is not None and result.release.group == "CSCE_2026Q3"
    units = {r.series: r.unit for r in result.rows}
    assert units == {"CES_C1_SHORT_TERM": "percent", "CES_C4_LOSE_JOB": "percent chance"}


async def test_mpr_projection_resolves_the_newest_report(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}lists/groups/json",
        json=_groups(
            "MPR_2026M07_SQP_CAN",
            "MPR_2026M10",
            "MPR_2026M10_SQP_CAN",
            "MPR_2026M10_GEG",
            "MPR_2026M10_CPI",
        ),
    )
    httpx_mock.add_response(
        url=f"{BASE}observations/group/MPR_2026M10_SQP_CAN/json",
        json=_obs(
            {"MPR_2026M10_SQP_CAN_CPI_YOY": ("CPI inflation (y/y)", "")},
            [
                {"d": "2026-10-01", "MPR_2026M10_SQP_CAN_CPI_YOY": {"v": "3.4"}},
                {"d": "2027-10-01", "MPR_2026M10_SQP_CAN_CPI_YOY": {"v": "2.6"}},
            ],
        ),
    )
    httpx_mock.add_response(
        url=f"{BASE}observations/group/MPR_2026M10_GEG/json",
        json=_obs(
            {
                "MPR_2026M10_GEG_US_GDP_SHR": ("Share of real global GDP (%) - US", ""),
                "MPR_2026M10_GEG_US_GDP_YOY": ("Projected growth (%) - US", ""),
            },
            [
                {"d": "2026-01-01", "MPR_2026M10_GEG_US_GDP_YOY": {"v": "2.4"}},
                {"d": "2026-10-01", "MPR_2026M10_GEG_US_GDP_SHR": {"v": "15"}},
            ],
        ),
    )
    httpx_mock.add_response(
        url=f"{BASE}groups/MPR_2026M10/json",
        json=_group_detail("MPR_2026M10", "October 2026 Monetary Policy Report", []),
    )
    result = await surveys.get_mpr_projection()
    assert result.report == "2026M10"
    assert result.recent_reports == ["2026M10", "2026M07"]
    rows = {(r.series, r.period): r for r in result.rows}
    assert rows[("MPR_2026M10_SQP_CAN_CPI_YOY", "2027Q4")].value == 2.6
    assert rows[("MPR_2026M10_GEG_US_GDP_YOY", "2026")].table == "global"
    share = rows[("MPR_2026M10_GEG_US_GDP_SHR", None)]
    assert share.unit == "percent of world GDP"
    assert result.release.released == "2026-10"
    assert [g.name for g in result.release.chart_groups] == [
        "MPR_2026M10_CPI",
        "MPR_2026M10_GEG",
        "MPR_2026M10_SQP_CAN",
    ]
    assert "gdp_contributions" in (result.provenance.limits or "")


async def test_mpr_report_without_tables_lists_the_others(httpx_mock):
    httpx_mock.add_response(url=f"{BASE}lists/groups/json", json=_groups("MPR_2026M10_SQP_CAN"))
    with pytest.raises(NotFound, match="2025M04.*2026M10"):
        await surveys.get_mpr_projection("April 2025")


async def test_staff_projections_mark_forecast_quarters(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}groups/SWP-GDP/json",
        json=_group_detail(
            "SWP-GDP", "Real Gross Domestic Product", ["SWP-GDP2019Q3", "SWP-GDP2019Q4"]
        ),
    )
    httpx_mock.add_response(
        url=f"{BASE}groups/SWP-R20N/json",
        json=_group_detail("SWP-R20N", "5-year bond rate", ["SWP-R20N2011Q1", "SWP-R20N2019Q3"]),
    )
    httpx_mock.add_response(
        url=f"{BASE}observations/SWP-GDP2019Q4/json?start_date=2019-07-01",
        json=_obs(
            {"SWP-GDP2019Q4": ("GDP - Staff Projection 2019Q4", "")},
            [
                {"d": "2019-09-30", "SWP-GDP2019Q4": {"v": "2099199.9"}},
                {"d": "2019-12-31", "SWP-GDP2019Q4": {"v": "2105965.5"}},
            ],
        ),
    )
    result = await surveys.get_staff_projections(["gdp", "R20N"], history_quarters=1)
    assert result.vintage == "2019Q4"
    assert [(r.period, r.projected) for r in result.rows] == [("2019Q3", False), ("2019Q4", True)]
    assert [v.code for v in result.variables] == ["GDP"]
    assert result.variables[0].first_vintage == "2019Q3"
    assert "R20N" in (result.provenance.limits or "")


async def test_staff_projection_inputs_are_checked():
    with pytest.raises(InvalidInput, match="NOPE"):
        await surveys.get_staff_projections(["NOPE"])
    with pytest.raises(InvalidInput, match="history_quarters"):
        await surveys.get_staff_projections(history_quarters=-1)


async def test_staff_vintage_missing_everywhere_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}groups/SWP-GDP/json",
        json=_group_detail("SWP-GDP", "Real GDP", ["SWP-GDP2019Q4"]),
    )
    with pytest.raises(NotFound, match="GDP 2019Q4-2019Q4"):
        await surveys.get_staff_projections(["GDP"], vintage="2024Q1")
