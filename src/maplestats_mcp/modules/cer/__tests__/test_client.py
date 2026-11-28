"""Tests for modules/cer/client.py, shaped on live 2026-09-23 files."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.cer import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


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


async def test_year_and_month_end_cover_the_whole_period(httpx_mock):
    # Live 2026-10-03: start="2024", end="2024" on Keystone kept only the
    # 2024-01-01 rows, because end="2024" meant January 1st.
    body = b"Date,Key Point,Throughput\n" + b"".join(
        f"2024-{m:02d}-01,Haskett,{m}\n".encode() for m in range(1, 13)
    )
    httpx_mock.add_response(url=_URL, content=body, is_reusable=True)
    year = await client.query_file(_URL, start="2024", end="2024", limit=100)
    assert year.matching_rows == 12
    month = await client.query_file(_URL, start="2024-03", end="2024-04", limit=100)
    assert [r["Date"] for r in month.rows] == ["2024-03-01", "2024-04-01"]


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


async def test_french_errors_are_french(httpx_mock):
    with pytest.raises(InvalidInput, match="Entrée invalide : cer : url doit être"):
        await client.query_file("https://example.com/data.csv", lang="fr")
    with pytest.raises(InvalidInput, match="AAAA-MM-JJ"):
        await client.query_file(_URL, start="June 2025", lang="fr")
    httpx_mock.add_response(url=_URL, content=_THROUGHPUT)
    with pytest.raises(InvalidInput, match="colonne inconnue 'Bogus'"):
        await client.query_file(_URL, {"Bogus": "x"}, lang="fr")


async def test_french_html_page_is_french_not_found(httpx_mock):
    httpx_mock.add_response(url=_URL, text="<!DOCTYPE html><html><body>Page</body></html>")
    with pytest.raises(NotFound, match="aucun fichier CSV"):
        await client.query_file(_URL, lang="fr")


async def test_french_provenance_and_english_file_note(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_THROUGHPUT)
    result = await client.query_file(_URL, limit=2, lang="fr")
    assert result.provenance.coverage == "2 lignes correspondantes sur 4"
    assert result.provenance.limits is not None
    assert "version anglaise :" in result.provenance.limits
    english = await client.query_file(_URL, limit=2)
    assert english.provenance.coverage == "2 of 4 matching rows"
    assert english.provenance.limits is None


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


_YEARLY = b"Year,Terminal,Volume\n2023,Queenston,5\n2024,Queenston,7\n2025,Queenston,9\n"


async def test_year_only_rows_are_kept_when_their_year_overlaps_the_bounds(httpx_mock):
    # A year-only value was read as January 1st, so start="2024-06" dropped every 2024 row
    # of a file whose only date column is a year (and start="2024-01-15" did the same).
    httpx_mock.add_response(url=_URL, content=_YEARLY, is_reusable=True)
    mid_year = await client.query_file(_URL, start="2024-06", end="2024-12")
    assert [r["Year"] for r in mid_year.rows] == ["2024"]
    after = await client.query_file(_URL, start="2024-06-15")
    assert [r["Year"] for r in after.rows] == ["2024", "2025"]
    before = await client.query_file(_URL, end="2024-03")
    assert [r["Year"] for r in before.rows] == ["2023", "2024"]
    # A year that ends before the start is still out.
    later = await client.query_file(_URL, start="2025-01")
    assert [r["Year"] for r in later.rows] == ["2025"]


async def test_month_rows_overlap_a_day_bound(httpx_mock):
    body = b"Date,Volume\n2024-05,1\n2024-06,2\n2024-07,3\n"
    httpx_mock.add_response(url=_URL, content=body)
    result = await client.query_file(_URL, start="2024-06-15", end="2024-06-20")
    assert [r["Date"] for r in result.rows] == ["2024-06"]


_ODD_DATES = (
    b"Date,Volume\n"
    b"2024-Q1,1\n"
    b"Q2 2024,2\n"
    b"01/31/2024,3\n"
    b"31/01/2024,4\n"
    b"07/08/2024,5\n"
    b"2024.09.10,6\n"
    b"soon,7\n"
    b",8\n"
)


async def test_common_date_forms_are_read_and_the_rest_is_counted(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_ODD_DATES, is_reusable=True)
    result = await client.query_file(_URL, start="2024-02", end="2024-12")
    # Q1 and Q2 overlap the range; both January dates are before it; 07/08/2024 could be
    # July 8th or August 7th, so it is not guessed.
    assert [r["Volume"] for r in result.rows] == ["1", "2", "6"]
    assert result.matching_rows == 3
    assert "3 rows passing the filters have a date" in (result.provenance.limits or "")
    assert "'07/08/2024'" in (result.provenance.limits or "")
    assert "left out of the start/end range" in (result.provenance.limits or "")

    french = await client.query_file(_URL, start="2024-02", end="2024-12", lang="fr")
    assert "3 lignes retenues par les filtres ont une date" in (french.provenance.limits or "")


async def test_unreadable_dates_are_counted_when_there_is_no_range(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_ODD_DATES)
    result = await client.query_file(_URL, limit=100)
    # They sort before the oldest dated row, as before, and the note says so.
    assert [r["Volume"] for r in result.rows] == ["5", "7", "8", "1", "3", "4", "2", "6"]
    assert "sort before the oldest dated row" in (result.provenance.limits or "")


async def test_a_clean_date_column_adds_no_note(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_THROUGHPUT)
    result = await client.query_file(_URL, start="2025-01-01")
    assert result.provenance.limits is None
