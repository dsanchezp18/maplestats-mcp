"""Tests for the NL Statistics Agency client against real payloads saved 2026-09-30.

topic_population.html is the live population topic page unchanged;
population_quarterly.xlsx and migration_quarterly.xls are the live files
(an .xlsx and a legacy .xls). lfc_agesex_monthly.xlsx is the live labour
"Current Month" file saved 2026-10-03 (one sheet per month, Jan2026 to Aug2026).
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
    with pytest.raises(InvalidInput):
        await client.list_files(offset=-1)


async def test_list_files_pages_with_limit_and_offset(httpx_mock):
    httpx_mock.add_response(
        url=_page_url("population"), content=_bytes("topic_population.html"), is_reusable=True
    )
    everything = await client.list_files(topic="population", limit=constants.FILES_LIMIT_MAX)
    total = everything.total_files
    assert total >= 10 and not everything.truncated and everything.offset == 0
    first = await client.list_files(topic="population", limit=4)
    assert len(first.files) == 4 and first.truncated and first.total_files == total
    assert first.provenance.limits is not None and "offset=4" in first.provenance.limits
    second = await client.list_files(topic="population", limit=4, offset=4)
    assert second.offset == 4
    assert [f.url for f in first.files + second.files] == [f.url for f in everything.files[:8]]
    last = await client.list_files(topic="population", limit=4, offset=total - 1)
    assert len(last.files) == 1 and not last.truncated
    past = await client.list_files(topic="population", offset=total + 5)
    assert past.files == [] and past.provenance.limits is not None


async def test_list_files_default_is_a_compact_page(httpx_mock):
    # 15 topic pages with the same body: about 15 x the population files.
    httpx_mock.add_response(content=_bytes("topic_population.html"), is_reusable=True)
    result = await client.list_files()
    assert len(result.files) == constants.FILES_LIMIT_DEFAULT
    assert result.truncated and result.total_files > constants.FILES_LIMIT_DEFAULT


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


_MONTHLY = "https://www.stats.gov.nl.ca/Statistics/Topics/labour/Excel/LFC_AgeSex_Mthly_NL.xlsx"


def test_sheet_month_names():
    assert client.sheet_month("Aug2026") == (2026, 8)
    assert client.sheet_month("September 2025") == (2025, 9)
    assert client.sheet_month("2026-Jan") == (2026, 1)
    assert client.sheet_month("Dec 25") == (2025, 12)
    assert client.sheet_month("Quarterly") is None
    assert client.sheet_month("Notes2026") is None
    assert client.default_sheet(["Quarterly", "Annual"]) == ("Quarterly", "first")
    assert client.default_sheet(["Notes", "Dec2025", "Jan2026"]) == ("Jan2026", "newest_month")


async def test_month_per_sheet_workbook_reads_newest_month(httpx_mock):
    # lfc_agesex_monthly.xlsx is the live "Current Month" file of 2026-10-03:
    # sheets Jan2026 .. Aug2026 in calendar order, so sheets[0] was the oldest.
    httpx_mock.add_response(url=_MONTHLY, content=_bytes("lfc_agesex_monthly.xlsx"))
    data = await client.read_file(_MONTHLY, limit=3)
    assert data.sheets[0].name == "Jan2026"
    assert data.sheet == "Aug2026" and data.sheet_chosen_by == "newest_month"
    assert data.provenance.limits and "newest ('Aug2026')" in data.provenance.limits
    assert "8 sheets exist" in data.provenance.limits
    asked = await client.read_file(_MONTHLY, sheet="jan2026", limit=1)
    assert asked.sheet == "Jan2026" and asked.sheet_chosen_by == "request"


async def test_multi_row_header_is_joined(httpx_mock):
    httpx_mock.add_response(url=_MONTHLY, content=_bytes("lfc_agesex_monthly.xlsx"))
    single = await client.read_file(_MONTHLY, limit=2)
    # Live layout: row 5 holds the group labels, row 6 the sub-labels, row 7 units.
    assert single.header_row == 5 and single.header[3] == "Employment"
    assert single.rows[0][3:6] == ["Total", "Full-Time", "Part-Time"]
    joined = await client.read_file(_MONTHLY, header_rows=3, limit=2)
    assert joined.header_rows == 3
    assert joined.header[1] == "Population 15+ Thousands"
    assert joined.header[3:6] == ["Employment Total", "Full-Time", "Part-Time"]
    assert joined.rows[0][0] == "Total-Gender"
    explicit = await client.read_file(_MONTHLY, header_row=6, limit=1)
    assert explicit.header_row == 6 and explicit.header[3] == "Total"


async def test_header_row_beyond_sheet_and_bad_header_rows(httpx_mock):
    httpx_mock.add_response(url=_MONTHLY, content=_bytes("lfc_agesex_monthly.xlsx"))
    data = await client.read_file(_MONTHLY, limit=1)
    rows = next(s.rows for s in data.sheets if s.name == data.sheet)
    with pytest.raises(InvalidInput, match=f"has only {rows} rows"):
        await client.read_file(_MONTHLY, header_row=9999)
    with pytest.raises(InvalidInput, match="header_rows"):
        await client.read_file(_MONTHLY, header_rows=9)
    with pytest.raises(InvalidInput, match="1-based"):
        await client.read_file(_MONTHLY, header_row=0)


async def test_html_error_page_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_XLSX, content=b"<!DOCTYPE html><html>Error</html>")
    with pytest.raises(NotFound):
        await client.read_file(_XLSX)


async def test_french_errors(httpx_mock):
    with pytest.raises(InvalidInput, match="Entrée invalide") as caught:
        await client.list_files(topic="weather", lang="fr")
    assert "topic doit être l'un de" in str(caught.value)
    httpx_mock.add_response(url=_XLSX, content=b"<!DOCTYPE html><html>Error</html>")
    with pytest.raises(NotFound, match="page Web, pas un fichier Excel"):
        await client.read_file(_XLSX, lang="fr")


async def test_french_provenance_and_english_unchanged(httpx_mock):
    httpx_mock.add_response(
        url=_XLSX, content=_bytes("population_quarterly.xlsx"), is_reusable=True
    )
    french = await client.read_file(_XLSX, limit=2, lang="fr")
    assert "Terre-Neuve-et-Labrador" in (french.provenance.licence or "")
    assert "Statistique Canada" in (french.provenance.licence or "")
    assert (french.provenance.freshness or "").startswith("Tel que publié")
    assert (french.provenance.limits or "").startswith("les feuilles sont lues")
    english = await client.read_file(_XLSX, limit=2)
    assert english.provenance.freshness == "As published by the NL Statistics Agency."
    assert english.provenance.coverage == "Sheet 'Quarterly' of " + str(len(english.sheets)) + "."
    assert "Statistics Canada" in (english.provenance.licence or "")
