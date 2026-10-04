"""Tests on markup trimmed from PMPRB pages on canada.ca (2026-09-27)."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.pmprb import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_EN = "https://www.canada.ca/en/patented-medicine-prices-review/services"

_INDEX = f"""<html><body><main>
<a href="/en/patented-medicine-prices-review/services/annual-reports/annual-report-2024.html">
Annual Report 2024</a>
<a href="/content/dam/pmprb-cepmb/2024/PMPRB-2024-Annual-Report-EN.pdf">PDF 2.6 MB</a>
<a href="/en/patented-medicine-prices-review/services/annual-reports/patented-medicines-reported-2021.html">
List of Patented Medicines 2021</a>
<a href="{_EN}/reports-studies/annual-report-2018.html">Annual Report 2018</a>
<a href="/content/dam/pmprb-cepmb/2019/annual-report-list-2019-en.pdf">List of Patented Medicines 2019 (PDF 2.4 MB)</a>
<a href="http://www.pmprb-cepmb.gc.ca/view.asp?ccid=1380&amp;lang=en">Annual Report 2017</a>
</main></body></html>"""

_REPORT = """<html><body><main>
<h2 id="a4">Budget</h2>
<p><b>Table 1. Budget and Staffing</b></p>
<div class="table-responsive"><table>
<thead><tr><th></th><th>2023-24</th><th>2024-25</th></tr></thead>
<tbody><tr><th>Budget *</th><td>$17,093,674</td><td>$17,746,047</td></tr>
<tr><td>Full Time Employees (FTEs)</td><td>81</td><td>81</td></tr></tbody>
</table></div>
<h2>Price Trends</h2>
<p>Figure 1 illustrates the change in prices.</p>
<figure><b>Figure 1. Annual Rate of Change, <abbr>PMPI</abbr> and CPI, 2005 to 2024</b>
<img src="fig1.png"/></figure>
<details><summary>Figure description</summary><p>This line graph ...</p>
<table><thead><tr><th>Year</th><th>CPI rate of change</th><th>CPI index</th></tr></thead>
<tbody><tr><td>2023</td><td>3.9%</td><td>157.1</td></tr>
<tr><td>2024</td><td>2.4%</td><td>160.9</td></tr></tbody></table></details>
<details><summary>Figure description</summary>
<table><tr><th>Year</th><th>Rate</th></tr><tr><td>2024</td><td>&#8722;1.5%</td></tr></table>
</details>
<figure><b>Figure 10. Foreign-to-Canadian List Price Comparisons</b></figure>
<details><table><tr><th>Country</th><th>Percent difference</th></tr>
<tr><td>Japan</td><td>n/a</td></tr></table></details>
<h2>Trends in Sales</h2>
<p><strong>Table 5. Sales of Patented Medicines, 2020 to 2024</strong></p>
<table><thead>
<tr><th rowspan="2">Year</th><th colspan="2">Patented medicine</th><th rowspan="2">Share</th></tr>
<tr><th>Sales ($billions)</th><th>Change in sales</th></tr></thead>
<tbody><tr><td>2024</td><td>$22.1</td><td>10.9%</td><td>47.2%</td></tr>
<tr><td></td><td></td><td></td><td></td></tr></tbody></table>
<p><strong>Table 2. Status of Board Proceedings</strong></p>
<table><caption>Allegations of Excessive Pricing</caption>
<tr><th>Medicine</th><th>Status</th></tr><tr><td>Soliris</td><td>Hearing</td></tr></table>
<table><caption>Table 7. Top 10 Medicines</caption>
<tr><th>Medicine</th><th>Status</th></tr><tr><td>Keytruda</td><td>x</td></tr></table>
</main></body></html>"""

_REPORT_FR = """<html><body><main><h2>Tendances</h2>
<p><strong>Tableau 7. Dépenses totales de R-D</strong></p>
<table><tr><th>Année</th><th>Dépenses</th><th>Variation</th></tr>
<tr><td>2024</td><td>1&#160;294,8$</td><td>21,1&#8239;%</td></tr></table>
</main></body></html>"""

_LIST = """<html><body><main>
<table><caption>AbbVie Corporation</caption>
<tr><th>DIN</th><th>Brand Name</th><th>Medicinal Ingredient</th><th>ATC</th><th>Dosage</th>
<th>Comments</th><th>Status</th></tr>
<tr><td>02474263</td><td>HUMIRA - 20 MG/SYRINGE</td><td>adalimumab</td><td>L04AB</td>
<td>Parenteral/Solution</td><td>blank</td><td>Within Guidelines</td></tr>
<tr><td>02312301</td><td>KALETRA 100/25 MG/TABLET</td><td>lopinavir/ritonavir</td><td>J05AE</td>
<td>Oral Solid/Tablet</td><td>Expired</td><td>Does not Trigger</td></tr></table>
<table><caption>Pfizer Canada ULC</caption>
<tr><th>DIN</th><th>Brand Name</th><th>Medicinal Ingredient</th><th>ATC</th><th>Dosage</th>
<th>Comments</th><th>Status</th></tr>
<tr><td>02491087</td><td>XELJANZ</td><td>tofacitinib</td><td>L04AA</td><td>Oral</td>
<td>Introduced</td><td>NOH</td></tr></table>
</main></body></html>"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _mock_index(httpx_mock, lang: str = "en") -> None:
    httpx_mock.add_response(url=constants.INDEX_PAGE[lang], text=_INDEX)


