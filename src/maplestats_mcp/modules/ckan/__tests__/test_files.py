"""Tests for the CKAN file reader (ckan_describe_resource / ckan_read_resource).

Payload shapes follow what the portals answered on 2026-10-02: federal
resources with a relative `/data/dataset/<id>/resource/<id>/download/<name>`
URL that redirects to a signed Azure blob, Ontario files on files.ontario.ca,
BC's numeric licence ids ("22" is Access Only), Toronto's `notspecified`
licence, a CSV whose portal format says XLS, a "CSV" that is an HTML error
page, and a DataStore-active resource whose table was dropped (404).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.ckan import constants, files, licences
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

PKG = "11111111-2222-3333-4444-555555555555"
RES = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
XLS_FIXTURE = (
    Path(__file__).parents[2] / "nl_stats" / "__tests__" / "migration_quarterly.xls"
).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _ok(result: object) -> dict[str, object]:
    return {"success": True, "result": result}


def _workbook(sheets: dict[str, list[list[Any]]]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.worksheets[0])
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _resource(url: str, fmt: str = "CSV", **extra: Any) -> dict[str, Any]:
    return {
        "id": RES,
        "package_id": PKG,
        "name": "Tax statistics by FSA",
        "format": fmt,
        "url": url,
        "size": None,
        "last_modified": "2026-08-01T10:00:00",
        "datastore_active": False,
        **extra,
    }


def _package(licence_id: str = "ca-ogl-lgo", licence: str = "Open Government Licence - Canada"):
    return {
        "id": PKG,
        "name": "tax-stats",
        "title": "Tax statistics",
        "organization": {"id": "o1", "name": "cra-arc", "title": "Canada Revenue Agency"},
        "license_id": licence_id,
        "license_title": licence,
        "license_url": "https://open.canada.ca/en/open-government-licence-canada",
        "resources": [],
    }


def _mock_api(httpx_mock, resource: dict[str, Any], package: dict[str, Any] | None = None) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/action/resource_show\?.*"), json=_ok(resource), is_reusable=True
    )
    httpx_mock.add_response(
        url=re.compile(r".*/action/package_show\?.*"),
        json=_ok(package or _package()),
        is_reusable=True,
    )


class _Chunks(httpx.AsyncByteStream):
    """A body with no Content-Length, as a chunked response is."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


FED_FILE = f"https://open.canada.ca/data/dataset/{PKG}/resource/{RES}/download/fsa.csv"
BLOB = "https://opencanada.blob.core.windows.net/files/fsa.csv?sig=abc"


# --- host rules and licence rules -------------------------------------------------------


def test_host_matcher_exact_and_wildcard():
    allowed = files.host_matcher(constants.PORTALS["federal"])
    assert allowed("open.canada.ca") and allowed("opencanada.blob.core.windows.net")
    assert allowed("www150.statcan.gc.ca") and allowed("www.canada.ca")
    assert not allowed("evilgc.ca") and not allowed("gc.ca.evil.com") and not allowed("example.com")
    assert files.host_matcher(constants.PORTALS["ab"])("open.alberta.ca")


@pytest.mark.parametrize(
    ("licence_id", "title", "status"),
    [
        ("ca-ogl-lgo", "Open Government Licence - Canada", "open"),
        ("OGL-ON-1.0", "Open Government Licence � Ontario", "open"),
        ("2", "Open Government Licence - British Columbia", "open"),
        ("22", "Access Only", "restricted"),
        ("25", "King's Printer Licence - British Columbia", "restricted"),
        ("other-closed", "Not applicable", "restricted"),
        ("ontario.ca-tou", "Ontario.ca Terms of Use", "restricted"),
        ("public-sector-sda", "Public Sector Salary Disclosure Act", "restricted"),
        ("queens-printers-on", "King's Printer for Ontario", "restricted"),
        ("notspecified", "Licence Not Specified", "not_stated"),
        (None, None, "not_stated"),
        ("notspecified", "Open Gov. License", "open"),
        ("cc-by", "Attribution (CC-BY 4.0)", "open"),
        ("cc-by-nc-sa", "cc-by-nc-sa", "non_commercial"),
        ("54", "ICI Society Data Sharing Licence", "unrecognised"),
        ("OGNL", "No licence", "restricted"),
    ],
)
def test_licence_classification(licence_id, title, status):
    assert licences.classify(licence_id, title) == status


