"""Tests for cra_tax_stats/client.py, on rows trimmed from the live files read 2026-11-19.

Each fixture keeps its edition's real quirks: Windows-1252 bilingual headers to
2023, millions of dollars in Table 1 to 2021, a 0 in the amount cell of count rows
from 2022, English-only 2024 headers, the 2021 FSA file's quote line and its unit
change from dollars to thousands, and package resources that link the wrong file.
"""

from __future__ import annotations

import re

import httpx
import pytest

from maplestats_mcp.modules.cra_tax_stats import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_BASE = "https://www.canada.ca/content/dam/cra-arc/prog-policy/stats"

# Table 1, 2018 edition (cp1252, bilingual, amounts in millions of dollars).
_T1_2018 = (
    "PROV_E,PROV_F,Tax year/Année d'imposition,Number of returns/Nombre de déclarations,"
    '"Total income assessed (000,000)/Revenu total établi (000 000)",'
    '"Total tax payable (000,000)/Impôt total à payer (000 000)",Return/Déclarations\r\n'
    "Alberta,Alberta,2018,2270050,180123,30500,Taxable returns/Déclarations imposables\r\n"
    "Canada,Canada,2018,19967650,1356387,231526,Taxable returns/Déclarations imposables\r\n"
    "Canada,Canada,2018,9084120,107151,0,Non taxable returns/Déclarations non imposables\r\n"
    "Canada,Canada,2018,29051760,1463537,231526,All returns/Toutes les déclarations\r\n"
).encode("cp1252")

# Table 1, 2024 edition (English only, thousands of dollars, padded cells).
_T1_2024 = (
    b"Province or territory,Tax year,Number of returns,Total income assessed (Thousands of $),"
    b"Total tax payable (Thousands of $),Return\n"
    b'Canada ,2024 ,31564157 ,2023605613 ,331230063 ,"All returns"\n'
    b'Canada ,2024 ,8994320 ,128929155 ,0 ,"Non-taxable returns"\n'
)

# Table 2, 2022 edition: "(Number / Nombre)" headers and a 0 beside count rows.
_T2_2022 = (
    "#,Item,Poste, Tax year/Année d'imposition , Total (Number / Nombre) ,"
    "Total (Thousands of Dollars / Milliers de dollars),"
    "4999 and under/Moins de 4 999 (Number / Nombre),"
    "4999 and under/Moins de 4 999 (Thousands of Dollars / Milliers de dollars)\n"
    "1,Number of taxable returns,Nombre de déclarations imposables,2022, 21408730,0,36780,0\n"
    "4,Employment income,Revenus d'emploi,2022, 19264950,1124466583,700000,1500000\n"
    "15,Total income assessed,Revenu total établi,2022, 29574480,1808608128,2600000,3000000\n"
).encode("cp1252")

# Table 2, 2024 edition: "Number" item column, English only.
_T2_2024 = (
    b"Number,Item, Tax year , Total (Number),Total (Thousands of Dollars),"
    b"4999 and under (Number),4999 and under (Thousands of Dollars)\n"
    b"1,Number of taxable returns,2024, 22569830,0,104980,0\n"
    b"4,Employment income,2024, 19453720,1247237840,587030,1609121\n"
    b"15,Total income assessed,2024, 30164960,2023605613,2686310,3000000\n"
)

# Table 3, 2018 edition: "#" and "$ (000)" columns, a slash inside an English group.
_T3_2018 = (
    "#,Item,Poste, Tax year/Année d'imposition , Grand total/Total global #,"
    "Grand total/Total global $ (000),"
    "Proprietorships/Partnerships/Entreprises indiv./Soc. de pers. #,"
    "Proprietorships/Partnerships/Entreprises indiv./Soc. de pers. $ (000)\n"
    "1,Number of taxable returns,Nombre de déclarations imposables,2018, 19967650,,955640,\n"
    "4,Employment income,Revenus d'emploi,2018, 18150220,910545087,300000,9000000\n"
).encode("cp1252")

# FSA Table 1a, 2019 edition: whole dollars, trailing empty rows.
_FSA_2019 = (
    b"Prov/Terr,FSA,Total,Total Income,Net Income,Taxable Income,,,\r\n"
    b"48,T5K,20150 ,1199830000 ,1100000000 ,1000000000 ,,,\r\n"
    b"48,Total,2500000 ,150000000000 ,140000000000 ,130000000000 ,,,\r\n"
    b",,,,,,,,\r\n"
)

