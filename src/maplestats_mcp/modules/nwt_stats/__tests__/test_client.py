"""Tests for the NWT Bureau of Statistics client against live pages and files.

Pages saved 2026-10-26 from the relaunched statsnwt.ca unchanged: the census
page (six census years in collapsible blocks, release dates as headings,
"(Excel)" and "(4 Excel Tables)" in link texts, every file linked on the
bearnet.gov.nt.ca staging host) and the GDP page (files under
/sites/default/files/documents/ and an export of the table shown on the
page). Files saved 2026-10-03: GDP by industry (.xlsx, a title above years
across columns), land area (.xls) and a two-sheet business workbook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.nwt_stats import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent
_CENSUS = "https://www.statsnwt.ca/en/Canadian-Census"
_GDP_PAGE = "https://www.statsnwt.ca/en/economy/gdp"
_DOCS = "https://www.statsnwt.ca/sites/default/files/documents/"
_GDP = _DOCS + "GDP%20by%20Industry%20(1999-2025).xlsx"
_LAND = _DOCS + "Land%20and%20Freshwater%20Area%20by%20Province%20and%20Territory_2023.xls"
_WOMEN = _DOCS + "Women%20&%20Indigenous%20Owned%20Businesses_Q1_2025.xlsx"
_EXPORT = "https://www.statsnwt.ca/en/download-xlsx/807/paragraph/117231"


def _text(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


def test_census_page_years_headings_and_staging_links():
    files = client.parse_page(_text("census.html"), _CENSUS, "census")
    assert len(files) == 94
    first = files[0]
    # "(Excel)" is dropped from the title; the link's staging host is rewritten.
    assert first.title == "Population Counts, by Province and Territory 1996 - 2021"
    assert first.section == "2021 Census > February 9, 2022: Population and Dwelling Counts"
    assert first.context is None
    assert first.url == _DOCS + "Prov-TerrCounts_1996-2021.xlsx"
    assert all(f.url.startswith(_DOCS) for f in files)
    years = {f.section.split(" > ")[0] for f in files if f.section}
    assert years == {f"{y} Census" for y in (1996, 2001, 2006, 2011, 2016, 2021)}
    income = next(f for f in files if f.title == "NWT Income (4 Excel Tables)")
    assert income.url == _DOCS + "NWT%20Income.xlsx"
    assert sum(f.format == "xls" for f in files) == 2


def test_gdp_page_files_and_table_export():
    files = client.parse_page(_text("gdp.html"), _GDP_PAGE, "gdp")
    assert len(files) == 6
    export = files[0]
    assert export.url == _EXPORT and export.format == "xlsx"
    assert export.title == (
        "NWT Gross Domestic Product at Basic Prices (Millions of Chained (2017) Dollars)"
        " - table on the page"
    )
    industry = files[1]
    assert industry.url == _GDP
    assert industry.title == "NWT GDP by Industry (Chained) (1999 - 2025)"
    assert industry.section == "Downloadable Excel Tables > Publications"


async def test_list_without_topic_makes_no_request():
    result = await client.list_files()
    assert result.files == [] and len(result.topics) == len(constants.TOPICS)
    assert "Northwest Territories" in result.licence


async def test_list_topic_reads_its_page(httpx_mock):
    httpx_mock.add_response(url=_CENSUS, text=_text("census.html"))
    result = await client.list_files(topic="census", limit=5)
    assert result.total_files == 94 and result.truncated
    assert result.provenance.url == _CENSUS


async def test_search_matches_every_word_across_title_heading_and_topic(httpx_mock):
    httpx_mock.add_response(url=_CENSUS, text=_text("census.html"))
    result = await client.search_files("2021 census income", topic="census")
    titles = [f.title for f in result.files]
    assert "NWT Income (4 Excel Tables)" in titles
    assert all("income" in (f.title + (f.section or "")).lower() for f in result.files)


async def test_search_skips_a_failing_page_and_says_so(httpx_mock):
    for topic, (path, _, _) in constants.TOPICS.items():
        url = constants.SITE + path
        if topic == "census":
            httpx_mock.add_response(url=url, text=_text("census.html"))
        else:
            httpx_mock.add_response(url=url, status_code=404, is_reusable=True)
    result = await client.search_files("mother tongue")
    assert "Mother Tongue (2 Excel Tables)" in [f.title for f in result.files]
    assert {f.topic for f in result.files} == {"census"}
    assert result.provenance.limits and "did not answer" in result.provenance.limits


async def test_unknown_topic_and_empty_query_are_refused():
    with pytest.raises(InvalidInput):
        await client.list_files(topic="weather")
    with pytest.raises(InvalidInput):
        await client.search_files("  ")


def test_only_statsnwt_excel_links_are_read():
    assert (
        client.normalize_url(
            "http://statsnwt.ca/sites/default/files/documents/GDP by Industry (1999-2025).xlsx"
        )
        == _GDP
    )
    assert client.normalize_url(_GDP) == _GDP
    staging = "https://bearnet.gov.nt.ca/t2/stats/sites/default/files/documents/NWT%20Income.xlsx"
    assert client.normalize_url(staging) == _DOCS + "NWT%20Income.xlsx"
    with pytest.raises(InvalidInput):
        client.normalize_url("https://bearnet.gov.nt.ca/other/a.xlsx")
    with pytest.raises(InvalidInput):
        client.normalize_url("https://example.com/a.xlsx")


async def test_read_a_table_export(httpx_mock):
    httpx_mock.add_response(url=_EXPORT, content=_bytes("gdp_by_industry.xlsx"))
    data = await client.read_file(_EXPORT, contains="All industries", limit=1)
    assert data.format == "xlsx" and data.rows


async def test_read_xlsx_years_across_columns(httpx_mock):
    httpx_mock.add_response(url=_GDP, content=_bytes("gdp_by_industry.xlsx"))
    data = await client.read_file(_GDP, contains="All industries", limit=1)
    assert data.format == "xlsx" and data.sheet_chosen_by == "only"
    assert data.header_row == 5 and data.all_columns[:3] == ["column_1", "1999", "2000"]
    assert data.rows[0]["column_1"] == "All industries (NAICS 2017)"
    assert data.rows[0]["1999"] == "3133.3"


async def test_read_legacy_xls_with_filter(httpx_mock):
    httpx_mock.add_response(url=_LAND, content=_bytes("land_area.xls"))
    data = await client.read_file(_LAND, filters={"column_1": "canada"})
    assert data.format == "xls" and data.total_rows == 1
    assert data.rows[0]["Total Area"] == "9984670"


async def test_two_comparable_sheets_need_a_choice(httpx_mock):
    httpx_mock.add_response(url=_WOMEN, content=_bytes("women_indigenous_businesses.xlsx"))
    listing = await client.read_file(_WOMEN)
    assert listing.sheet is None and listing.rows == []
    assert [s.name for s in listing.sheets] == ["Table 1", "Table 2"]
    data = await client.read_file(_WOMEN, sheet="table 2", limit=2)
    assert data.sheet == "Table 2" and data.rows


async def test_a_web_page_instead_of_a_file_is_an_error(httpx_mock):
    httpx_mock.add_response(url=_GDP, text="<!DOCTYPE html><html><title>Error 404</title></html>")
    with pytest.raises(Exception, match="web page"):
        await client.read_file(_GDP)


async def test_missing_file_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_GDP, status_code=404)
    with pytest.raises(NotFound):
        await client.read_file(_GDP)


async def test_bad_paging_and_non_excel_links_are_refused():
    with pytest.raises(InvalidInput):
        await client.read_file(_GDP, limit=0)
    with pytest.raises(InvalidInput):
        await client.read_file(_DOCS + "May2026_GDP%28CORRECTED%29.pdf")


async def test_french_errors():
    with pytest.raises(InvalidInput, match="Entrée invalide") as caught:
        await client.list_files(topic="weather", lang="fr")
    assert "topic doit être l'un de" in str(caught.value)
    with pytest.raises(InvalidInput, match="doit être un lien sur www.statsnwt.ca"):
        client.normalize_url("https://example.com/a.xlsx", lang="fr")


async def test_french_provenance_and_licence(httpx_mock):
    httpx_mock.add_response(url=_GDP, content=_bytes("gdp_by_industry.xlsx"))
    data = await client.read_file(_GDP, contains="All industries", limit=1, lang="fr")
    assert "Licence du gouvernement ouvert – Territoires du Nord-Ouest" in data.licence
    assert data.provenance.licence == data.licence
    assert "Bureau de la statistique des Territoires du Nord-Ouest" in (
        data.provenance.freshness or ""
    )
    assert (data.provenance.coverage or "").startswith("Feuille ")
    topics = await client.list_files(lang="fr")
    assert topics.topics[0].title == "Produit intérieur brut"
    assert (topics.provenance.coverage or "").startswith("38 sujets")


async def test_english_provenance_unchanged(httpx_mock):
    httpx_mock.add_response(url=_GDP, content=_bytes("gdp_by_industry.xlsx"))
    data = await client.read_file(_GDP, contains="All industries", limit=1)
    assert data.provenance.freshness == (
        "As published by the NWT Bureau of Statistics; files cached up to 6 hours."
    )
    assert data.licence.startswith("Two statements apply. (1) Open Government Licence - ")