def test_index_keeps_canada_ca_html_pages_only():
    reports = client.parse_index(_INDEX, constants.INDEX_PAGE["en"])
    assert [(r.kind, r.year) for r in reports] == [
        ("annual_report", 2024),
        ("annual_report", 2018),
        ("patented_medicines_list", 2021),
    ]
    assert reports[1].url.endswith("/reports-studies/annual-report-2018.html")


def test_numbers_in_both_languages():
    assert client.parse_number("$17,093,674", "en") == 17093674
    assert client.parse_number("10.9%", "en") == 10.9
    assert client.parse_number("−1.5%", "en") == -1.5
    assert client.parse_number("1 294,8$", "fr") == 1294.8
    assert client.parse_number("21,1 %", "fr") == 21.1
    assert client.parse_number("2023-24", "en") == "2023-24"
    assert client.parse_number("", "en") is None


def test_report_tables_labels_headers_and_rows():
    tables = client.parse_report(_REPORT, 2024, "en")
    labels = [(t.info.index, t.info.label, t.info.subtitle) for t in tables]
    assert labels[0] == (1, "Table 1. Budget and Staffing", None)
    # The prose "Figure 1 illustrates ..." is not taken as a title.
    assert labels[1][1] == "Figure 1. Annual Rate of Change, PMPI and CPI, 2005 to 2024"
    assert labels[2][1] == labels[1][1]  # a figure's second data table
    assert labels[5][1:] == (
        "Table 2. Status of Board Proceedings",
        "Allegations of Excessive Pricing",
    )
    # A caption holding the real title wins over the nearest <b>.
    assert labels[6][1:] == ("Table 7. Top 10 Medicines", None)

    budget = tables[0]
    assert budget.info.section == "Budget"
    assert budget.info.columns == ["row", "2023-24", "2024-25"]
    assert budget.rows[0] == {"row": "Budget *", "2023-24": 17093674, "2024-25": 17746047}

    sales = tables[4]
    assert sales.info.columns == [
        "Year",
        "Patented medicine - Sales ($billions)",
        "Patented medicine - Change in sales",
        "Share",
    ]
    assert sales.rows == [
        {
            "Year": 2024,
            "Patented medicine - Sales ($billions)": 22.1,
            "Patented medicine - Change in sales": 10.9,
            "Share": 47.2,
        }
    ]
    assert tables[2].rows == [{"Year": 2024, "Rate": -1.5}]  # header row without <thead>


async def test_get_table_by_title_position_and_language(httpx_mock):
    _mock_index(httpx_mock)
    httpx_mock.add_response(url=f"{_EN}/annual-reports/annual-report-2024.html", text=_REPORT)
    figure = await client.get_report_table(2024, "figure 1")
    # "Figure 1" matches Figure 1's two tables, not Figure 10.
    assert [t.info.index for t in figure.tables] == [2, 3]
    assert figure.tables[0].rows[-1] == {
        "Year": 2024,
        "CPI rate of change": 2.4,
        "CPI index": 160.9,
    }
    by_position = await client.get_report_table(2024, "4")
    assert (
        by_position.tables[0].info.label == "Figure 10. Foreign-to-Canadian List Price Comparisons"
    )
    assert (await client.get_report_table(2024, "Tableau 5")).tables[0].info.index == 5
    with pytest.raises(NotFound):
        await client.get_report_table(2024, "Figure 99")
    with pytest.raises(NotFound):
        await client.get_report_table(2017, "Table 1")