# FSA Table 1a, 2021 edition: a quote line and a blank line first, thousands of dollars.
_FSA_2021 = (
    b"'\r\n\r\n"
    b'"Prov/Terr","FSA","Total","Total income","Net income","Taxable income"\r\n'
    b'48,"T5K",20530,1134003,1050000,990000\r\n'
    b'"Canada","Total",29866500,1726353028,1583936322,1525544645\r\n'
)

_FSA_1E_2018 = (
    b"Prov/Terr,FSA,Employment Income #,Employment Income $,Pension Income #,Pension Income $\n"
    b"24,H2X,12000 ,600000000 ,3000 ,60000000\n"
)


def _package(dataset_id: str, title: str, resources: list[dict[str, object]]) -> dict:
    return {
        "success": True,
        "result": {
            "id": dataset_id,
            "title": title,
            "title_translated": {"en": title, "fr": f"FR {title}"},
            "license_id": "ca-ogl-lgo",
            "resources": resources,
        },
    }


def _resource(rid: str, url: str, lang: str = "en", fmt: str = "CSV") -> dict[str, object]:
    return {"id": rid, "url": url, "format": fmt, "language": [lang], "name": rid}


def _mock_package(httpx_mock, series: str, year: int, resources: list[dict[str, object]]):
    editions = constants.T1_EDITIONS if series == "t1_final" else constants.FSA_EDITIONS
    dataset_id = editions[year]
    httpx_mock.add_response(
        url=re.compile(re.escape(constants.CKAN_BASE_URL) + rf"package_show\?id={dataset_id}"),
        json=_package(dataset_id, f"{series} {year}", resources),
    )


def _t1_url(year: int, name: str) -> str:
    return f"{_BASE}/t1-final-stats/{year}-tax-year/{name}"


def _fsa_url(year: int, name: str) -> str:
    return f"{_BASE}/individual-tax-stats-fsa/{year}-tax-year/{name}"


# ------------------------------------------------------------------ parsing


def test_parse_t1_table1_converts_millions_and_normalizes_return_type():
    rows = client.parse_t1(_T1_2018, 2018)
    canada = [r for r in rows if r.group == "Canada" and r.item == "Total income assessed"]
    by_type = {r.return_type: r for r in canada}
    assert set(by_type) == {"Taxable returns", "Non-taxable returns", "All returns"}
    all_returns = by_type["All returns"]
    assert all_returns.value == 1_463_537_000
    assert all_returns.unit == "thousands of dollars"
    assert all_returns.published_unit == "millions of dollars"
    count = next(r for r in rows if r.item == "Number of returns" and r.group == "Alberta")
    assert (count.measure, count.value, count.unit) == ("number", 2_270_050, "number")


def test_parse_t1_table1_2024_english_only():
    rows = client.parse_t1(_T1_2024, 2024)
    income = next(
        r for r in rows if r.item == "Total income assessed" and r.return_type == "All returns"
    )
    assert income.value == 2_023_605_613
    assert income.published_unit == "thousands of dollars"
    assert {r.return_type for r in rows} == {"All returns", "Non-taxable returns"}


def test_parse_t1_drops_the_zero_amount_of_count_rows():
    rows = client.parse_t1(_T2_2022, 2022)
    taxable = [r for r in rows if r.item == "Number of taxable returns"]
    assert {r.measure for r in taxable} == {"number"}
    employment = [r for r in rows if r.item == "Employment income" and r.group == "Total"]
    assert {(r.measure, r.value) for r in employment} == {
        ("number", 19_264_950),
        ("amount", 1_124_466_583),
    }
    assert employment[0].item_fr == "Revenus d'emploi"
    assert employment[0].item_number == 4
    assert {r.group for r in rows} == {"Total", "4999 and under"}


def test_parse_t1_2024_number_column_and_2018_grand_total():
    rows_2024 = client.parse_t1(_T2_2024, 2024)
    assert next(r for r in rows_2024 if r.item == "Employment income").item_number == 4
    assert all(r.item_fr is None for r in rows_2024)
    rows_2018 = client.parse_t1(_T3_2018, 2018)
    assert {r.group for r in rows_2018} == {"Total", "Proprietorships/Partnerships"}
    amount = next(r for r in rows_2018 if r.item == "Employment income" and r.measure == "amount")
    assert amount.value == 910_545_087
    # The blank amount beside a count row is skipped, not read as 0.
    assert not [r for r in rows_2018 if r.item.startswith("Number") and r.measure == "amount"]


