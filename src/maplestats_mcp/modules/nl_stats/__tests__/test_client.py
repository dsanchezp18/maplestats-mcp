"""Tests for the NL Statistics Agency client against real payloads saved 2026-09-30.

topic_population.html is the live population topic page unchanged;
population_quarterly.xlsx and migration_quarterly.xls are the live files
(an .xlsx and a legacy .xls).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.nl_stats import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent
_XLSX = (
    "https://www.stats.gov.nl.ca/Statistics/Topics/population/excel/"
    "Population_CanProvTerr_Quarterly_1971-2026.xlsx"
)
_XLS = (
    "https://www.stats.gov.nl.ca/Statistics/Topics/population/Excel/"
    "Interprovincial_Migration_NL_Quarterly_1961-2026.xls"
)


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _page_url(topic: str) -> str:
    return constants.TOPIC_PAGE_URL.format(topic=topic)


def test_topic_page_parsing_titles_sections_and_nesting():
    files = client.parse_topic_page(_bytes("topic_population.html").decode("utf-8"), "population")
    assert len(files) >= 10
    quarterly = files[0]
    assert quarterly.title == "Quarterly Population - Canada, Provinces and Territories; 1971-2026"
    assert quarterly.section == "Quarterly Data"
    assert quarterly.format == "xlsx" and quarterly.url == _XLSX
    assert any(f.format == "xls" for f in files)
    nested = [f for f in files if f.title.startswith("Annual Population by Age Group and Gender")]
    assert any("Total - Gender" in f.title for f in nested)
    assert all(f.url.startswith("https://www.stats.gov.nl.ca/Statistics/Topics/") for f in files)


async def test_list_files_filters_by_topic_and_query(httpx_mock):
    httpx_mock.add_response(url=_page_url("population"), content=_bytes("topic_population.html"))
    result = await client.list_files(topic="population", query="quarterly migration")
    assert [f.format for f in result.files] == ["xls"]
    assert result.total_files == 1 and not result.truncated
    assert {t.topic for t in result.topics} == set(constants.TOPICS)


async def test_list_files_rejects_unknown_topic():
    with pytest.raises(InvalidInput):
        await client.list_files(topic="weather")


def test_only_agency_excel_links_are_read():
    for bad in (
        "http://www.stats.gov.nl.ca/Statistics/Topics/x/a.xlsx",
        "https://example.com/Statistics/Topics/x/a.xlsx",
        "https://www.stats.gov.nl.ca/Statistics/Topics/x/a.pdf",
        "https://www.stats.gov.nl.ca/other/a.xlsx",
    ):
        with pytest.raises(InvalidInput):
            client.check_file_url(bad)
    client.check_file_url(_XLSX)


async def test_read_xlsx_guesses_header_and_filters_rows(httpx_mock):
    httpx_mock.add_response(url=_XLSX, content=_bytes("population_quarterly.xlsx"))
    data = await client.read_file(_XLSX, contains="1971", limit=5)
    assert data.sheet == "Quarterly" and data.format == "xlsx"
    assert data.header[:4] == ["Year", "Month", "Canada", "N.L."]
    assert data.header_row == 3
    assert data.rows[0][:4] == ["1971", "7", "21962032", "530854"]
    assert data.total_rows >= 2


async def test_read_legacy_xls(httpx_mock):
    httpx_mock.add_response(url=_XLS, content=_bytes("migration_quarterly.xls"))
    data = await client.read_file(_XLS, limit=3)
    assert data.format == "xls"
    assert data.sheets and data.rows
    assert data.header_row is not None


async def test_unknown_sheet_and_paging(httpx_mock):
    httpx_mock.add_response(url=_XLSX, content=_bytes("population_quarterly.xlsx"))
    with pytest.raises(InvalidInput, match="sheets are"):
        await client.read_file(_XLSX, sheet="Nope")
    first = await client.read_file(_XLSX, limit=2)
    second = await client.read_file(_XLSX, limit=2, offset=2)
    assert first.truncated and first.rows != second.rows


async def test_html_error_page_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_XLSX, content=b"<!DOCTYPE html><html>Error</html>")
    with pytest.raises(NotFound):
        await client.read_file(_XLSX)
