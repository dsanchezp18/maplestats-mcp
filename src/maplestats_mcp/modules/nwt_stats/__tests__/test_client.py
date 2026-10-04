"""Tests for the NWT Bureau of Statistics client against live pages and files.

Saved 2026-10-03 from statsnwt.ca unchanged: the 2021 Census page (items
nested inside items, release dates as headings, "(4 Excel Tables)" notes),
the Business Dynamics page (267 links in quarterly blocks, file names with
spaces and '&'), the Community Data page and Aklavik's page (one profile per
community, link text "Excel"), GDP by industry (.xlsx, a title above years
across columns), land area (.xls) and a two-sheet business workbook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.nwt_stats import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent
_CENSUS = "https://www.statsnwt.ca/census/2021/"
_BUSINESS = "https://www.statsnwt.ca/economy/BusinessDynamics/index.php"
_COMMUNITY = "https://www.statsnwt.ca/community-data/index.html"
_GDP = "https://www.statsnwt.ca/economy/gdp/GDP%20by%20Industry%20(1999-2025).xlsx"
_LAND = (
    "https://www.statsnwt.ca/environment/"
    "Land%20and%20Freshwater%20Area%20by%20Province%20and%20Territory_2023.xls"
)
_WOMEN = (
    "https://www.statsnwt.ca/economy/BusinessDynamics/"
    "Women%20&%20Indigenous%20Owned%20Businesses_Q1_2025.xlsx"
)


def _text(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


def test_census_page_titles_headings_and_nested_items():
    files = client.parse_page(_text("census_2021.html"), _CENSUS, "census-2021")
    assert len(files) == 27
    first = files[0]
    assert first.title == "Population Counts, by Province and Territory 1996-2021"
    assert first.section == "February 9, 2022"
    # The nested item's text is not glued to its parent's, and "(Excel)" alone adds nothing.
    assert first.context is None
    income = next(f for f in files if f.title == "NWT Income")
    assert income.context == "NWT Income (4 Excel Tables)"
    assert income.url == "https://www.statsnwt.ca/census/2021/NWT%20Income.xlsx"
    assert any(f.format == "xls" for f in files)


def test_business_page_encodes_file_names_and_keeps_quarters():
    files = client.parse_page(_text("business_dynamics.html"), _BUSINESS, "business-dynamics")
    assert len(files) > 250
    assert files[0].url == _WOMEN
    table1 = next(f for f in files if f.url.endswith("Table%201_Q1_2026.xlsx"))
    assert table1.section == "Q1 2026 Business Conditions"
    assert table1.title == "Expectations over the next three months"
    assert table1.context == "Table 1 - Expectations over the next three months"


def test_community_profiles_are_one_page_deeper():
    subpages = client.subpage_links(
        _text("community_data.html"), _COMMUNITY, constants.SUBPAGE_PREFIXES["community-data"]
    )
    assert len(subpages) == 33
    assert "https://www.statsnwt.ca/community-data/infrastructure/Lutsel'Ke.html" in subpages
    html = _text("community_aklavik.html")
    [profile] = client.parse_page(html, subpages[0], "community-data", client.page_name(html))
    assert profile.title == "Statistical Profile"
    assert profile.section == "Aklavik > Profiles"
    assert profile.context is None
    assert profile.url == "https://www.statsnwt.ca/community-data/Profile-Excel/Aklavik_2024.xlsx"


async def test_list_without_topic_makes_no_request():
    result = await client.list_files()
    assert result.files == [] and len(result.topics) == len(constants.TOPICS)
    assert "Northwest Territories" in result.licence


async def test_list_topic_pages_and_follows_community_pages(httpx_mock):
    community = _text("community_data.html")
    httpx_mock.add_response(url=_COMMUNITY, text=community)
    aklavik = _text("community_aklavik.html")
    subpages = client.subpage_links(
        community, _COMMUNITY, constants.SUBPAGE_PREFIXES["community-data"]
    )
    for url in subpages:
        httpx_mock.add_response(url=url, text=aklavik)
    result = await client.list_files(topic="community-data", limit=5)
    # The summary file on the index page plus one Aklavik profile: every subpage here
    # is the Aklavik fixture, and a file already listed is not repeated.
    assert result.total_files == 2 and not result.truncated
    assert result.files[1].section == "Aklavik > Profiles"


async def test_search_matches_every_word_across_title_heading_and_topic(httpx_mock):
    httpx_mock.add_response(url=_CENSUS, text=_text("census_2021.html"))
    result = await client.search_files("2021 census income", topic="census-2021")
    titles = [f.title for f in result.files]
    assert "NWT Income" in titles and "Median Income by Province and Territory" in titles
    assert all("income" in (f.title + (f.context or "")).lower() for f in result.files)


async def test_search_skips_a_failing_page_and_says_so(httpx_mock):
    for topic, (path, _, _) in constants.TOPICS.items():
        url = constants.SITE + path
        if topic == "census-2021":
            httpx_mock.add_response(url=url, text=_text("census_2021.html"))
        elif topic == "community-data":
            httpx_mock.add_response(url=url, text="<html><body></body></html>")
        else:
            httpx_mock.add_response(url=url, status_code=404, is_reusable=True)
    result = await client.search_files("mother tongue")
    assert "Mother Tongue" in [f.title for f in result.files]
    assert {f.topic for f in result.files} == {"census-2021"}
    assert result.provenance.limits and "did not answer" in result.provenance.limits


async def test_unknown_topic_and_empty_query_are_refused():
    with pytest.raises(InvalidInput):
        await client.list_files(topic="weather")
    with pytest.raises(InvalidInput):
        await client.search_files("  ")


def test_only_statsnwt_excel_links_are_read():
    assert (
        client.normalize_url("http://statsnwt.ca/economy/gdp/GDP by Industry (1999-2025).xlsx")
        == _GDP
    )
    assert client.normalize_url(_GDP) == _GDP
    with pytest.raises(InvalidInput):
        client.normalize_url("https://example.com/a.xlsx")


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
        await client.read_file("https://www.statsnwt.ca/economy/gdp/May2026_GDP.pdf")
