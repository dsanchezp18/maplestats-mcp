"""Tests for epcor/client.py, shaped around page structures and file
naming quirks confirmed live 2026-09-22 (see the module docstring).
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.epcor import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_DAILY_PAGE = """
<table><tr><td></td>
<td><span id="DateLabel1">SEP-15</span></td><td><span id="DateLabel2">SEP-16</span></td></tr>
<tr><td><span id="ZoneLabel">Rossdale</span></td></tr>
<tr><td><span id="HardnessLabel1">178</span></td><td><span id="HardnessLabel2">182</span></td></tr>
<tr><td><span id="phLabel1">7.9</span></td><td><span id="phLabel2">7.8</span></td></tr>
<tr><td><span id="TempLabel1">--</span></td><td><span id="TempLabel2">13.9</span></td></tr>
<tr><td><span id="ChlorineLabel1">2.20</span></td><td><span id="ChlorineLabel2">2.25</span></td></tr>
<tr><td><span id="SodaDoseLabel1">1.17</span></td><td><span id="SodaDoseLabel2">0.000</span></td></tr>
</table>
"""

_BASE = "/content/dam/epcor/documents/water-quality-reports/"
_REPORTS_PAGE = f"""
<a href="{_BASE}2024-09_edmonton_water-quality_monthly-summary.pdf">Sep</a>
<a href="{_BASE}2025-03_edmonton_water-quality_monthly-report..pdf">Mar</a>
<a href="{_BASE}2026-07-edmonton-water-quality-monthly-bacteriological-summary.pdf">Jul</a>
<a href="{_BASE}2026-07-edmonton-wastewater-quality-monthly-summary.pdf">Jul ww</a>
<a href="{_BASE}2025-edmonton-water-quality-annual-report.pdf">2025</a>
<a href="{_BASE}2025-edmonton-water-quality-annual-report.pdf">duplicate</a>
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_infer_label_date_rolls_back_across_new_year():
    assert client.infer_label_date("SEP-15", date(2026, 9, 22)) == date(2026, 9, 15)
    assert client.infer_label_date("DEC-30", date(2027, 1, 2)) == date(2026, 12, 30)
    assert client.infer_label_date("garbage", date(2026, 9, 22)) is None


def test_parse_daily_page_handles_missing_values():
    readings = client.parse_daily_page(_DAILY_PAGE, date(2026, 9, 22))
    assert [r.date_label for r in readings] == ["SEP-15", "SEP-16"]
    assert readings[0].total_hardness == 178
    assert readings[0].temperature is None
    assert readings[1].caustic_soda_dose == 0
    assert readings[0].alkalinity is None


def test_parse_daily_page_without_dates_raises():
    with pytest.raises(UpstreamError):
        client.parse_daily_page("<html>maintenance</html>", date(2026, 9, 22))


async def test_get_daily_water_quality(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=Rossdale", text=_DAILY_PAGE)
    result = await client.get_daily_water_quality("rossdale")
    assert result.plant_name == "Rossdale"
    assert result.units["ph"] == "pH"
    assert len(result.readings) == 2


async def test_unknown_plant_raises():
    with pytest.raises(InvalidInput):
        await client.get_daily_water_quality("gold_bar")  # type: ignore[arg-type]


def test_parse_report_links_normalizes_both_namings():
    reports = client.parse_report_links(_REPORTS_PAGE)
    by_name = {r.file_name: r for r in reports}
    assert len(reports) == 5
    old = by_name["2024-09_edmonton_water-quality_monthly-summary.pdf"]
    assert (old.year, old.month, old.system, old.kind) == (2024, 9, "water", "monthly-summary")
    typo = by_name["2025-03_edmonton_water-quality_monthly-report..pdf"]
    assert typo.kind == "monthly-report"
    new = by_name["2026-07-edmonton-wastewater-quality-monthly-summary.pdf"]
    assert (new.system, new.kind) == ("wastewater", "monthly-summary")
    annual = by_name["2025-edmonton-water-quality-annual-report.pdf"]
    assert (annual.year, annual.month) == (2025, None)
    assert annual.url.startswith("https://www.epcor.com/content/dam/")


async def test_list_reports_filters_and_sorts(httpx_mock):
    httpx_mock.add_response(url=constants.REPORTS_PAGE_URL, text=_REPORTS_PAGE)
    result = await client.list_water_quality_reports(system="water")
    assert result.total_matches == 4
    assert result.reports[0].year == 2026
    assert "monthly-bacteriological-summary" in result.kinds_available
    july = await client.list_water_quality_reports(year=2026, month=7)
    assert {r.system for r in july.reports} == {"water", "wastewater"}


async def test_list_reports_bad_month_raises():
    with pytest.raises(InvalidInput):
        await client.list_water_quality_reports(month=13)
