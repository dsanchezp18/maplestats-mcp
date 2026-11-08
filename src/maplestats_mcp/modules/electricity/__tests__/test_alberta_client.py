"""Tests for electricity/alberta_client.py against excerpts of the AESO ETS
reports recorded live on 2026-11-08 (see the client docstring).
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from maplestats_mcp.modules.electricity import alberta_client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

POOL_URL = re.compile(re.escape(constants.AESO_REPORTS_URL) + r"/HistoricalPoolPriceReportServlet")
DAILY_URL = re.compile(
    re.escape(constants.AESO_REPORTS_URL) + r"/DailyAveragePoolPriceReportServlet"
)
CSD_URL = re.compile(re.escape(constants.AESO_REPORTS_URL) + r"/CSDReportServlet")

# HistoricalPoolPriceReportServlet, 2025-11-02 (autumn day with the '02*' hour)
# and the last hours of a day still being settled.
POOL_CSV = """Pool Price\r
\r
""\r
\r
Date (HE),Price ($),30Ravg ($),AIL Demand (MW)\r
"11/02/2025 01","0.00","32.84","9707.0"\r
"11/02/2025 02","0.00","32.82","9688.0"\r
"11/02/2025 02*","0.00","32.81","9668.0"\r
"11/02/2025 03","4.03","32.80","9650.0"\r
"11/03/2025 01","28.34","42.40","10747.0"\r
"11/03/2025 02","20.30","42.42","10642.0"\r
"11/03/2025 03","-","-","-"\r
"""

DAILY_CSV = """Daily Average Pool Price Report\r
\r
""\r
\r
Date,Daily Average,Daily On Peak Average,Daily Off Peak Average,30Ravg Average,30Ravg On Peak Average,30Ravg Off Peak Average\r
"10/05/2026","18.45","21.27","12.82","29.92","33.01","23.74"\r
"10/04/2026","25.08","21.92","31.40","30.17","33.26","24.00"\r
"""

MONTHLY_2026 = """<html><body><table>
<tr><td><p>Pool Monthly Summary for October 2026</p></td></tr>
<tr><td><p>The average pool price for the month of October was $51.33/MWh. The on peak pool
price averaged $63.20/MWh and ranged from $0.00/MWh to $976.86/MWh. The off peak pool price
averaged $27.59/MWh and ranged from $0.00/MWh to $193.36/MWh.</p></td></tr>
<tr><td>Monthly Statistics</td></tr>
<tr><td>Pool Price ($/MWh)</td><td>Demand (AIL, MW)</td><td>Total Energy (GWh)</td></tr>
<tr><td>Minimum</td><td>Average</td><td>Maximum</td><td>Weighted Average*</td><td>Minimum</td>
<td>Average</td><td>Maximum</td><td>&nbsp;</td><td>Load Factor</td></tr>
<tr><td>$0.00</td><td>$51.33</td><td>$976.86</td><td>$52.16</td><td>9,270</td><td>10,470</td>
<td>11,627</td><td>7,790</td><td>90.1%</td></tr>
</table></body></html>"""

# Legacy layouts: 2003 without and 2008 with the weighted-average column.
MONTHLY_2003 = """<html><body><table>
<tr><td>Day</td><td>Minimum</td><td>Maximum</td><td>Average</td><td>Minimum</td><td>Maximum</td>
<td>Average *</td><td>(MWh) **</td></tr>
<tr><td>1</td><td>9.07</td><td>119.00</td><td>48.45</td><td>6,377</td><td>7,644</td><td>6,989</td>
<td>167,742</td></tr>
<tr><td>Monthly Value</td><td>8.04</td><td>999.99</td><td>80.52</td><td>6,287</td><td>8,433</td>
<td>7,385</td><td>5,494,269</td></tr>
</table></body></html>"""

MONTHLY_2008 = """<html><body><table>
<tr><td>Day</td><td>Minimum</td><td>Maximum</td><td>Average</td><td>Weighted Average #</td>
<td>Minimum</td><td>Maximum</td><td>Average *</td><td>(MWh) **</td></tr>
<tr><td>Monthly Value</td><td>13.99</td><td>999.99</td><td>96.66</td><td>98.99</td><td>6,900</td>
<td>9,254</td><td>7,992</td><td>5,762,569</td></tr>
</table></body></html>"""

# CSDReportServlet: the page's own nesting (tables inside rows and cells).
CSD_HTML = """<HTML><BODY>
<TABLE>
<TR>
    <TABLE WIDTH=100%>
        <tr>
            <td colspan="2"><table><tr><td><b>Legend</b></td></tr></table></td>
            <td><table><tr><td> <TR><TD>Last Update : Nov 07, 2026 23:19</TD></TR>
 </td></tr></table></td>
        </tr>
        <tr><td>MC - Maximum Capability</td></tr>
    </TABLE>
