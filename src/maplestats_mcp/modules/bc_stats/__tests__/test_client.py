"""Tests for the BC Stats Excel client against real payloads saved 2026-10-01.

package_search_bc_stats.json is the live `package_search` answer for the
bc-stats organization cut to six datasets (descriptions and tags removed);
the .xlsx files are the live BC Stats workbooks, unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.bc_stats import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent
_SEARCH = re.compile(r"https://catalogue\.data\.gov\.bc\.ca/api/3/action/package_search\?.*")


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


def _packages() -> list[dict]:
    return json.loads(_bytes("package_search_bc_stats.json"))["result"]["results"]


def _by_name(name: str) -> str:
    """Download URL of the fixture file whose catalogue .xlsx name is `name`."""
    return next(f.url for f in client.parse_packages(_packages()) if f.url.endswith(name))


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def catalogue(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, content=_bytes("package_search_bc_stats.json"))


def test_parse_packages_keeps_only_xlsx_with_licence_and_flags():
    files = client.parse_packages(_packages())
    assert files and all(f.url.endswith(".xlsx") for f in files)
    lfs = next(f for f in files if f.url.endswith("lfs_datatables.xlsx"))
    assert lfs.title == "Labour Force Survey (LFS) Monthly Data Tables (XLS)"
    assert lfs.licence == "Open Government Licence - British Columbia"
    assert lfs.update_cycle == "monthly"
    assert lfs.datastore_flag is False
    assert {"pdf", "xlsx"} <= set(lfs.dataset_formats)
    assert lfs.dataset_url == "https://catalogue.data.gov.bc.ca/dataset/" + lfs.dataset
    # The catalogue mixes the string "true" and the boolean for datastore_active.
    assert any(f.datastore_flag is True for f in files)
    # The literal "null" BC writes for missing values is not kept as text.
    assert all(f.update_cycle != "null" for f in files)


async def test_list_files_filters_and_pages(httpx_mock, catalogue):
    everything = await client.list_files(limit=200)
    assert everything.total_files == len(client.parse_packages(_packages()))
    assert not everything.truncated
    assert "Open Government Licence" in everything.licence_note

    lfs = await client.list_files(query="labour force monthly")
    assert lfs.total_files >= 1
    assert all("labour force" in f.title.casefold() for f in lfs.files)

    one = await client.list_files(dataset="bankruptcies")
    assert {f.dataset for f in one.files} == {"bankruptcies"}

    first = await client.list_files(limit=2)
    second = await client.list_files(limit=2, offset=2)
    assert first.truncated and first.files != second.files
    assert first.provenance.limits and "of" in first.provenance.limits


async def test_list_files_follows_catalogue_pages(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "PAGE_SIZE", 1)
    packages = _packages()[:2]
    for start, package in enumerate(packages):
        body = {"success": True, "result": {"count": 2, "results": [package]}}
        httpx_mock.add_response(
            url=re.compile(rf".*package_search\?.*start={start}(&.*)?$"), json=body
        )
    result = await client.list_files(limit=200)
    assert {f.dataset for f in result.files} == {p["name"] for p in packages}


async def test_list_files_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.list_files(limit=0)
    with pytest.raises(InvalidInput):
        await client.list_files(offset=-1)


def test_only_catalogue_xlsx_downloads_are_read():
    good = _by_name("lfs_datatables.xlsx")
    client.check_file_url(good)
    for bad in (
        good.replace("https://", "http://"),
        good.replace("catalogue.data.gov.bc.ca", "example.com"),
        good.replace(".xlsx", ".csv"),
        "https://catalogue.data.gov.bc.ca/dataset/x/resource/y/file.xlsx",
    ):
        with pytest.raises(InvalidInput):
            client.check_file_url(bad)


async def test_read_gdp_guesses_header_and_filters(httpx_mock, catalogue):
    url = _by_name("gdp_by_industry_at_basic_prices.xlsx")
    httpx_mock.add_response(url=url, content=_bytes("gdp_by_industry_at_basic_prices.xlsx"))
    data = await client.read_file(url, contains="All industries", limit=5)
    assert [s.name for s in data.sheets] == ["BC GDP $Current", "BC GDP $2017"]
    assert data.sheet == "BC GDP $Current"
    assert data.header_row == 4
    assert data.header[1:4] == ["2007", "2008", "2009"]
    assert data.rows[0][0] == "All industries"
    # Matches Statistics Canada table 36-10-0402-01, BC, current dollars, 2021.
    by_year = dict(zip(data.header, data.rows[0], strict=False))
    assert by_year["2021"] == "330874"
    assert by_year["2023"] == ".."
    assert data.licence == "Open Government Licence - British Columbia"
    assert data.provenance.source == "bc-stats"


async def test_read_population_projections_header_override(httpx_mock, catalogue):
    name = "table_provincial_level_population_estimates_and_projections.xlsx"
    url = _by_name(name)
    httpx_mock.add_response(url=url, content=_bytes(name))
    data = await client.read_file(
        url, sheet="table 1", header_row=6, contains="Estimate", limit=500
    )
    assert data.sheet == "Table 1" and data.header_row == 6
    assert data.header[:3] == ["Statistic", "Year", "Total population (000s)"]
    by_year = {r[1]: r for r in data.rows if r[0] == "Estimate"}
    # Matches Statistics Canada table 17-10-0005-01, BC, July 1 1971: 2,240,470.
    assert by_year["1971"][2] == "2240.5"
    with pytest.raises(InvalidInput, match="past the last row with content"):
        await client.read_file(url, sheet="Table 1", header_row=5000)


async def test_read_cpi_page_matches_published_index(httpx_mock, catalogue):
    url = _by_name("cpidata.xlsx")
    httpx_mock.add_response(url=url, content=_bytes("cpidata.xlsx"))
    data = await client.read_file(url, sheet="PAGE1", header_row=6, contains="All-items", limit=1)
    assert data.header[2] == "Aug 26"
    # Matches Statistics Canada table 18-10-0004-01, BC all-items, August 2026.
    assert data.rows[0][1:3] == ["All-items", "163.8"]


async def test_paging_and_unknown_sheet(httpx_mock, catalogue):
    url = _by_name("econ_bankruptcies_quarterly.xlsx")
    httpx_mock.add_response(url=url, content=_bytes("econ_bankruptcies_quarterly.xlsx"))
    first = await client.read_file(url, limit=2)
    second = await client.read_file(url, limit=2, offset=2)
    assert first.truncated and first.rows != second.rows
    assert first.header[:3] == ["Bankruptcies Filed by Consumers", "Q1 2014", "Q2 2014"]
    with pytest.raises(InvalidInput, match="sheets are"):
        await client.read_file(url, sheet="Nope")
    with pytest.raises(InvalidInput):
        await client.read_file(url, limit=0)
    with pytest.raises(InvalidInput):
        await client.read_file(url, header_row=0)


async def test_unlisted_file_is_not_found(httpx_mock, catalogue):
    url = _by_name("lfs_datatables.xlsx").replace("c9bdc5f3", "00000000")
    with pytest.raises(NotFound, match="not an Excel file of the BC Stats"):
        await client.read_file(url)


async def test_html_page_and_http_404_are_not_found(httpx_mock, catalogue):
    url = _by_name("cpidata.xlsx")
    httpx_mock.add_response(url=url, content=b"<!DOCTYPE html><html>Error</html>")
    with pytest.raises(NotFound, match="web page"):
        await client.read_file(url)
    cache_module._caches.clear()
    other = _by_name("econ_bankruptcies_quarterly.xlsx")
    httpx_mock.add_response(url=other, status_code=404)
    httpx_mock.add_response(url=_SEARCH, content=_bytes("package_search_bc_stats.json"))
    with pytest.raises(NotFound, match="no file"):
        await client.read_file(other)


async def test_french_errors_and_provenance(httpx_mock, catalogue):
    with pytest.raises(InvalidInput, match="Entrée invalide.*limit doit être compris"):
        await client.list_files(limit=0, lang="fr")
    with pytest.raises(InvalidInput, match="lien de téléchargement"):
        client.check_file_url("https://example.com/x.xlsx", lang="fr")

    url = _by_name("gdp_by_industry_at_basic_prices.xlsx")
    httpx_mock.add_response(url=url, content=_bytes("gdp_by_industry_at_basic_prices.xlsx"))
    data = await client.read_file(url, limit=5, lang="fr")
    assert data.provenance.licence
    assert data.provenance.licence.startswith("Licence du gouvernement ouvert – Colombie")
    assert data.provenance.freshness
    assert data.provenance.freshness.startswith("Tel que publié par BC Stats")
    assert data.provenance.coverage
    assert "feuille 'BC GDP $Current' sur 2" in data.provenance.coverage
    with pytest.raises(InvalidInput, match="aucune feuille 'Nope'"):
        await client.read_file(url, sheet="Nope", lang="fr")

    listing = await client.list_files(limit=2, lang="fr")
    assert listing.provenance.limits
    assert listing.provenance.limits.startswith("Fichiers 1 à 2 sur")
    assert "Licence du gouvernement ouvert – Colombie-Britannique" in listing.licence_note


async def test_english_text_is_unchanged(httpx_mock, catalogue):
    with pytest.raises(InvalidInput, match=r"^bc_stats: limit must be 1 to 200\.$"):
        await client.list_files(limit=0)
    listing = await client.list_files(limit=2)
    assert listing.provenance.freshness == "Catalogue metadata, cached for six hours."
    assert listing.provenance.limits
    assert listing.provenance.limits.startswith("Showing files 1 to 2 of")
    url = _by_name("gdp_by_industry_at_basic_prices.xlsx")
    httpx_mock.add_response(url=url, content=_bytes("gdp_by_industry_at_basic_prices.xlsx"))
    data = await client.read_file(url, limit=5)
    assert data.provenance.freshness
    assert data.provenance.freshness.startswith("As published by BC Stats; catalogue update")
    assert data.provenance.licence
    assert data.provenance.licence.startswith("Open Government Licence - British Columbia")
