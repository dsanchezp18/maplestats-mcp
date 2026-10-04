"""Tests for the Yukon Bureau of Statistics client.

rent_vacancy.csv is the first 39 lines of the live "Rent and vacancy
rates" file (saved 2026-09-30) with its header. The package_search fixture
keeps the fields of the live response (2026-10-03) the client reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.yukon_stats import client, constants
from maplestats_mcp.modules.yukon_stats.schemas import TableEntry
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent
_URL = (
    "https://open.yukon.ca/data/4586fed6-dfa8-4bb2-8b72-e28f9cdb2b69/resource/"
    "9d6ceba0-c79d-4de9-ab41-cf0bf2ce6765/download/rent-and-vacancy-rates.csv"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def listed(monkeypatch):
    """A catalogue holding the rent table only (query_table reads listed URLs only)."""
    entries = [
        TableEntry(
            dataset="economic-statistics",
            dataset_title="Economic statistics",
            title="Rent and vacancy rates",
            url=_URL,
            size_bytes=None,
        )
    ]

    async def catalogue():
        return entries, False

    monkeypatch.setattr(client, "_catalogue", catalogue)
    return entries


def _csv(with_footnotes: bool = False) -> bytes:
    body = (_HERE / "rent_vacancy.csv").read_bytes()
    if not with_footnotes:
        return body
    lines = body.decode("utf-8").splitlines()
    out = [lines[0] + ",footnotes"] + [line + "," + "x" * 500 for line in lines[1:]]
    return "\n".join(out).encode("utf-8")


def test_only_yukon_download_csvs_are_read():
    for bad in (
        "http://open.yukon.ca/data/a/b.csv",
        "https://example.com/data/a/b.csv",
        "https://open.yukon.ca/data/a/b.xlsx",
        "https://open.yukon.ca/api/3/action/package_list.csv",
    ):
        with pytest.raises(InvalidInput):
            client.check_table_url(bad)
    client.check_table_url(_URL)


_SEARCH = re.compile(r"https://open\.yukon\.ca/api/3/action/package_search.*")


def _resource(name: str, fmt: str, url: str, size: int | None = 68847) -> dict:
    return {
        "name": name,
        "format": fmt,
        "url": url,
        "size": size,
        "last_modified": "2026-05-20T23:19:06.043767",
        "metadata_modified": "2026-05-20T23:19:06.060913",
    }


def _search(*extra: dict) -> dict:
    packages = [
        {
            "name": "economic-statistics",
            "id": "p1",
            "title": "Economic statistics",
            "license_title": "Open Government Licence - Yukon",
            "resources": [
                _resource("Rent and vacancy rates", "CSV", _URL),
                _resource("Community Statistics", "HTML", "https://community.example/search"),
                _resource("Elsewhere", "CSV", "https://example.com/data/x.csv"),
                *extra,
            ],
        },
        {
            "name": "social-statistics",
            "id": "p2",
            "title": "Social statistics",
            "license_title": "Open Government Licence - Yukon",
            "resources": [
                _resource(
                    "Crime", "CSV", "https://open.yukon.ca/data/a/resource/b/download/crime.csv"
                )
            ],
        },
    ]
    return {"success": True, "result": {"count": 2, "results": packages}}


async def test_query_filters_select_columns_and_page(httpx_mock, listed):
    httpx_mock.add_response(url=_URL, content=_csv())
    result = await client.query_table(
        _URL, filters={"REGION": "yukon"}, columns=["year", "quarter", "median_rent"], limit=2
    )
    assert result.columns == ["year", "quarter", "median_rent"]
    assert result.total_rows >= 3 and result.truncated
    assert result.rows[0] == {"year": "2025", "quarter": "1", "median_rent": "1340"}
    assert result.licence == constants.LICENCE["en"]
    assert "Open Government Licence - Yukon" in (result.provenance.licence or "")
    assert "Showing rows 1 to 2" in (result.provenance.limits or "")


async def test_footnotes_column_is_dropped(httpx_mock, listed):
    httpx_mock.add_response(url=_URL, content=_csv(with_footnotes=True))
    result = await client.query_table(_URL, limit=1)
    assert "footnotes" not in result.all_columns
    assert "footnotes" not in result.rows[0]


async def test_unknown_column_is_invalid_input(httpx_mock, listed):
    httpx_mock.add_response(url=_URL, content=_csv())
    with pytest.raises(InvalidInput, match="Unknown column"):
        await client.query_table(_URL, filters={"nope": "x"})


async def test_html_page_is_not_found(httpx_mock, listed):
    httpx_mock.add_response(url=_URL, content=b"<!DOCTYPE html><html>Not here</html>")
    with pytest.raises(NotFound):
        await client.query_table(_URL)


async def test_unlisted_csv_is_not_read(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json=_search())
    with pytest.raises(NotFound, match="not a CSV table"):
        await client.query_table("https://open.yukon.ca/data/x/resource/y/download/other.csv")


async def test_oversized_file_is_refused_before_download(httpx_mock):
    big = "https://open.yukon.ca/data/a/resource/c/download/big.csv"
    httpx_mock.add_response(
        url=_SEARCH,
        json=_search(_resource("Big", "CSV", big, size=constants.MAX_FILE_BYTES + 1)),
    )
    with pytest.raises(UpstreamError, match="larger than"):
        await client.query_table(big)
    assert [str(r.url) for r in httpx_mock.get_requests() if "download" in str(r.url)] == []


async def test_catalogue_is_one_call_and_keeps_only_bureau_csvs(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json=_search())
    everything = await client.list_tables()
    assert [t.title for t in everything.tables] == ["Rent and vacancy rates", "Crime"]
    modified = everything.tables[0].modified
    assert modified and modified.year == 2026
    assert everything.tables[0].size_bytes == 68847
    assert (await client.list_tables(query="rent vacancy")).total_tables == 1
    assert (await client.list_tables(dataset="social")).tables[0].title == "Crime"
    assert len(httpx_mock.get_requests()) == 1
    assert "Open Government Licence - Yukon" in (everything.provenance.licence or "")


async def test_renamed_file_of_a_listed_resource_is_refused(listed):
    # Live 2026-10-03: the portal served the rent table for this made-up file
    # name (it goes by the resource id), so the URL must match the catalogue.
    bogus = _URL.replace("rent-and", "zz")
    with pytest.raises(InvalidInput, match="rent-and-vacancy-rates.csv"):
        await client.query_table(bogus)


async def test_unlisted_resource_is_not_found(listed):
    other = "https://open.yukon.ca/data/x/resource/y/download/other.csv"
    with pytest.raises(NotFound, match="yukon_stats_list_tables"):
        await client.query_table(other)


async def test_stated_size_over_the_cap_is_refused_before_download(listed):
    listed[0].size_bytes = constants.MAX_FILE_BYTES + 1
    with pytest.raises(UpstreamError, match="Download it from the portal"):
        await client.query_table(_URL)


async def test_declared_length_over_the_cap_stops_the_download(httpx_mock, listed):
    httpx_mock.add_response(
        url=_URL,
        content=_csv(),
        headers={"content-length": str(constants.MAX_FILE_BYTES + 1)},
    )
    with pytest.raises(UpstreamError, match="this reader stops at"):
        await client.query_table(_URL)
