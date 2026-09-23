"""Tests for modules/cer/client.py, shaped on live 2026-09-23 files."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.cer import client
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_URL = (
    "https://www.cer-rec.gc.ca/open/energy/throughput-capacity/keystone-throughput-and-capacity.csv"
)
_THROUGHPUT = b"\xef\xbb\xbf" + (
    b"Date,Key Point,Product,Throughput (1000 m3/d),Available Capacity (1000 m3/d)\n"
    b"2025-12-01,Haskett,crude oil-heavy,84.1,93.56\n"
    b"2026-06-01,Haskett,crude oil-heavy,86.23,93.56\n"
    b"2026-06-01,Other,crude oil-light,1.54,93.56\n"
    b"2024-01-01,Haskett,crude oil-heavy,80.0,93.56\n"
)
_FRENCH_URL = "https://www.cer-rec.gc.ca/ouvert/importations-exportations/gnl-par-annee.csv"
_FRENCH = '"Ann\xe9e","Flux ","Terminal"\n"2023","Importation","Queenston"\n'.encode("cp1252")


async def test_query_filters_dates_and_returns_most_recent(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_THROUGHPUT)
    result = await client.query_file(_URL, {"key point": "haskett"}, start="2025-01-01", limit=5)
    assert result.date_column == "Date"
    assert [r["Date"] for r in result.rows] == ["2025-12-01", "2026-06-01"]
    assert result.total_rows == 4
    latest = await client.query_file(_URL, columns=["Date", "Product"], limit=1)
    assert latest.rows == [{"Date": "2026-06-01", "Product": "crude oil-light"}]


async def test_french_file_decodes_cp1252_and_strips_headers(httpx_mock):
    httpx_mock.add_response(url=_FRENCH_URL, content=_FRENCH)
    result = await client.query_file(_FRENCH_URL, {"Flux": "importation"}, start="2023")
    assert result.columns == ["Année", "Flux", "Terminal"]
    assert result.date_column == "Année"
    assert result.rows[0]["Terminal"] == "Queenston"


async def test_rejects_non_cer_urls_and_unknown_columns(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.query_file("https://example.com/data.csv")
    with pytest.raises(InvalidInput):
        await client.query_file("http://www.cer-rec.gc.ca/open/x.csv")
    httpx_mock.add_response(url=_URL, content=_THROUGHPUT)
    with pytest.raises(InvalidInput, match="Unknown column"):
        await client.query_file(_URL, {"Bogus": "x"})
    with pytest.raises(InvalidInput):
        await client.query_file(_URL, start="June 2025")


async def test_html_error_page_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_URL, text="<!DOCTYPE html><html><body>Page</body></html>")
    with pytest.raises(NotFound, match="web page"):
        await client.query_file(_URL)


async def test_list_datasets_keeps_csv_files_in_requested_language(httpx_mock):
    httpx_mock.add_response(
        json={
            "success": True,
            "result": {"count": 1, "results": [{"id": "p1", "title": "LNG Exports"}]},
        }
    )
    httpx_mock.add_response(
        json={
            "success": True,
            "result": {
                "id": "p1",
                "title": "LNG Exports",
                "resources": [
                    {
                        "id": "r1",
                        "name": "annual",
                        "format": "CSV",
                        "url": _URL,
                        "language": ["en"],
                    },
                    {
                        "id": "r2",
                        "name": "annuel",
                        "format": "CSV",
                        "url": _FRENCH_URL,
                        "language": ["fr"],
                    },
                    {
                        "id": "r3",
                        "name": "page",
                        "format": "HTML",
                        "url": "https://x",
                        "language": ["en"],
                    },
                ],
            },
        }
    )
    result = await client.list_datasets("lng")
    assert [f.name for f in result.datasets[0].files] == ["annual"]
