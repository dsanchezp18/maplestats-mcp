"""Client tests with the quirks seen live on open.alberta.ca on 2026-10-02.

income_support.xlsx and indicators.xlsx are the live workbooks, unchanged.
The package payloads follow the live package_search / package_show shape,
including a link resource on another host, an "XLSX" resource that is a
CSV, an extensionless file name and a dataset under license_id OGNL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.ab_opendata import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent
DATASET_ID = "e1ec585f-3f52-40f2-a022-5a38ea3397e5"
RESOURCE_ID = "f660db62-5687-4614-8f53-327652856f80"
CSV_ID = "4f97a3ae-1b3a-48e9-a96f-f65c58526e07"
LINK_ID = "11111111-2222-3333-4444-555555555555"
MISLABELLED_ID = "99999999-2222-3333-4444-555555555555"
BASE = f"https://open.alberta.ca/dataset/{DATASET_ID}/resource"
XLSX_URL = f"{BASE}/{RESOURCE_ID}/download/is-aggregated-data-april-2005-jun-2026.xlsx"
CSV_URL = f"{BASE}/{CSV_ID}/download/is.csv"
MISLABELLED_URL = f"{BASE}/{MISLABELLED_ID}/download/is-truncated-name-with-no-extens"
LINK_URL = "https://regionaldashboard.alberta.ca/export/opendata/Tax/xlsxs"


def _resource(rid: str, fmt: str, url: str, size: int | None = None) -> dict:
    return {
        "id": rid,
        "name": f"File {fmt}",
        "format": fmt,
        "url": url,
        "size": size,
        "last_modified": "2026-09-03T22:02:33.905506",
        "description": "Caseload &nbsp; table",
    }


def _package(licence_id: str = "OGLA", licence: str = "Open Government Licence - Alberta"):
    return {
        "id": DATASET_ID,
        "name": "income-support-caseload-alberta",
        "title": "Income Support Caseload",
        "type": "opendata",
        "license_id": licence_id,
        "license_title": licence,
        "license_url": "https://open.alberta.ca/licence",
        "date_modified": "2026-09-03",
        "updatefrequency": "Quarterly",
        "notes": "Monthly caseload.\r\n\r\n&nbsp;\r\n\r\nBy region.",
        "organization": {"name": "assisted-living-and-social-services", "title": "ALSS"},
        "topic": ["Society and Communities"],
        "resources": [
            _resource(LINK_ID, "XLSX", LINK_URL),
            _resource(RESOURCE_ID, "XLSX", XLSX_URL, 127868),
            _resource(CSV_ID, "CSV", CSV_URL, 224478),
            _resource(MISLABELLED_ID, "XLSX", MISLABELLED_URL),
            _resource("77777777-2222-3333-4444-555555555555", "PDF", XLSX_URL + ".pdf"),
        ],
    }


def _envelope(result) -> dict:
    return {"success": True, "result": result}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def show(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*/action/package_show\?.*"), json=_envelope(_package()), is_reusable=True
    )


def test_parse_dataset_flags_links_and_cleans_text():
    entry = client.parse_dataset(_package())
    assert entry.ogl_alberta and entry.licence_note is None
    assert [r.readable for r in entry.resources] == [True, True, True, False, False]
    link = next(r for r in entry.resources if r.id == LINK_ID)
    assert not link.readable
    assert entry.other_formats == ["pdf", "xlsx"]
    assert entry.summary == "Monthly caseload. By region."
    assert entry.resources[0].description == "Caseload table"


def test_dataset_under_another_licence_gets_a_plain_note():
    entry = client.parse_dataset(_package("OGNL", "No licence"))
    assert not entry.ogl_alberta
    assert entry.licence_note and "NOT under the Open Government Licence" in entry.licence_note
    assert "non-commercial" in entry.licence_note
    french = client.parse_dataset(_package("OGNL", "No licence"), "fr")
    assert french.licence_note and "PAS" in french.licence_note


def test_download_urls_are_checked():
    assert client.parse_download_url(XLSX_URL) == (DATASET_ID, RESOURCE_ID)
    for bad in (
        XLSX_URL.replace("https://", "http://"),
        XLSX_URL.replace("open.alberta.ca", "example.com"),
        LINK_URL,
        f"https://open.alberta.ca/dataset/{DATASET_ID}",
    ):
        with pytest.raises(InvalidInput):
            client.parse_download_url(bad)


async def test_search_builds_filters_and_returns_organizations(httpx_mock):
    body = _envelope(
        {
            "count": 41,
            "results": [_package()],
            "search_facets": {
                "organization": {
                    "items": [
                        {"name": "health", "display_name": "Health", "count": 12},
                    ]
                }
            },
        }
    )
    httpx_mock.add_response(url=re.compile(r".*/action/package_search\?.*"), json=body)
    result = await client.search_datasets(
        query="caseload", organization="Health", format="xlsx", ogl_alberta_only=True, limit=1
    )
    request = httpx_mock.get_requests()[0]
    fq = request.url.params["fq"]
    assert "type:opendata" in fq and "res_format:XLSX" in fq
    assert "organization:health" in fq and "license_id:OGLA" in fq
    assert result.total_datasets == 41 and result.truncated
    assert result.organizations[0].title == "Health"
    assert "Open Government Licence" in result.licence_note


async def test_search_rejects_bad_arguments():
    with pytest.raises(InvalidInput):
        await client.search_datasets(organization="a b; DROP")
    with pytest.raises(InvalidInput):
        await client.search_datasets(format="pdf")
    with pytest.raises(InvalidInput):
        await client.search_datasets(limit=0)


async def test_get_dataset_accepts_a_page_url_and_reports_missing(httpx_mock, show):
    detail = await client.get_dataset(f"https://open.alberta.ca/dataset/{DATASET_ID}")
    assert detail.dataset.name == "income-support-caseload-alberta"
    request = httpx_mock.get_requests()[0]
    assert request.url.params["id"] == DATASET_ID


async def test_get_dataset_not_found(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*package_show.*"),
        status_code=404,
        json={"success": False, "error": {"message": "Not found", "__type": "Not Found Error"}},
    )
    with pytest.raises(NotFound):
        await client.get_dataset("no-such-dataset")


async def test_read_xlsx_filters_and_attribution(httpx_mock, show):
    httpx_mock.add_response(url=XLSX_URL, content=(_HERE / "income_support.xlsx").read_bytes())
    result = await client.read_resource(
        XLSX_URL, filters={"Measure Type": "Total Caseload"}, limit=2
    )
    assert result.format == "xlsx" and result.header_row == 2
    assert result.all_columns[:2] == ["Ref_Date", "Geography"]
    assert result.rows[0]["Ref_Date"] == "2005-04-01"
    assert result.rows[0]["Geography"] == "Alberta"
    assert result.total_rows > 2 and result.truncated
    assert (
        result.attribution
        == "Contains information licensed under the Open Government Licence – Alberta."
    )
    assert result.provenance.coverage and "Open Government Licence" in result.provenance.coverage


async def test_describe_workbook_with_many_sheets(httpx_mock):
    package = _package()
    package["resources"][1]["url"] = XLSX_URL
    httpx_mock.add_response(url=re.compile(r".*package_show.*"), json=_envelope(package))
    httpx_mock.add_response(url=XLSX_URL, content=(_HERE / "indicators.xlsx").read_bytes())
    result = await client.describe_resource(XLSX_URL)
    assert result.total_sheets == 16
    names = [s.name for s in result.sheets]
    assert names[:2] == ["Time Series", "Table"]
    table = result.sheets[1]
    assert table.header_row and table.column_names
    # The default sheet skips the one-column index sheet.
    data = await client.read_resource(XLSX_URL, limit=1)
    assert data.sheet != "Time Series"
    with pytest.raises(InvalidInput, match="no sheet"):
        await client.read_resource(XLSX_URL, sheet="Nope")


async def test_csv_resource_is_read_and_cp1252_decoded(httpx_mock, show):
    body = "Year,Geography,Incidents,Value\n2001,Alberta,Total,27987\n2002,Québec,Total,3\n"
    httpx_mock.add_response(url=CSV_URL, content=body.encode("cp1252"))
    result = await client.read_resource(CSV_URL, filters={"geography": "québec"})
    assert result.format == "csv" and result.sheets == ["csv"]
    assert result.rows == [
        {"Year": "2002", "Geography": "Québec", "Incidents": "Total", "Value": "3"}
    ]


async def test_mislabelled_xlsx_that_is_really_csv_still_reads(httpx_mock, show):
    httpx_mock.add_response(url=MISLABELLED_URL, content=b"a,b,c\n1,2,3\n")
    result = await client.read_resource(MISLABELLED_URL)
    assert result.format == "csv" and result.rows == [{"a": "1", "b": "2", "c": "3"}]


async def test_link_resources_and_html_answers_are_refused(httpx_mock, show):
    link = XLSX_URL.replace(RESOURCE_ID, LINK_ID)
    with pytest.raises(InvalidInput, match="not an Excel or CSV"):
        await client.read_resource(link)
    httpx_mock.add_response(url=XLSX_URL, content=b"<!DOCTYPE html><html>error</html>")
    with pytest.raises(UpstreamError, match="web page"):
        await client.read_resource(XLSX_URL)


async def test_resource_not_in_dataset_is_not_found(httpx_mock, show):
    other = XLSX_URL.replace(RESOURCE_ID, "00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFound, match="not listed"):
        await client.read_resource(other)


async def test_dataset_without_open_licence_is_flagged_on_read(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*package_show.*"), json=_envelope(_package("OGNL", "No licence"))
    )
    httpx_mock.add_response(url=CSV_URL, content=b"a,b,c\n1,2,3\n")
    result = await client.read_resource(CSV_URL)
    assert not result.ogl_alberta and result.attribution is None
    assert result.licence_note and "alberta.ca terms of use" in result.licence_note


async def test_read_rejects_bad_paging(httpx_mock):
    for kwargs in ({"limit": 0}, {"offset": -1}, {"header_row": 0}, {"header_rows": 9}):
        with pytest.raises(InvalidInput):
            await client.read_resource(XLSX_URL, **kwargs)  # type: ignore[arg-type]


async def test_http_404_on_download_is_not_found(httpx_mock, show):
    httpx_mock.add_response(url=XLSX_URL, status_code=404)
    with pytest.raises(NotFound):
        await client.read_resource(XLSX_URL)
