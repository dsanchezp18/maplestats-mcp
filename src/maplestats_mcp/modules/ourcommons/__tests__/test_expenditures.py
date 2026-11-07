"""Tests for the Members' Expenditures Reports, with pages and CSVs shaped like
the live ones of 2026-11-07 (see expenditures.py's docstring)."""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.ourcommons import constants, expenditures
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = constants.DISCLOSURE_URL.format(lang="en")
BASE_FR = constants.DISCLOSURE_URL.format(lang="fr")
REPORT = "9d297d77-146f-49ce-8e8a-3a3d634feaf3"
MEMBER = "b95a3afb-15ed-43c1-9003-df444968625a"

LANDING = """
<a href="/ProactiveDisclosure/en/members/2027/1?summaryId=3c8438ea-0966-43ff-bb73-71f9d5d76df5">Q1</a>
<a href="/ProactiveDisclosure/en/members/2026/4?summaryId=37d471d3-3bac-41b0-bfeb-2f9e870766f7">Q4</a>
<a href="/ProactiveDisclosure/en/members/2021/2?summaryId=125f6976-01e5-4a4d-9358-3f2b4f774be7">Q2</a>
"""
LANDING_FR = LANDING.replace("/en/members/", "/fr/deputes/")


def _row(name: str, riding: str, member: str | None) -> str:
    link = (
        f'<a href="/ProactiveDisclosure/en/members/travel/2027/1/{member}">$1</a>' if member else ""
    )
    return (
        f'<tr class="expenses-main-info"> <td class="text-nowrap"> {name} </td>'
        f"<td> {riding} </td><td> Conservative </td><td>$1</td><td>{link}</td></tr>"
    )