</TR>
<tr>
    <TABLE WIDTH=100%>
        <TD VALIGN="TOP" WIDTH="30%">
            <TABLE BORDER="1" WIDTH="100%">
            <TR><TH COLSPAN="3"><CENTER><B>SUMMARY</B></CENTER></TH></TR>
            <TR><TD>Alberta Total Net Generation</TD><TD>10951</TD></TR>
<TR><TD>Net Actual Interchange</TD><TD>450</TD></TR>
<TR><TD>Alberta Internal Load (AIL)</TD><TD>10501</TD></TR>
<TR><TD>Net-To-Grid Generation</TD><TD>8121</TD></TR>
<TR><TD>Dispatched Contingency Reserve -Gen</TD><TD>445</TD></TR>
            </TABLE>
        </TD>
        <TD VALIGN="TOP" WIDTH="30%">
            <TABLE BORDER="1" WIDTH="100%">
            <TR><TH COLSPAN="4"><CENTER><B>GENERATION</B></CENTER></TH></TR>
            <TR><TD>GROUP</TD><TD>MC</TD><TD>TNG</TD><TD>DCR</TD></TR>
<TR><TD>COGENERATION</TD><TD>6125</TD><TD>4744</TD><TD>15</TD></TR>
<TR><TD>WIND</TD><TD>5684</TD><TD>3325</TD><TD>0</TD></TR>
<TR><TD>TOTAL</TD><TD>11809</TD><TD>8069</TD><TD>15</TD></TR>
            </TABLE>
        </TD>
        <TD VALIGN="TOP" WIDTH="30%">
            <TABLE BORDER="1" WIDTH="100%">
                <TR><TH COLSPAN=2><CENTER><B>INTERCHANGE</B></CENTER></TH></TR>
                <TR><TD><P ALIGN=RIGHT><FONT>PATH</FONT></TD><TD><P><FONT>ACTUAL FLOW</FONT></TD></TR>
                <TR><TD>British Columbia</TD><TD>376</TD></TR>
<TR><TD>Montana</TD><TD>74</TD></TR>
<TR><TD>Saskatchewan</TD><TD>0</TD></TR>
<TR><TD>TOTAL</TD><TD>450</TD></TR>
            </TABLE>
        </TD>
    </table>
</tr>
<tr>
    <TABLE WIDTH=100%>
        <TD VALIGN="TOP">
            <TABLE BORDER="1" WIDTH="100%">
            <TR><TH COLSPAN="4"><CENTER><B>GAS</B></CENTER></TH></TR>
            <TR BGCOLOR=#CEE3F6><TD COLSPAN=4><FONT><center><b>Cogeneration</b></center></FONT></TD></TR>
            <TR><TD>ASSET</TD><TD>MC</TD><TD>TNG</TD><TD>DCR</TD></TR>