async def test_list_and_search_tables(httpx_mock):
    _mock_index(httpx_mock)
    httpx_mock.add_response(url=f"{_EN}/annual-reports/annual-report-2024.html", text=_REPORT)
    httpx_mock.add_response(url=f"{_EN}/reports-studies/annual-report-2018.html", text=_REPORT)
    reports_only = await client.list_report_tables()
    assert reports_only.total_matched == 0 and len(reports_only.reports) == 3
    one_year = await client.list_report_tables(2024)
    assert one_year.total_matched == 7
    found = await client.list_report_tables(query="cpi")
    # Figure 1 owns tables 2 and 3, so both match on its title.
    assert [(t.year, t.index) for t in found.tables] == [(2024, 2), (2024, 3), (2018, 2), (2018, 3)]


async def test_french_report(httpx_mock):
    httpx_mock.add_response(
        url=constants.INDEX_PAGE["fr"],
        text='<main><a href="/fr/x/rapport-annuel-2024.html">Rapport annuel 2024</a></main>',
    )
    httpx_mock.add_response(
        url="https://www.canada.ca/fr/x/rapport-annuel-2024.html", text=_REPORT_FR
    )
    result = await client.get_report_table(2024, "Table 7", lang="fr")
    assert result.tables[0].rows == [{"Année": 2024, "Dépenses": 1294.8, "Variation": 21.1}]


async def test_patented_medicines(httpx_mock):
    _mock_index(httpx_mock)
    httpx_mock.add_response(
        url=f"{_EN}/annual-reports/patented-medicines-reported-2021.html", text=_LIST
    )
    everything = await client.search_patented_medicines()
    assert everything.total_matched == 3
    assert everything.by_status == {
        "within_guidelines": 1,
        "does_not_trigger": 1,
        "notice_of_hearing": 1,
    }
    humira = everything.medicines[0]
    assert (humira.company, humira.din, humira.comments) == ("AbbVie Corporation", "02474263", None)
    assert (await client.search_patented_medicines(company="pfizer")).medicines[0].brand_name == (
        "XELJANZ"
    )
    assert (await client.search_patented_medicines(atc="l04")).total_matched == 2
    hearing = await client.search_patented_medicines(status="notice_of_hearing")
    assert hearing.medicines[0].status_label == "Notice of Hearing"
    assert (await client.search_patented_medicines("KALETRA")).medicines[0].comments == "Expired"


async def test_medicines_errors(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_patented_medicines(limit=0)
    with pytest.raises(InvalidInput):
        await client.search_patented_medicines(status="approved")
    _mock_index(httpx_mock)
    with pytest.raises(NotFound):
        await client.search_patented_medicines(year=2019)  # a PDF only


async def test_french_provenance_and_errors(httpx_mock):
    httpx_mock.add_response(
        url=constants.INDEX_PAGE["fr"],
        text='<main><a href="/fr/x/rapport-annuel-2024.html">Rapport annuel 2024</a></main>',
    )
    httpx_mock.add_response(
        url="https://www.canada.ca/fr/x/rapport-annuel-2024.html", text=_REPORT_FR
    )
    result = await client.get_report_table(2024, "Table 7", lang="fr")
    assert result.provenance.freshness == "une fois par année (chaque rapport annuel)"
    assert "Avis du site Web du gouvernement du Canada" in (result.provenance.licence or "")
    with pytest.raises(NotFound, match=r"^Aucune correspondance trouvée\xa0: pmprb\xa0: aucun"):
        await client.get_report_table(2024, "Table 99", lang="fr")
    with pytest.raises(InvalidInput, match="statut 'approved' inconnu"):
        await client.search_patented_medicines(status="approved", lang="fr")
    with pytest.raises(InvalidInput, match=r"^pmprb: limit must be 1 to"):
        await client.search_patented_medicines(limit=0)