def test_warning_text_only_for_non_open_licences():
    assert licences.warning("open", "OGL", "https://x") is None
    text = licences.warning("restricted", "Access Only", "https://x")
    assert text and "NOT an open licence" in text and "https://x" in text
    assert "PAS" in (licences.warning("restricted", "Access Only", "https://x", "fr") or "")


# --- reading -----------------------------------------------------------------------------


async def test_federal_relative_url_redirects_to_blob_and_reads_cp1252_csv(httpx_mock):
    _mock_api(httpx_mock, _resource(f"/data/dataset/{PKG}/resource/{RES}/download/fsa.csv"))
    httpx_mock.add_response(url=FED_FILE, status_code=302, headers={"Location": BLOB})
    body = "FSA;Province;Montant\nH2X;Québec;1 200\nM5V;Ontario;3 400\n".encode("cp1252")
    httpx_mock.add_response(url=BLOB, content=body, headers={"Content-Length": str(len(body))})
    result = await files.read_resource("federal", RES, filters={"province": "québec"}, lang="fr")
    assert result.read_via == "file" and result.format == "csv"
    assert result.rows == [{"FSA": "H2X", "Province": "Québec", "Montant": "1 200"}]
    assert result.source.source_url == FED_FILE
    # A CSV declares no row count; only its width is known.
    assert [(s.name, s.rows, s.columns) for s in result.sheets] == [("csv", None, 3)]
    assert result.source.licence_status == "open" and result.source.licence_warning is None
    assert result.source.organization == "Canada Revenue Agency"
    assert result.source.landing_page and "open.canada.ca" in result.source.landing_page
    assert "Canada Revenue Agency" in result.source.citation
    assert result.provenance.licence and "ca-ogl-lgo" in result.provenance.licence