<TR><TD>Base Plant (SCR1)</TD><TD>856</TD><TD>800</TD><TD>0</TD></TR>
            </TABLE>
        </TD>
        <TD VALIGN="TOP">
            <table WIDTH="100%"><tr><td VALIGN="TOP" WIDTH="100%">
                <TABLE BORDER="1" WIDTH="100%">
                    <TR><TH COLSPAN="4"><CENTER><B>WIND</B></CENTER></TH></TR>
                    <TR><TD>ASSET</TD><TD>MC</TD><TD>TNG</TD><TD>DCR</TD></TR>
<TR><TD>Ardenville Wind (ARD1)*</TD><TD>68</TD><TD>16</TD><TD>0</TD></TR>
<TR><TD>Kisikaw-pisim 1 (KKP1)*^</TD><TD>7</TD><TD>0</TD><TD>0</TD></TR>
                </TABLE>
            </td></tr></table>
        </TD>
    </table>
</tr>
</TABLE></BODY></HTML>"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_pool_price_csv_keeps_the_repeated_hour_and_unsettled_rows():
    hours = alberta_client.parse_pool_price_csv(POOL_CSV)
    assert len(hours) == 7
    repeated = [h for h in hours if h.repeated_hour]
    assert len(repeated) == 1 and repeated[0].hour_ending == 2
    assert hours[-1].pool_price is None and hours[-1].ail_demand_mw is None
    assert hours[3].pool_price == 4.03 and hours[3].ail_demand_mw == 9650.0


async def test_pool_price_asks_for_the_day_after_end_and_counts_unsettled_hours(httpx_mock):
    httpx_mock.add_response(url=POOL_URL, text=POOL_CSV)
    result = await alberta_client.get_pool_price("2025-11-02", "2025-11-03", limit=10)
    request = httpx_mock.get_requests()[0]
    # The servlet's endDate is exclusive.
    assert request.url.params["beginDate"] == "11022025"
    assert request.url.params["endDate"] == "11042025"
    assert result.rows_matched == 6
    assert result.hours_not_yet_published == 1
    assert (result.latest_published_date, result.latest_published_hour_ending) == (
        date(2025, 11, 3),
        2,
    )
    assert result.provenance.commercial_use == "not_allowed"
    assert "non-commercial" in (result.provenance.licence or "")
    assert "written permission" in result.commercial_use_notice


async def test_pool_price_without_dates_returns_the_latest_hours(httpx_mock, monkeypatch):
    monkeypatch.setattr(alberta_client, "alberta_today", lambda: date(2025, 11, 3))
    httpx_mock.add_response(url=POOL_URL, text=POOL_CSV)
    result = await alberta_client.get_pool_price(limit=2)
    assert [(r.date.day, r.hour_ending) for r in result.rows] == [(3, 1), (3, 2)]


async def test_pool_price_rejects_long_ranges_and_dates_before_1999():
    with pytest.raises(InvalidInput):
        await alberta_client.get_pool_price("2023-01-01", "2024-12-31")
    with pytest.raises(InvalidInput):
        await alberta_client.get_pool_price("1998-12-31", "1999-01-02")


async def test_validation_error_page_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=POOL_URL,
        text="<html><h2>Validation Error</h2>This report is available for a maximum of 721 days "
        'of data for report type "text/csv".</html>',
    )
    with pytest.raises(InvalidInput, match="721 days"):
        await alberta_client.get_pool_price("2025-01-01", "2025-01-02")


async def test_daily_prices_split_into_31_day_requests_and_sort_oldest_first(httpx_mock):
    httpx_mock.add_response(url=DAILY_URL, text=DAILY_CSV, is_reusable=True)
    result = await alberta_client.get_daily_prices("2026-08-01", "2026-10-05")
    assert result.requests_made == 3
    assert len(httpx_mock.get_requests()) == 3
    assert [d.date for d in result.days] == [date(2026, 10, 4), date(2026, 10, 5)]
    assert result.days[-1].average == 18.45 and result.days[-1].on_peak_average == 21.27


async def test_daily_prices_reject_more_than_a_year():
    with pytest.raises(InvalidInput):
        await alberta_client.get_daily_prices("2025-01-01", "2026-03-01")