def test_parse_fsa_harmonizes_dollars_to_thousands():
    old = client.parse_fsa(_FSA_2019, 2019)
    income = next(r for r in old if r.fsa == "T5K" and r.item == "Total Income")
    assert income.value == 1_199_830
    assert income.published_unit == "dollars"
    assert next(r for r in old if r.fsa == "T5K" and r.item == "Total").measure == "number"
    assert {r.fsa for r in old} == {"T5K", "Total"}
    new = client.parse_fsa(_FSA_2021, 2021)
    income = next(r for r in new if r.fsa == "T5K" and r.item == "Total income")
    assert (income.value, income.published_unit) == (1_134_003, "thousands of dollars")
    canada = next(r for r in new if r.province == "ca")
    assert canada.fsa == "Total"


def test_parse_fsa_source_table_pairs_number_and_amount():
    rows = client.parse_fsa(_FSA_1E_2018, 2018)
    assert {(r.item, r.measure) for r in rows} == {
        ("Employment Income", "number"),
        ("Employment Income", "amount"),
        ("Pension Income", "number"),
        ("Pension Income", "amount"),
    }
    assert next(r for r in rows if r.measure == "amount").value == 600_000
    assert rows[0].province == "qc"


def test_table_files_matches_by_file_name_not_resource_tags():
    package = _package(
        "x",
        "T1 2024",
        [
            _resource("a", _t1_url(2024, "tbl1_ac_en.csv")),
            _resource("b", _t1_url(2024, "tbl1_ac_fr.csv"), "fr"),
            # The French Nova Scotia resource links the English file (live, 2026-11-19).
            _resource("c", _t1_url(2024, "tbl2_ns_en.csv"), "fr"),
            _resource("d", _t1_url(2024, "tbl2_ns_en.csv")),
            # A "CSV" resource that is a PDF (2021 Table 2, Alberta).
            _resource("e", _t1_url(2021, "table2_ab-fra.pdf")),
            _resource("f", _t1_url(2018, "table1.csv")),
            _resource("g", "http://www.cra-arc.gc.ca/gncy/stts/t1fnl/2014/tbl1.csv"),
        ],
    )["result"]
    files = client.table_files("t1_final", package)
    assert [(f.table, f.area, f.resource_id) for f in files] == [
        ("1", "ca", "a"),
        ("2", "ns", "c"),
    ]


# ------------------------------------------------------------------ catalogue


async def test_list_tables_without_year_needs_no_request():
    result = await client.list_tables("fsa")
    assert [e.tax_year for e in result.editions] == [2017, 2018, 2019, 2020, 2021]
    assert result.tables == []
    assert "Open Government Licence - Canada" in (result.provenance.licence or "")


async def test_list_tables_for_one_edition(httpx_mock):
    _mock_package(
        httpx_mock,
        "t1_final",
        2022,
        [
            _resource("t1", _t1_url(2022, "tbl1_ac.csv")),
            _resource("t2", _t1_url(2022, "tbl2_ac.csv")),
            _resource("t2nl", _t1_url(2022, "tbl2_nl.csv")),
            _resource("pdf", _t1_url(2022, "tbl2_ac.pdf"), fmt="PDF"),
        ],
    )
    result = await client.list_tables("t1_final", 2022)
    assert [(t.table, t.area) for t in result.tables] == [("1", "ca"), ("2", "ca"), ("2", "nl")]
    assert "Canada Revenue Agency" in (result.provenance.coverage or "")


async def test_list_tables_rejects_uncovered_year_in_french():
    with pytest.raises(InvalidInput, match="année d'imposition 2016"):
        await client.list_tables("t1_final", 2016, lang="fr")


# ------------------------------------------------------------------ T1 reads


async def test_get_t1_table_filters_and_pages(httpx_mock):
    _mock_package(httpx_mock, "t1_final", 2022, [_resource("t2", _t1_url(2022, "tbl2_ac.csv"))])
    httpx_mock.add_response(url=_t1_url(2022, "tbl2_ac.csv"), content=_T2_2022)
    result = await client.get_t1_table(2022, 2, item="income", group="total", limit=1)
    assert result.total_rows == 4
    assert len(result.rows) == 1 and result.truncated
    assert "rows 1 to 1 of 4" in (result.provenance.limits or "")
    assert result.source_url.endswith("tbl2_ac.csv")