async def test_redirect_to_a_host_off_the_list_is_refused_before_it_is_requested(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(
        url=FED_FILE, status_code=302, headers={"Location": "https://evil.example.com/x.csv"}
    )
    with pytest.raises(InvalidInput, match="evil.example.com"):
        await files.read_resource("federal", RES)
    requested = [str(r.url) for r in httpx_mock.get_requests()]
    assert not any("evil.example.com" in u for u in requested)


async def test_redirect_to_http_is_refused(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(
        url=FED_FILE, status_code=302, headers={"Location": "http://open.canada.ca/x.csv"}
    )
    with pytest.raises(InvalidInput, match="https"):
        await files.read_resource("federal", RES)


async def test_resource_url_on_an_unlisted_host_is_never_requested(httpx_mock):
    _mock_api(httpx_mock, _resource("https://files.example.org/data.csv"))
    with pytest.raises(InvalidInput, match="files.example.org"):
        await files.read_resource("federal", RES)
    assert all("example.org" not in str(r.url) for r in httpx_mock.get_requests())


async def test_resource_id_must_not_be_a_url(httpx_mock):
    with pytest.raises(InvalidInput, match="not a URL"):
        await files.read_resource("federal", "https://evil.example.com/x.csv")
    assert httpx_mock.get_requests() == []


async def test_declared_length_over_the_cap_is_refused_without_reading_the_body(
    httpx_mock, monkeypatch
):
    monkeypatch.setattr(constants, "FILE_MAX_BYTES", 1000)
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(
        url=FED_FILE, content=b"a,b,c\n" * 10, headers={"Content-Length": "5000"}
    )
    with pytest.raises(UpstreamError, match="stops at 1,000"):
        await files.read_resource("federal", RES)


async def test_undeclared_stream_is_aborted_at_the_cap(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "FILE_MAX_BYTES", 1000)
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(url=FED_FILE, stream=_Chunks([b"a,b,c\n" * 100] * 5))
    with pytest.raises(UpstreamError, match="larger than 1,000 bytes"):
        await files.read_resource("federal", RES)


async def test_size_the_portal_states_over_the_cap_skips_the_download(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE, size=3_500_000_000))
    with pytest.raises(UpstreamError, match="3,500,000,000"):
        await files.read_resource("federal", RES)
    assert not any(str(r.url) == FED_FILE for r in httpx_mock.get_requests())


async def test_multi_sheet_workbook_reads_the_largest_and_says_so(httpx_mock):
    body = _workbook(
        {
            "Notes": [["Read me"], ["Source: CRA"]],
            "Data": [["FSA", "Year", "Amount"]] + [[f"H{i}X", 2022, i * 10] for i in range(25)],
        }
    )
    url = "https://files.ontario.ca/tourism/regions.xlsx"
    _mock_api(httpx_mock, _resource(url, "XLSX"), _package("OGL-ON-1.0", "Open Government Licence"))
    httpx_mock.add_response(url=url, content=body)
    result = await files.read_resource("on", RES, limit=2)
    assert result.sheet == "Data" and result.sheet_chosen_by == "largest"
    assert [s.name for s in result.sheets] == ["Notes", "Data"]
    assert result.total_rows == 25 and result.truncated
    assert result.provenance.limits and "largest" in result.provenance.limits
    named = await files.read_resource("on", RES, sheet="notes", limit=5)
    assert named.sheet == "Notes" and named.sheet_chosen_by == "request"
    with pytest.raises(InvalidInput, match="no sheet"):
        await files.read_resource("on", RES, sheet="Nope")


async def test_describe_lists_sheets_header_guess_and_candidates(httpx_mock):
    body = _workbook(
        {
            "Table": [
                ["Tourism regions 2022"],
                ["Region", "Visits", "Spend"],
                ["Niagara", 120, 4.5],
                ["Ottawa", 90, 3.1],
            ]
        }
    )
    url = "https://files.ontario.ca/tourism/regions.xlsx"
    _mock_api(httpx_mock, _resource(url, "XLSX"))
    httpx_mock.add_response(url=url, content=body)
    result = await files.describe_resource("on", RES)
    sheet = result.sheets[0]
    assert result.format == "xlsx" and result.total_sheets == 1
    assert sheet.header_row == 2 and sheet.header_row_candidates == [2]
    assert sheet.column_names == ["Region", "Visits", "Spend"]
    assert sheet.rows == 4 and sheet.preview[0][0] == "Niagara"


async def test_legacy_xls_is_read(httpx_mock):
    url = "https://files.ontario.ca/moe/MISA_2004.xls"
    _mock_api(httpx_mock, _resource(url, "XLS"))
    httpx_mock.add_response(url=url, content=XLS_FIXTURE)
    result = await files.read_resource("on", RES, limit=3)
    assert result.format == "xls" and result.rows and result.all_columns


async def test_xls_label_on_a_csv_file_still_reads(httpx_mock):
    url = "https://files.ontario.ca/misc/really.xls"
    _mock_api(httpx_mock, _resource(url, "XLS"))
    httpx_mock.add_response(url=url, content=b"a,b,c\n1,2,3\n")
    result = await files.read_resource("on", RES)
    assert result.format == "csv" and result.rows == [{"a": "1", "b": "2", "c": "3"}]


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (b"<!DOCTYPE html><html><body>Not found</body></html>", "web page"),
        (b"PK\x03\x04" + b"\x00" * 30, "ZIP archive"),
        (b'{"a": 1}', "JSON"),
        (b"<?xml version='1.0'?><Workbook/>", "XML"),
        (b"%PDF-1.7 binary", "not a readable"),
    ],
)
async def test_mislabelled_files_get_a_plain_error(httpx_mock, content, match):
    url = "https://files.ontario.ca/misc/data.csv"
    _mock_api(httpx_mock, _resource(url, "CSV"))
    httpx_mock.add_response(url=url, content=content)
    with pytest.raises(UpstreamError, match=match):
        await files.read_resource("on", RES)