QUARTER_PAGE = (
    f'<a class="csv-btn" href="/ProactiveDisclosure/en/members/{REPORT}/csv">CSV</a><table>'
    + _row("Aboultaif, Ziad", "Edmonton Manning", MEMBER)
    + _row("Aitchison, Scott", "Parry Sound&#x2014;Muskoka", "1e100f70-e4ed-4342-af71-b13633461369")
    + _row("Reid, Scott", "Lanark&#x2014;Frontenac", None)
    + "</table>"
)
SUMMARY = (
    "﻿Name,Constituency,Caucus,Salaries,Travel,Hospitality,Contracts\n"
    '"Aboultaif,  Ziad",Edmonton Manning,Conservative,65140.53,62251.81,349.43,14503\n'
    '"Aitchison,  Scott",Parry Sound—Muskoka,Conservative,79093.73,49497.38,1443.09,30187.72\n'
    '"Reid,  Scott",Lanark—Frontenac,Conservative,0,0,0,0\n'
    '"Davies,  Don",Vancouver Kingsway,New Democratic Party,70000,90000,10,20000\n'
)
TRAVEL = (
    '﻿"Members – Detailed Travel Expenditures Report – Aboultaif, Ziad"\n'
    "Travel start date,Travel end date,Departure,Places Visited,Purpose of Travel,"
    "Traveller Name,Traveller Type,Transportation,Accommodations,Meals and Incidentals,Total\n"
    '2026-01-24,2026-02-06,Edmonton,Ottawa,Session,"Aboultaif, Ziad",Member,'
    "-1592.56,0,0,-1592.56\n"
    "2026-02-22,2026-02-27,Edmonton,Ottawa,Reunite with the Member,,Designated Traveller,"
    "63844.37,0,0,63844.37\n"
)
HOSPITALITY = (
    '﻿"Members – Detailed Hospitality Expenditures Report – Aboultaif, Ziad"\n'
    "Date,Location,Total of Attendees,Purpose of Hospitality,Supplier,Amount,Total\n"
    "2026-05-07,Ottawa,5,To meet visitors,House of Commons Food Services,7.06,349.43\n"
    "2026-05-07,Ottawa,5,To meet visitors,Shawarma Maestro,342.37,349.43\n"
)
CONTRACT = (
    '﻿"Members – Detailed Contract Expenditures Report – Aboultaif, Ziad"\n'
    "Supplier,Description,Date,Total\n"
    "Bilbo Holdings Ltd.,Office Rental,2026-04-01,14503\n"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _mock_quarter(httpx_mock) -> None:
    httpx_mock.add_response(url=BASE, text=LANDING)
    httpx_mock.add_response(url=f"{BASE}/2027/1", text=QUARTER_PAGE)
    httpx_mock.add_response(url=f"{BASE}/{REPORT}/csv", content=SUMMARY.encode("utf-8"))


def test_period_of_a_fiscal_quarter():
    assert expenditures.period(2027, 1) == (date(2026, 4, 1), date(2026, 6, 30))
    assert expenditures.period(2026, 4) == (date(2026, 1, 1), date(2026, 3, 31))
    assert expenditures.period(2021, 3)[1] == date(2020, 12, 31)


async def test_list_reports_newest_first(httpx_mock):
    httpx_mock.add_response(url=BASE, text=LANDING)
    result = await expenditures.list_expenditure_reports()
    assert [(r.fiscal_year, r.quarter) for r in result.reports] == [(2027, 1), (2026, 4), (2021, 2)]
    assert result.reports[0].fiscal_year_label == "2026-2027"
    assert result.reports[0].url == f"{BASE}/2027/1"


async def test_list_reports_in_french(httpx_mock):
    httpx_mock.add_response(url=BASE_FR, text=LANDING_FR)
    result = await expenditures.list_expenditure_reports(lang="fr")
    assert result.total_reports == 3
    assert (result.provenance.freshness or "").startswith("Trimestriel")


async def test_summary_latest_sorted_and_filtered(httpx_mock):
    _mock_quarter(httpx_mock)
    result = await expenditures.get_member_expenditures(caucus="conservative")
    assert (result.fiscal_year, result.quarter) == (2027, 1)
    assert result.members_in_report == 4 and result.total_matches == 3
    first = result.members[0]
    assert first.name == "Aitchison, Scott" and first.total == 160221.92
    assert result.totals.travel == 111749.19
    assert "House of Commons" in (result.provenance.licence or "")


async def test_ndp_caucus_spelled_out_matches_the_code(httpx_mock):
    _mock_quarter(httpx_mock)
    result = await expenditures.get_member_expenditures(caucus="NDP", sort_by="name")
    assert [m.name for m in result.members] == ["Davies, Don"]


async def test_unknown_quarter_and_half_a_quarter(httpx_mock):
    httpx_mock.add_response(url=BASE, text=LANDING)
    with pytest.raises(NotFound, match="2021 Q2 to 2027 Q1"):
        await expenditures.get_member_expenditures(fiscal_year=2019, quarter=1)
    with pytest.raises(InvalidInput):
        await expenditures.get_member_expenditures(fiscal_year=2027)


async def test_details_add_up_to_the_summary(httpx_mock):
    _mock_quarter(httpx_mock)
    for kind, body in (("travel", TRAVEL), ("hospitality", HOSPITALITY), ("contract", CONTRACT)):
        httpx_mock.add_response(
            url=f"{BASE}/{kind}/{REPORT}/{MEMBER}/csv", content=body.encode("utf-8")
        )
    result = await expenditures.get_member_expenditure_details("aboultaif")
    assert result.travel is not None and result.hospitality is not None
    assert result.contracts is not None
    assert round(sum(t.total for t in result.travel), 2) == result.travel_total == 62251.81
    assert round(sum(h.amount for h in result.hospitality), 2) == result.hospitality_total
    assert result.contracts[0].total == result.contracts_total == 14503
    assert result.travel[0].total < 0 and result.travel[1].traveller_name is None
    assert result.hospitality[0].attendees == 5
    assert result.hospitality[0].event_date == date(2026, 5, 7)


async def test_details_ambiguous_name_and_member_without_links(httpx_mock):
    _mock_quarter(httpx_mock)
    with pytest.raises(InvalidInput, match="Narrow with constituency"):
        await expenditures.get_member_expenditure_details("Scott")
    result = await expenditures.get_member_expenditure_details(
        "Scott", constituency="Lanark", categories=["travel"]
    )
    assert result.name == "Reid, Scott" and result.travel == []
    assert result.hospitality is None and result.contracts is None


async def test_details_bad_category():
    with pytest.raises(InvalidInput):
        await expenditures.get_member_expenditure_details("x", categories=["meals"])


async def test_error_page_redirect_is_not_found(httpx_mock):
    httpx_mock.add_response(url=BASE, text=LANDING)
    httpx_mock.add_response(
        url=f"{BASE}/2026/4", status_code=302, headers={"Location": "/ErrorPage"}
    )
    with pytest.raises(NotFound):
        await expenditures.get_member_expenditures(fiscal_year=2026, quarter=4)