async def test_get_t1_table_retries_a_dropped_connection(httpx_mock):
    _mock_package(httpx_mock, "t1_final", 2024, [_resource("t1", _t1_url(2024, "tbl1_ac_en.csv"))])
    # canada.ca sometimes closes the connection mid-answer; the shared retries absorb it.
    httpx_mock.add_exception(
        httpx.RemoteProtocolError("Server disconnected"), url=_t1_url(2024, "tbl1_ac_en.csv")
    )
    httpx_mock.add_response(url=_t1_url(2024, "tbl1_ac_en.csv"), content=_T1_2024)
    result = await client.get_t1_table(2024, 1, measure="amount", item="total income")
    assert [r.value for r in result.rows if r.return_type == "All returns"] == [2_023_605_613]


async def test_get_t1_table_missing_file_is_not_found(httpx_mock):
    _mock_package(httpx_mock, "t1_final", 2024, [_resource("t1", _t1_url(2024, "tbl1_ac_en.csv"))])
    with pytest.raises(NotFound, match="no readable CSV for table 5"):
        await client.get_t1_table(2024, 5)


async def test_html_page_is_an_upstream_error_and_not_cached(httpx_mock):
    # A 200 error page used to be kept in the shared file cache for 24 hours and then
    # reported as NotFound ("returned a web page") on every call until it expired.
    _mock_package(httpx_mock, "t1_final", 2022, [_resource("t2", _t1_url(2022, "tbl2_ac.csv"))])
    httpx_mock.add_response(
        url=_t1_url(2022, "tbl2_ac.csv"), content=b"<!DOCTYPE html><html>Maintenance</html>"
    )
    httpx_mock.add_response(url=_t1_url(2022, "tbl2_ac.csv"), content=_T2_2022)
    with pytest.raises(UpstreamError, match="web page"):
        await client.get_t1_table(2022, 2)
    result = await client.get_t1_table(2022, 2)
    assert result.total_rows > 0


async def test_web_page_error_is_in_french_on_request(httpx_mock):
    # The web-page error was English only; the module's other errors follow `lang`.
    _mock_package(httpx_mock, "t1_final", 2022, [_resource("t2", _t1_url(2022, "tbl2_ac.csv"))])
    httpx_mock.add_response(url=_t1_url(2022, "tbl2_ac.csv"), content=b"<html>Maintenance</html>")
    with pytest.raises(UpstreamError, match="page Web, pas un fichier CSV"):
        await client.get_t1_table(2022, 2, lang="fr")
    # The parser's own check (a bad body reaching it without the download's check).
    with pytest.raises(UpstreamError, match="page Web, pas un fichier CSV"):
        client.parse_t1(b"<!doctype html><html></html>", 2022, "https://x", lang="fr")
    with pytest.raises(UpstreamError, match="web page, not a CSV file"):
        client.parse_fsa(b"<!doctype html><html></html>", 2021, "https://x")


async def test_get_t1_series_does_not_read_an_error_page_as_a_missing_year(httpx_mock):
    # The NotFound a web page raised was caught as "no file for that year", so the
    # outage came back as missing_years / "no matching row in 2024".
    _mock_package(httpx_mock, "t1_final", 2024, [_resource("b", _t1_url(2024, "tbl1_ac_en.csv"))])
    httpx_mock.add_response(url=_t1_url(2024, "tbl1_ac_en.csv"), content=b"<html>Error</html>")
    with pytest.raises(UpstreamError, match="web page"):
        await client.get_t1_series(1, "Total income assessed", from_year=2024)


async def test_fsa_error_page_is_not_cached(httpx_mock):
    _mock_package(httpx_mock, "fsa", 2021, [_resource("a", _fsa_url(2021, "tbl1a-en.csv"))])
    httpx_mock.add_response(url=_fsa_url(2021, "tbl1a-en.csv"), content=b"  <!doctype html>...")
    httpx_mock.add_response(url=_fsa_url(2021, "tbl1a-en.csv"), content=_FSA_2021)
    with pytest.raises(UpstreamError, match="web page"):
        await client.get_fsa_table(2021, "1a")
    assert (await client.get_fsa_table(2021, "1a", fsa=["T5K"])).total_rows == 4


async def test_get_t1_table_checks_arguments():
    with pytest.raises(InvalidInput, match="table must be 1 to 5"):
        await client.get_t1_table(2024, 6)
    with pytest.raises(InvalidInput, match="area 'zz'"):
        await client.get_t1_table(2024, 2, area="zz")
    with pytest.raises(InvalidInput, match="limit"):
        await client.get_t1_table(2024, 2, limit=0)