async def test_pdf_resource_is_refused_before_download(httpx_mock):
    url = "https://files.ontario.ca/misc/report.pdf"
    _mock_api(httpx_mock, _resource(url, "PDF"))
    with pytest.raises(InvalidInput, match="CSV, TSV, XLS and XLSX"):
        await files.read_resource("on", RES)
    assert not any(str(r.url) == url for r in httpx_mock.get_requests())


async def test_csv_label_on_a_zip_file_name_is_refused_before_download(httpx_mock):
    url = "https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/x/attachments/All%20Areas.zip"
    _mock_api(httpx_mock, _resource(url, "CSV", size=9_871_656))
    with pytest.raises(InvalidInput, match="'.zip'"):
        await files.read_resource("federal", RES)
    assert not any(str(r.url) == url for r in httpx_mock.get_requests())


async def test_paging_arguments_are_checked():
    bad: list[dict[str, Any]] = [
        {"limit": 0},
        {"limit": 5000},
        {"offset": -1},
        {"header_row": 0},
        {"header_rows": 9},
    ]
    for kwargs in bad:
        with pytest.raises(InvalidInput):
            await files.read_resource("federal", RES, **kwargs)


async def test_http_404_on_the_file_is_not_found(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(url=FED_FILE, status_code=404)
    with pytest.raises(NotFound):
        await files.read_resource("federal", RES)


async def test_header_rows_and_columns_options_reach_the_scan(httpx_mock):
    body = _workbook(
        {
            "T": [
                ["", "Visits", "Visits"],
                ["Region", "2021", "2022"],
                ["Niagara", 100, 120],
                ["Ottawa", 80, 90],
            ]
        }
    )
    url = "https://files.ontario.ca/tourism/regions.xlsx"
    _mock_api(httpx_mock, _resource(url, "XLSX"))
    httpx_mock.add_response(url=url, content=body)
    result = await files.read_resource(
        "on", RES, header_row=1, header_rows=2, columns=["Visits 2022"]
    )
    assert result.all_columns == ["Region", "Visits 2021", "Visits 2022"]
    assert result.rows == [{"Visits 2022": "120"}, {"Visits 2022": "90"}]


async def test_the_downloaded_file_is_cached_between_calls(httpx_mock):
    body = b"a,b,c\n1,2,3\n"
    _mock_api(httpx_mock, _resource(FED_FILE))
    httpx_mock.add_response(url=FED_FILE, content=body)
    first = await files.read_resource("federal", RES)
    second = await files.describe_resource("federal", RES)
    assert not first.provenance.cached and second.provenance.cached
    downloads = [r for r in httpx_mock.get_requests() if str(r.url) == FED_FILE]
    assert len(downloads) == 1


# --- licences in responses ----------------------------------------------------------------


async def test_bc_access_only_licence_carries_a_warning(httpx_mock):
    url = "https://www2.gov.bc.ca/assets/gov/stats/table.csv"
    _mock_api(httpx_mock, _resource(url), _package("22", "Access Only"))
    httpx_mock.add_response(url=url, content=b"a,b,c\n1,2,3\n")
    result = await files.read_resource("bc", RES)
    assert result.source.licence_status == "restricted"
    assert result.source.licence_warning and "NOT an open licence" in result.source.licence_warning
    assert result.provenance.licence and "NOT an open licence" in result.provenance.licence
    assert result.provenance.coverage and "NOT an open licence" in result.provenance.coverage


async def test_toronto_files_are_not_read():
    # The reader refuses Toronto's files before any request is made.
    with pytest.raises(InvalidInput, match="automated file downloads"):
        await files.read_resource("toronto", RES)
    with pytest.raises(InvalidInput, match="automated file downloads"):
        await files.describe_resource("toronto", RES)


# --- DataStore ---------------------------------------------------------------------------


def _datastore_body(records: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return _ok(
        {
            "fields": [
                {"id": "_id", "type": "int"},
                {"id": "Year", "type": "text"},
                {"id": "n", "type": "int"},
            ],
            "records": records,
            "total": total,
        }
    )


async def test_active_datastore_serves_rows_without_the_file(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE, datastore_active=True))
    httpx_mock.add_response(
        url=re.compile(r".*/action/datastore_search\?.*"),
        json=_datastore_body([{"_id": 1, "Year": "2022", "n": 5}], 40),
    )
    result = await files.read_resource("federal", RES, filters={"Year": "2022"}, limit=1)
    assert result.read_via == "datastore" and result.sheet is None
    assert result.rows == [{"Year": "2022", "n": "5"}] and result.total_rows == 40
    assert result.truncated and result.all_columns == ["Year", "n"]
    assert not any(str(r.url) == FED_FILE for r in httpx_mock.get_requests())


async def test_datastore_404_falls_back_to_the_file(httpx_mock):
    _mock_api(httpx_mock, _resource(FED_FILE, datastore_active=True))
    httpx_mock.add_response(
        url=re.compile(r".*/action/datastore_search\?.*"),
        status_code=404,
        json={"success": False, "error": {"__type": "Not Found Error", "message": "Not found"}},
    )
    httpx_mock.add_response(url=FED_FILE, content=b"a,b,c\n1,2,3\n")
    result = await files.read_resource("federal", RES)
    assert result.read_via == "file" and result.rows[0]["a"] == "1"
    assert result.provenance.limits and "answered 404" in result.provenance.limits


async def test_portal_without_datastore_reads_the_file_even_if_flagged_active(httpx_mock):
    url = "https://open.yukon.ca/dataset/x/resource/y/download/t.csv"
    _mock_api(httpx_mock, _resource(url, datastore_active=True))
    httpx_mock.add_response(url=url, content=b"a,b,c\n1,2,3\n")
    result = await files.read_resource("yt", RES)
    assert result.read_via == "file"


async def test_workbook_of_comparable_sheets_returns_the_sheet_list_not_rows(httpx_mock):
    sheets = {
        f"Table {n}": [["Item", "Amount", "Note"]] + [[f"x{i}", i, "n"] for i in range(10 + n)]
        for n in range(1, 5)
    }
    url = "https://donnees.montreal.ca/dataset/x/resource/y/download/budget.xlsx"
    _mock_api(httpx_mock, _resource(url, "XLSX"), _package("cc-by", "Creative Commons"))
    httpx_mock.add_response(url=url, content=_workbook(sheets))
    listing = await files.read_resource("montreal", RES)
    assert listing.sheet is None and listing.sheet_chosen_by == "none" and listing.rows == []
    assert [s.name for s in listing.sheets] == [f"Table {n}" for n in range(1, 5)]
    assert listing.sheets[0].rows == 12 and listing.sheets[0].columns == 3
    assert listing.provenance.limits and "pass it as `sheet`" in listing.provenance.limits
    chosen = await files.read_resource("montreal", RES, sheet="table 2", limit=1)
    assert chosen.sheet == "Table 2" and chosen.rows[0]["Item"] == "x0"


def test_sheet_sizes_that_are_formatting_never_pick_a_sheet():
    # Declared sizes of 65,536 x 16,217 (NWT traffic) say nothing about where the table is.
    sizes = [("Numbered Highways", 9833, 16248), ("Access", 65536, 16217), ("Summary", 5165, 36)]
    assert files._choose_sheet(sizes, None, "xlsx") == (None, "none")
    assert files._choose_sheet([("Notes", 10, 2), ("Data", 5000, 20)], None, "xlsx") == (
        "Data",
        "largest",
    )
