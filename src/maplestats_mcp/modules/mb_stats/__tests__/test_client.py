"""Manitoba Bureau of Statistics, against files shaped as seen live on 2026-11-24.

The quick-facts CSV keeps unquoted commas in its summaries (rows of 16 to 19
fields) and breaks one Labour Force Survey note across lines; the catalogue lists
one file under several indicators, PDFs beside Excel tables and Statistics Canada
links; retail_mb.xlsx has a title row over a three-row header.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.mb_stats import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

HEADER = (
    "Id,Title,Category,Reference Period,Value,Data Type,Change,chgDirection,chgContext,"
    "powerBI_link,SummaryText,SubCategory,CategoryOrder,SubCategoryOrder,TileOrder,"
    "IsKeyIndicator\n"
)
QUICK_FACTS = HEADER + (
    '16,Population estimate,Population & Community,"July 1, 2026","1,517,379 persons",NO,'
    "+0.2%,Up_green,Quarterly Change,NO,Population estimates, by quarter, from StatCan.,"
    "Population,7,1,1,TRUE\n"
    '3,Persons employed,Employment & Labour Market,October 2026,"752,500 persons",'
    "(seasonally adjusted),+0.1%,Up_green,Month to Month Change,NO,The <b>LFS</b> provides "
    'estimates.<p><br><i><a href=https://www23.statcan.gc.ca/x" target="_blank">Source: '
    "Statistics Canada, Labour Force Survey</a></i>\n"
    "On January 26, 2026, Statistics Canada revised the LFS, as is standard practice,"
    "Labour force survey,5,1,1,TRUE\n"
    "71,Active businesses (with employees),Archives,NO,NO,NO,NO,NO,NO,NO,NO,Archives,9,1,1,FALSE\n"
)
REPORTS = (
    "FileName,Date Released,displayName,Related_indicatorId,ReportType\n"
    'retail_mb.xlsx,2026-11-20,"Retail trade, sales by industry, Manitoba",10,Data Table\n'
    "de_migr-popn-qrt_tb_mb.xlsx,2026-09-23,Manitoba demographic statistics,16,Data Table\n"
    "de_migr-popn-qrt_tb_mb.xlsx,2026-09-23,Manitoba demographic statistics,57,Data Table\n"
    'mbs101_weekly_20261123_w42.pdf,2026-11-23,"MBS Weekly, week #42",31,Bulletin\n'
    "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1710000901,,Population estimates,"
    "16,Related links\n"
)
RETAIL_URL = constants.PUBLICATIONS_URL + "retail_mb.xlsx"


def _retail() -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "retail_mb"
    sheet.append(["Retail trade by industry, Manitoba - Unadjusted", None, None, "September 2026"])
    sheet.append([None, "Sep", "Aug", "Sep"])
    sheet.append([None, "2025", "2026r", "2026p"])
    sheet.append([None, "millions of dollars"])
    sheet.append(["Retail trade", 2309.883, 2598.917, 2430.69])
    sheet.append(["  Motor vehicle and parts dealers", 660.979, 746.854, 643.595])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def bureau(httpx_mock):
    httpx_mock.add_response(
        url=constants.QUICK_FACTS_URL,
        content=QUICK_FACTS.encode(),
        is_reusable=True,
        is_optional=True,
    )
    httpx_mock.add_response(
        url=constants.REPORTS_URL, content=REPORTS.encode(), is_reusable=True, is_optional=True
    )
    httpx_mock.add_response(url=RETAIL_URL, content=_retail(), is_reusable=True, is_optional=True)


def test_quick_facts_mend_split_summaries():
    rows = client.parse_quick_facts(QUICK_FACTS)
    assert [r["id"] for r in rows] == ["16", "3", "71"]
    assert rows[0]["summary"] == "Population estimates, by quarter, from StatCan."
    assert rows[0]["key"] == "TRUE" and rows[0]["subcategory"] == "Population"
    # The broken note joined the record it belongs to; the tail is read from the end.
    assert rows[1]["subcategory"] == "Labour force survey" and rows[1]["key"] == "TRUE"
    assert "revised the LFS" in rows[1]["summary"]


async def test_list_indicators(bureau):
    result = await client.list_indicators()
    population = result.indicators[0]
    assert (population.id, population.value, population.reference_period) == (
        16,
        "1,517,379 persons",
        "July 1, 2026",
    )
    assert population.data_type is None  # "NO" means none
    # The demographic table and the Statistics Canada link.
    assert population.key_indicator and population.files == 2
    employed = result.indicators[1]
    assert employed.summary and "<" not in employed.summary
    archived = result.indicators[2]
    assert archived.value is None and archived.category == "Archives"
    assert result.categories == ["Archives", "Employment & Labour Market", "Population & Community"]
    assert result.provenance.commercial_use == "allowed"
    narrowed = await client.list_indicators(query="employed")
    assert [i.id for i in narrowed.indicators] == [3]


async def test_list_files_merges_indicators_and_filters_by_kind(bureau):
    tables = await client.list_files()
    assert [f.url for f in tables.files] == [
        RETAIL_URL,
        constants.PUBLICATIONS_URL + "de_migr-popn-qrt_tb_mb.xlsx",
    ]
    assert tables.files[1].indicators == [16, 57]
    docs = await client.list_files(kind="document")
    assert docs.files[0].report_type == "Bulletin" and docs.files[0].url.endswith(".pdf")
    links = await client.list_files(kind="link")
    assert links.files[0].url.startswith("https://www150.statcan.gc.ca/")
    by_indicator = await client.list_files(indicator=57, kind="any")
    assert by_indicator.total_files == 1
    page = await client.list_files(kind="any", limit=2)
    assert page.truncated and page.total_files == 4


async def test_read_file_joins_a_three_row_header(bureau):
    result = await client.read_file(url=RETAIL_URL, header_rows=3)
    assert result.header_row == 2
    assert result.header[:3] == ["", "Sep 2025 millions of dollars", "Aug 2026r"]
    assert result.rows[0][:2] == ["Retail trade", "2309.883"]
    assert result.title == "Retail trade, sales by industry, Manitoba"
    filtered = await client.read_file(url=RETAIL_URL, contains="motor")
    assert filtered.total_rows == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/mbs/publications/retail_mb.xlsx",
        "https://www.gov.mb.ca/finance/retail_mb.xlsx",
        "https://www.gov.mb.ca/mbs/publications/weekly.pdf",
    ],
)
async def test_read_file_refuses_other_urls(url):
    with pytest.raises(InvalidInput):
        await client.read_file(url=url)


async def test_read_file_refuses_an_unlisted_file(bureau):
    with pytest.raises(NotFound):
        await client.read_file(url=constants.PUBLICATIONS_URL + "unlisted.xlsx")
    with pytest.raises(InvalidInput):
        await client.read_file(url=RETAIL_URL, sheet="nope")


_OUTAGE_PAGE = "<!DOCTYPE html><html><body><h1>Service unavailable</h1></body></html>"


async def test_a_web_page_in_place_of_a_file_is_an_upstream_error_and_not_cached(httpx_mock):
    # An outage page served with HTTP 200 was cached as the file, then reported as
    # NotFound on every call until the cache expired, after the site had recovered.
    httpx_mock.add_response(url=constants.REPORTS_URL, content=REPORTS.encode(), is_reusable=True)
    httpx_mock.add_response(url=RETAIL_URL, text=_OUTAGE_PAGE)
    with pytest.raises(UpstreamError, match="web page"):
        await client.read_file(url=RETAIL_URL)
    httpx_mock.add_response(url=RETAIL_URL, content=_retail())
    result = await client.read_file(url=RETAIL_URL, header_rows=3)
    assert result.rows[0][:2] == ["Retail trade", "2309.883"]


async def test_a_web_page_in_place_of_the_catalogue_is_not_cached(httpx_mock):
    httpx_mock.add_response(url=constants.REPORTS_URL, text=_OUTAGE_PAGE)
    with pytest.raises(UpstreamError, match="web page"):
        await client.list_files()
    httpx_mock.add_response(url=constants.REPORTS_URL, content=REPORTS.encode())
    assert (await client.list_files()).total_files == 2


async def test_the_web_page_error_is_in_french_with_lang_fr(httpx_mock):
    httpx_mock.add_response(url=constants.REPORTS_URL, text=_OUTAGE_PAGE)
    with pytest.raises(UpstreamError, match="a renvoyé une page Web"):
        await client.list_files(lang="fr")