def test_monthly_statistics_layout():
    month = alberta_client.parse_monthly_html(MONTHLY_2026, date(2026, 10, 1))
    assert month is not None and month.layout == "monthly_statistics"
    assert (month.pool_price_average, month.pool_price_weighted_average) == (51.33, 52.16)
    assert (month.on_peak_average, month.off_peak_average) == (63.2, 27.59)
    assert (month.ail_maximum_mw, month.total_energy_gwh, month.load_factor_percent) == (
        11627.0,
        7790.0,
        90.1,
    )


def test_monthly_legacy_layouts_with_and_without_weighted_average():
    early = alberta_client.parse_monthly_html(MONTHLY_2003, date(2003, 1, 1))
    assert early is not None and early.layout == "legacy_daily_table"
    assert (early.pool_price_minimum, early.pool_price_maximum, early.pool_price_average) == (
        8.04,
        999.99,
        80.52,
    )
    assert early.pool_price_weighted_average is None
    assert (early.ail_minimum_mw, early.ail_maximum_mw, early.ail_average_mw) == (
        6287.0,
        8433.0,
        7385.0,
    )
    assert early.total_energy_gwh == 5494.269
    later = alberta_client.parse_monthly_html(MONTHLY_2008, date(2008, 11, 1))
    assert later is not None
    assert (later.pool_price_average, later.pool_price_weighted_average) == (96.66, 98.99)
    assert (later.ail_average_mw, later.total_energy_gwh) == (7992.0, 5762.569)


async def test_monthly_summary_reports_unpublished_months(httpx_mock):
    httpx_mock.add_response(url=re.compile(r".*PMS_09012026\.html"), text=MONTHLY_2026)
    httpx_mock.add_response(url=re.compile(r".*PMS_10012026\.html"), status_code=404)
    result = await alberta_client.get_monthly_summary("2026-09", "2026-10")
    assert [m.month for m in result.months] == ["2026-09"]
    assert result.months_not_published == ["2026-10"]


async def test_monthly_summary_rejects_bad_months():
    with pytest.raises(InvalidInput):
        await alberta_client.get_monthly_summary("2026-13")
    with pytest.raises(InvalidInput):
        await alberta_client.get_monthly_summary("2020-01", "2022-06")


async def test_supply_demand_reads_the_nested_page(httpx_mock):
    httpx_mock.add_response(url=CSD_URL, text=CSD_HTML)
    result = await alberta_client.get_supply_demand(include_assets=True, lang="fr")
    assert result.last_update == "Nov 07, 2026 23:19"
    assert result.alberta_internal_load_mw == 10501.0
    assert result.total_net_generation_mw == 10951.0
    assert result.net_actual_interchange_mw == 450.0
    assert result.other_measures_mw == {"dispatched_contingency_reserve_gen_mw": 445.0}
    assert [f.fuel for f in result.generation_by_fuel] == ["COGENERATION", "WIND"]
    assert [p.path for p in result.interchange] == ["British Columbia", "Montana", "Saskatchewan"]
    groups = {a.asset: a for a in result.assets}
    assert groups["Base Plant (SCR1)"].group == "Gas: Cogeneration"
    kkp = groups["Kisikaw-pisim 1 (KKP1)"]
    assert kkp.group == "Wind" and kkp.net_to_grid and kkp.includes_storage
    assert "non commercial" in result.commercial_use_notice
    assert result.provenance.commercial_use == "not_allowed"


async def test_supply_demand_filters_assets_by_group(httpx_mock):
    httpx_mock.add_response(url=CSD_URL, text=CSD_HTML)
    result = await alberta_client.get_supply_demand(include_assets=True, group="wind")
    assert [a.asset for a in result.assets] == ["Ardenville Wind (ARD1)", "Kisikaw-pisim 1 (KKP1)"]
    without = await alberta_client.get_supply_demand()
    assert without.assets == []
