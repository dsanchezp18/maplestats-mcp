"""Tests for the Saskatchewan Bureau of Statistics client.

Product payloads follow the Publications Centre's /api/v1/products/<id> answers read
on 2026-11-24 (product 86383, Provincial Economic Accounts): a "PDF " type with a
trailing space, "Excel" and "Microsoft Excel" types, formatPublicationDate often null.
"""

from __future__ import annotations

import io
import re

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.sk_stats import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_PRODUCT = re.compile(r".*/api/v1/products/\d+$")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _format(fid: int, kind: str, description: str, posted: str, **extra: object) -> dict:
    return {
        "productFormatId": fid,
        "productFormatMediumType": "DIGITAL",
        "productFormatType": kind,
        "description": description,
        "formatPublicationDate": None,
        "activeTimestamp": f"{posted}T17:00:00Z",
        "inactiveTimestamp": None,
        "pageCount": None,
        **extra,
    }


ACCOUNTS = {
    "productId": 86383,
    "name": "Provincial Economic Accounts",
    "productFormats": [
        _format(99993, "PDF ", "SPEA Jan 2018", "2017-07-17", pageCount=89),
        _format(142560, "Microsoft Excel", "SPEA 2022 Edition", "2024-01-11"),
        _format(153159, "Microsoft Excel", "SPEA Tables", "2026-01-19"),
        _format(1, "Microsoft Excel", "Withdrawn", "2020-01-01", inactiveTimestamp="2021"),
        _format(2, "Printed Copy", "Print", "2020-01-01", productFormatMediumType="PRINT"),
    ],
}


def _workbook() -> bytes:
    book = Workbook()
    book.remove(book.worksheets[0])
    index = book.create_sheet("index")
    index.append(["Saskatchewan Provincial Economic Accounts"])
    table = book.create_sheet("1.1")
    table.append(["Table 1.1 Gross Domestic Product, Income Based"])
    table.append(["", "2023", "2024", "2025"])
    table.append(["Compensation of Employees", 36071, 38162, 40332])
    table.append(["Per cent Change", "", 5.8, 5.7])
    for _ in range(40):
        table.append(["filler", 1, 2, 3])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _serve_products(httpx_mock, accounts: dict = ACCOUNTS) -> None:
    def answer(request):
        import httpx

        pid = int(str(request.url).rsplit("/", 1)[1])
        payload = accounts if pid == 86383 else {"productId": pid, "productFormats": []}
        return httpx.Response(200, json=payload)

    httpx_mock.add_callback(answer, url=_PRODUCT, is_reusable=True)


def test_entries_keep_live_digital_files_newest_first():
    files = client.entries("economic_accounts", ACCOUNTS)
    assert [f.format_id for f in files] == [153159, 142560, 99993]
    assert [f.kind for f in files] == ["data_table", "data_table", "document"]
    assert files[2].format == "PDF"
    assert files[2].pages == 89
    assert files[0].url == (
        "https://publications.saskatchewan.ca/api/v1/products/86383/formats/153159/download"
    )


async def test_list_files_defaults_to_excel_across_every_product(httpx_mock):
    _serve_products(httpx_mock)
    result = await client.list_files()
    assert [f.format_id for f in result.files] == [153159, 142560]
    assert {p.product for p in result.products} == set(constants.PRODUCTS)
    assert len(httpx_mock.get_requests()) == len(constants.PRODUCTS)
    assert result.provenance.commercial_use == "not_allowed"
    assert "Crown copyright" in result.licence


async def test_list_files_filters_by_product_query_and_kind(httpx_mock):
    _serve_products(httpx_mock)
    result = await client.list_files(product="economic_accounts", query="spea 2018", kind="any")
    assert [f.format_id for f in result.files] == [99993]
    assert len(httpx_mock.get_requests()) == 1


async def test_list_files_pages(httpx_mock):
    _serve_products(httpx_mock)
    result = await client.list_files(product="economic_accounts", limit=1)
    assert result.total_files == 2
    assert result.truncated
    assert "offset=1" in (result.provenance.limits or "")


async def test_list_files_rejects_a_bad_limit():
    with pytest.raises(InvalidInput, match="limit"):
        await client.list_files(limit=0)


async def test_read_file_lists_sheets_then_reads_one(httpx_mock):
    _serve_products(httpx_mock)
    httpx_mock.add_response(
        url=re.compile(r".*/formats/153159/download$"), content=_workbook(), is_reusable=True
    )
    listing = await client.read_file(153159)
    assert [s.name for s in listing.sheets] == ["index", "1.1"]
    rows = await client.read_file(153159, sheet="1.1", contains="compensation")
    assert rows.sheet == "1.1"
    assert rows.header_row == 2
    assert rows.rows[0]["2025"] == "40332"
    assert rows.title == "SPEA Tables"


async def test_read_file_refuses_a_pdf(httpx_mock):
    _serve_products(httpx_mock)
    with pytest.raises(InvalidInput, match="only Excel files"):
        await client.read_file(99993)


async def test_read_file_names_an_unknown_id(httpx_mock):
    _serve_products(httpx_mock)
    with pytest.raises(NotFound, match="sk_stats_list_files"):
        await client.read_file(424242)


_OUTAGE_PAGE = "<!DOCTYPE html><html><body><h1>Service unavailable</h1></body></html>"


async def test_a_web_page_in_place_of_the_file_is_refused_and_not_cached(httpx_mock):
    _serve_products(httpx_mock)
    download = re.compile(r".*/formats/153159/download$")
    httpx_mock.add_response(url=download, text=_OUTAGE_PAGE)
    with pytest.raises(UpstreamError, match="web page"):
        await client.read_file(153159)
    # The portal recovers: the file is downloaded again, not the cached page.
    httpx_mock.add_response(url=download, content=_workbook())
    listing = await client.read_file(153159)
    assert [s.name for s in listing.sheets] == ["index", "1.1"]


async def test_a_csv_in_place_of_the_workbook_is_refused_and_not_cached(httpx_mock):
    _serve_products(httpx_mock)
    download = re.compile(r".*/formats/153159/download$")
    httpx_mock.add_response(url=download, content=b"year,value\n2024,1\n2025,2\n")
    with pytest.raises(UpstreamError, match="did not return an Excel workbook"):
        await client.read_file(153159, lang="en")
    httpx_mock.add_response(url=download, content=_workbook())
    assert (await client.read_file(153159)).sheets


async def test_the_web_page_error_is_in_french_with_lang_fr(httpx_mock):
    _serve_products(httpx_mock)
    httpx_mock.add_response(url=re.compile(r".*/formats/153159/download$"), text=_OUTAGE_PAGE)
    with pytest.raises(UpstreamError, match="n'est pas un classeur Excel lisible"):
        await client.read_file(153159, lang="fr")
