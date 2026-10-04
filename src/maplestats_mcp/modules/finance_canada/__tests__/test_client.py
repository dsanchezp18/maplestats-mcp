"""Tests shaped on Finance Canada's feed, FRT workbooks and Fiscal Monitor pages (2026-10-03)."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.finance_canada import client, constants, monitor
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_FEED = {
    "data": [
        {
            "title": "Fiscal Reference Tables November 2025",
            "link": "https://www.canada.ca/en/department-finance/services/publications/"
            "fiscal-reference-tables/2025.html",
            "title-fr": "Tableaux de référence financiers Novembre 2025",
            "link-fr": "https://www.canada.ca/fr/ministere-finances/services/publications/"
            "tableaux-reference-financiers/2025.html",
            "pub-date": "2025-11-07",
            "pub-type": "Fiscal Reference Tables",
        },
        {
            "title": "Fiscal Reference Tables December 2021",
            "link": "https://www.canada.ca/en/department-finance/services/publications/"
            "fiscal-reference-tables/2021.html",
            "title-fr": "Tableaux de référence financiers décembre 2021",
            "link-fr": "https://www.canada.ca/fr/x/tableaux-reference-financiers/2021.html",
            "pub-date": "2021-12-14",
            "pub-type": "Fiscal Reference Tables",
        },
        {
            "title": "The Fiscal Monitor - July 2026",
            "link": "https://www.canada.ca/en/department-finance/services/publications/"
            "fiscal-monitor/2026/07.html",
            "title-fr": "La revue financière - juillet 2026",
            "link-fr": "https://www.canada.ca/fr/ministere-finances/services/publications/"
            "revue-financiere/2026/07.html",
            "pub-date": "2026-09-25",
            "pub-type": "Fiscal Monitor",
        },
        {
            "title": "The Fiscal Monitor - April and May 2026",
            "link": "https://www.canada.ca/en/x/fiscal-monitor/2026/04.html",
            "title-fr": "La revue financière - avril et mai 2026",
            "link-fr": "https://www.canada.ca/fr/x/revue-financiere/2026/04.html",
            "pub-date": "2026-07-31",
            "pub-type": "Fiscal Monitor",
        },
        {"title": "Budget 2025", "link": "x", "pub-type": "Federal Budget"},
    ]
}


def _workbook() -> bytes:
    """A workbook laid out like frt-trf-25-eng.xlsx: dividers, split headers, notes."""
    wb = Workbook()
    assert wb.active is not None
    wb.active.title = "colophon"
    wb.create_sheet("Fed - PA")
    revenues = wb.create_sheet("3 - Revenues")
    for row in [
        ["Table 3"],
        ["Revenues (millions of dollars)"],
        [None, None, None, "Non-", None],
        [None, "Personal", "Corporate", "resident", "Total"],
        ["Year", "income tax", "income tax", "income tax", "revenues"],
        [None, "(millions of dollars)"],
        ["1966-67", 3050, 1743, 305, 9975],
        ["2015-16 ", 144897, 41444, "-", 292608],
        ["2024-25", 234319.00000000003, 96954, 13528, 510951],
        ["Due to a break in the series, data before 1983-84 are not comparable."],
    ]:
        revenues.append(row)
    wb.create_sheet("NA")
    balance = wb.create_sheet("47-FederalBalanceSheet")
    for row in [
        ["Table 47"],
        ["Federal government liabilities and assets"],
        ["National Accounts basis"],
        [None, 2023, 2024],
        [None, "(millions of dollars)"],
        ["Liabilities"],
        ["    Currency and deposits", 6866, 6960],
        ["    Total liabilities", 1983915, 2068012],
        [None],
        ["Net worth (liabilities less assets)", -806033, -874806],
        ["Source: Statistics Canada, National Balance Sheet Accounts"],
    ]:
        balance.append(row)
    # The 2019 edition: two tables on one sheet, the second marker written twice.
    provinces = wb.create_sheet("18-19 NFLD+PEI")
    for row in [
        ["Table 18"],
        ["Newfoundland and Labrador"],
        [None, "Own-", "Deficit (-)"],
        ["Year", "source revenues", "or surplus"],
        [None, "(millions of dollars)"],
        ["1990-91", 1569.4, -347.4000000000001],
        ["Sources: Public Accounts of Newfoundland and Labrador"],
        [None],
        ["Table 19"],
        ["Table 19"],
        ["Prince Edward Island"],
        ["Year", "Revenues", "Net debt"],
        [None, "(millions of dollars)"],
        ["2024-25 Interim", 3000, 2500],
    ]:
        provinces.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_workbook_tables():
    tables = {t.info.number: t for t in client.parse_workbook(_workbook(), "en")}
    assert sorted(tables) == [3, 18, 19, 47]
    revenues = tables[3]
    assert revenues.info.part == "Federal government (Public Accounts)"
    assert revenues.info.columns == [
        "Year",
        "Personal income tax",
        "Corporate income tax",
        "Non-resident income tax",
        "Total revenues",
    ]
    assert revenues.info.units == ["(millions of dollars)"]
    assert revenues.rows[1]["Non-resident income tax"] is None
    assert revenues.rows[1]["Year"] == "2015-16"
    assert revenues.rows[2]["Personal income tax"] == 234319
    assert revenues.notes[0].startswith("Due to a break")
    balance = tables[47]
    assert balance.info.title == "Federal government liabilities and assets National Accounts basis"
    assert balance.info.columns == ["row", "2023", "2024"]
    assert balance.rows[0] == {
        "row": "Currency and deposits",
        "2023": 6866,
        "2024": 6960,
        "section": "Liabilities",
    }
    assert balance.notes == ["Source: Statistics Canada, National Balance Sheet Accounts"]
    assert tables[18].rows == [
        {"Year": "1990-91", "Own-source revenues": 1569.4, "Deficit (-) or surplus": -347.4}
    ]
    assert tables[19].info.title == "Prince Edward Island"
    assert tables[19].info.last_row == "2024-25 Interim"


def test_editions_from_the_feed():
    editions = client.frt_editions(_FEED["data"], "en")
    # 2019 and 2020 are not in the feed but still on canada.ca.
    assert [e.edition for e in editions] == [2025, 2021, 2020, 2019]
    assert editions[0].workbook_url.endswith("/frt-trf/2025/frt-trf-25-eng.xlsx")
    assert client.frt_editions(_FEED["data"], "fr")[0].workbook_url.endswith("25-fra.xlsx")


def _workbook_with_padding() -> bytes:
    """The client refuses a workbook with under 20 tables, as the real one has 55."""
    wb = Workbook()
    assert wb.active is not None
    wb.active.title = "Fed - PA"
    for n in range(1, 25):
        sheet = wb.create_sheet(f"{n} - T")
        for row in [[f"Table {n}"], [f"Title {n}"], ["Year", "A", "B"], ["2024-25", n, n * 2]]:
            sheet.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


async def test_list_and_get_frt(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL, content=json.dumps(_FEED).encode())
    url = "https://www.canada.ca/content/dam/fin/publications/frt-trf/2025/frt-trf-25-eng.xlsx"
    httpx_mock.add_response(url=url, content=_workbook_with_padding())
    listing = await client.list_frt_tables(query="title 12")
    assert listing.edition == 2025 and [t.number for t in listing.tables] == [12]
    table = await client.get_frt_table(3, last=1)
    assert table.rows == [{"Year": "2024-25", "A": 3, "B": 6}]
    with pytest.raises(NotFound):
        await client.get_frt_table(99)
    with pytest.raises(NotFound):
        await client.get_frt_table(1, edition=2015)
    with pytest.raises(InvalidInput):
        await client.get_frt_table(1, last=0)


async def test_workbook_too_small_is_an_error(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL, content=json.dumps(_FEED).encode())
    url = "https://www.canada.ca/content/dam/fin/publications/frt-trf/2025/frt-trf-25-eng.xlsx"
    httpx_mock.add_response(url=url, content=_workbook())
    with pytest.raises(UpstreamError):
        await client.list_frt_tables()


# ------------------------------------------------------------ Fiscal Monitor

_ISSUE = """<html><body><main>
<figure><figcaption>Chart 1 Monthly Budgetary Balance</figcaption>
<details><summary>Text version</summary>
<table><thead><tr><th>Month</th><th>2025-26</th><th>2026-27</th></tr></thead>
<tbody><tr><th>April</th><td> (7,711)</td><td> (1,046)</td></tr></tbody></table>
</details></figure>
<table id="t2"><caption>Table 2<br/><strong>Revenues</strong></caption>
<thead>
<tr><th rowspan="3"></th><th colspan="2">July</th><th></th><th colspan="2">April to July</th>
<th></th></tr>
<tr><th>2025<sup>1</sup></th><th>2026</th><th>Change</th><th>2025-26<sup>1</sup></th>
<th>2026-27</th><th>Change</th></tr>
<tr><th colspan="2">($ millions)</th><th>(%)</th><th colspan="2">($ millions)</th><th>(%)</th></tr>
</thead><tbody>
<tr><th colspan="7">Tax revenues</th></tr>
<tr><th>Personal</th><td>17,121</td><td>18,480</td><td>7.9</td><td>71,037</td><td>76,679</td>
<td>7.9</td></tr>
<tr><th>Other</th><td>n/a</td><td>-1,512</td><td>-</td><td>5</td><td>6</td><td>20.0</td></tr>
</tbody></table>
</main></body></html>"""

_ISSUE_FR = """<html><body><main>
<table><caption>Tableau 1<br/><strong>État sommaire des opérations</strong></caption>
<thead><tr><th></th><th colspan="3">Avril</th><th colspan="2">Avril à mai</th></tr>
<tr><th></th><th>2025</th><th colspan="2">2026</th><th>2025-2026</th><th>2026-2027</th></tr>
</thead><tbody>
<tr><th>Revenus</th><td>38 784</td><td colspan="2">45 890</td><td>76 028</td>
<td>87 826</td></tr>
<tr><th>Variation</th><td>5,2</td><td colspan="2">(7 711)</td><td>s.o.</td><td>1,0</td></tr>
</tbody></table></main></body></html>"""


def test_monitor_numbers():
    assert monitor.parse_number(" (7,711)") == -7711
    assert monitor.parse_number("17,121") == 17121
    assert monitor.parse_number("7.9") == 7.9
    assert monitor.parse_number("38 784", "fr") == 38784
    assert monitor.parse_number("5,2", "fr") == 5.2
    assert monitor.parse_number("n/a") is None
    assert monitor.parse_number("April") == "April"


def test_monitor_tables():
    chart, revenues = monitor.parse_issue(_ISSUE)
    assert chart.label == "Chart 1 Monthly Budgetary Balance"
    assert chart.rows == [{"Month": "April", "2025-26": -7711, "2026-27": -1046}]
    assert revenues.label == "Table 2 Revenues"
    assert revenues.columns == [
        "row",
        "July - 2025 - ($ millions)",
        "July - 2026 - ($ millions)",
        "July - Change - (%)",
        "April to July - 2025-26 - ($ millions)",
        "April to July - 2026-27 - ($ millions)",
        "April to July - Change - (%)",
    ]
    assert revenues.rows[0]["section"] == "Tax revenues"
    assert revenues.rows[0]["July - Change - (%)"] == 7.9
    assert revenues.rows[1]["July - 2025 - ($ millions)"] is None
    assert revenues.rows[1]["July - 2026 - ($ millions)"] == -1512


def test_two_month_issue_drops_the_repeated_column():
    (summary,) = monitor.parse_issue(_ISSUE_FR, "fr")
    assert summary.columns == [
        "row",
        "Avril - 2025",
        "Avril - 2026",
        "Avril à mai - 2025-2026",
        "Avril à mai - 2026-2027",
    ]
    assert summary.rows[1] == {
        "row": "Variation",
        "Avril - 2025": 5.2,
        "Avril - 2026": -7711,
        "Avril à mai - 2025-2026": None,
        "Avril à mai - 2026-2027": 1.0,
    }


async def test_monitor_issue_selection(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL, content=json.dumps(_FEED).encode())
    httpx_mock.add_response(
        url="https://www.canada.ca/en/department-finance/services/publications/"
        "fiscal-monitor/2026/07.html",
        text=_ISSUE,
    )
    issues = await monitor.list_issues()
    assert [i.period for i in issues.issues] == ["2026-07", "2026-04"]
    latest = await monitor.get_tables(table="2")
    assert latest.issue.period == "2026-07" and len(latest.tables) == 1
    chart = await monitor.get_tables("2026-07", table="Chart 1")
    assert chart.tables[0].label.startswith("Chart 1")
    with pytest.raises(NotFound):
        await monitor.get_tables("2026-05")
    with pytest.raises(InvalidInput):
        await monitor.get_tables("July 2026")
    with pytest.raises(NotFound):
        await monitor.get_tables("2026-07", table="Table 9")