async def test_get_t1_series_puts_editions_in_one_unit(httpx_mock):
    _mock_package(httpx_mock, "t1_final", 2021, [_resource("a", _t1_url(2021, "table1.csv"))])
    _mock_package(httpx_mock, "t1_final", 2024, [_resource("b", _t1_url(2024, "tbl1_ac_en.csv"))])
    for year in (2022, 2023):
        _mock_package(httpx_mock, "t1_final", year, [])
    # The 2018 rows stand in for 2021's file: same layout, millions of dollars.
    httpx_mock.add_response(url=_t1_url(2021, "table1.csv"), content=_T1_2018)
    httpx_mock.add_response(url=_t1_url(2024, "tbl1_ac_en.csv"), content=_T1_2024)
    result = await client.get_t1_series(
        1, "total income assessed", measure="amount", from_year=2021, to_year=2024
    )
    assert [(r.tax_year, r.value) for r in result.rows] == [
        (2021, 1_463_537_000),
        (2024, 2_023_605_613),
    ]
    assert result.missing_years == [2022, 2023]
    assert result.group == "Canada"
    assert "millions of dollars were converted" in (result.provenance.limits or "")


async def test_get_t1_series_matches_whole_labels_only(httpx_mock):
    _mock_package(httpx_mock, "t1_final", 2024, [_resource("b", _t1_url(2024, "tbl1_ac_en.csv"))])
    httpx_mock.add_response(url=_t1_url(2024, "tbl1_ac_en.csv"), content=_T1_2024)
    with pytest.raises(NotFound, match="Total income"):
        await client.get_t1_series(1, "Total income", from_year=2024)


async def test_get_t1_series_rejects_reversed_years():
    with pytest.raises(InvalidInput, match="from_year"):
        await client.get_t1_series(1, "Total income assessed", from_year=2024, to_year=2018)


# ------------------------------------------------------------------ FSA reads


async def test_get_fsa_table_by_fsa_and_province(httpx_mock):
    _mock_package(httpx_mock, "fsa", 2021, [_resource("a", _fsa_url(2021, "tbl1a-en.csv"))])
    httpx_mock.add_response(url=_fsa_url(2021, "tbl1a-en.csv"), content=_FSA_2021)
    one = await client.get_fsa_table(2021, "1a", fsa=["t5k"])
    assert {r.fsa for r in one.rows} == {"T5K"} and one.total_rows == 4
    alberta = await client.get_fsa_table(2021, "1A", province="48", item="total income")
    assert [(r.fsa, r.value) for r in alberta.rows] == [("T5K", 1_134_003)]


async def test_get_fsa_table_checks_arguments():
    with pytest.raises(InvalidInput, match="forward sortation area"):
        await client.get_fsa_table(2021, "1a", fsa=["12345"])
    with pytest.raises(InvalidInput, match="FSA table"):
        await client.get_fsa_table(2021, "9")
    with pytest.raises(InvalidInput, match="province 'nr'"):
        await client.get_fsa_table(2021, "1a", province="nr")
    with pytest.raises(InvalidInput, match="at most"):
        await client.get_fsa_table(2021, "1a", fsa=["T5K"] * 101)


async def test_get_fsa_series_harmonizes_units(httpx_mock):
    _mock_package(httpx_mock, "fsa", 2019, [_resource("a", _fsa_url(2019, "tbl1a-en.csv"))])
    _mock_package(httpx_mock, "fsa", 2020, [_resource("b", _fsa_url(2020, "tbl1a-en.csv"))])
    _mock_package(httpx_mock, "fsa", 2021, [_resource("c", _fsa_url(2021, "tbl1a-en.csv"))])
    httpx_mock.add_response(url=_fsa_url(2019, "tbl1a-en.csv"), content=_FSA_2019)
    httpx_mock.add_response(url=_fsa_url(2020, "tbl1a-en.csv"), status_code=404, text="gone")
    httpx_mock.add_response(url=_fsa_url(2021, "tbl1a-en.csv"), content=_FSA_2021)
    result = await client.get_fsa_series("t5k", item="Total income", from_year=2019)
    assert [(r.tax_year, r.value) for r in result.rows] == [(2019, 1_199_830), (2021, 1_134_003)]
    assert result.missing_years == [2020]
    assert "dollars were converted" in (result.provenance.limits or "")


async def test_get_fsa_series_wants_one_fsa():
    with pytest.raises(InvalidInput, match="give one FSA"):
        await client.get_fsa_series("Total")
