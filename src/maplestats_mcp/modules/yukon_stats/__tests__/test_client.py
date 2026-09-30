"""Tests for the Yukon Bureau of Statistics client.

rent_vacancy.csv is the first 39 lines of the live "Rent and vacancy
rates" file (saved 2026-09-30) with its header.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from maplestats_mcp.modules.yukon_stats import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_HERE = Path(__file__).parent
_URL = (
    "https://open.yukon.ca/data/4586fed6-dfa8-4bb2-8b72-e28f9cdb2b69/resource/"
    "9d6ceba0-c79d-4de9-ab41-cf0bf2ce6765/download/rent-and-vacancy-rates.csv"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


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


async def test_query_filters_select_columns_and_page(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_csv())
    result = await client.query_table(
        _URL, filters={"REGION": "yukon"}, columns=["year", "quarter", "median_rent"], limit=2
    )
    assert result.columns == ["year", "quarter", "median_rent"]
    assert result.total_rows >= 3 and result.truncated
    assert result.rows[0] == {"year": "2025", "quarter": "1", "median_rent": "1340"}
    assert result.licence == constants.LICENCE["en"]


async def test_footnotes_column_is_dropped(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_csv(with_footnotes=True))
    result = await client.query_table(_URL, limit=1)
    assert "footnotes" not in result.all_columns
    assert "footnotes" not in result.rows[0]


async def test_unknown_column_is_invalid_input(httpx_mock):
    httpx_mock.add_response(url=_URL, content=_csv())
    with pytest.raises(InvalidInput, match="Unknown column"):
        await client.query_table(_URL, filters={"nope": "x"})


async def test_html_page_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_URL, content=b"<!DOCTYPE html><html>Not here</html>")
    with pytest.raises(NotFound):
        await client.query_table(_URL)


async def test_catalogue_keeps_only_bureau_csvs(monkeypatch):
    packages = [SimpleNamespace(id="p1"), SimpleNamespace(id="p2")]

    async def fake_search(portal, query, **kwargs):
        assert portal == "yt" and kwargs["fq"] == "organization:yukon-bureau-of-statistics"
        return SimpleNamespace(packages=packages)

    def resource(name, fmt, url):
        return SimpleNamespace(
            name=name,
            format=fmt,
            url=url,
            last_modified=None,
            metadata_modified=datetime(2026, 5, 20, tzinfo=UTC),
        )

    details = {
        "p1": SimpleNamespace(
            name="economic-statistics",
            id="p1",
            title="Economic statistics",
            resources=[
                resource("Rent and vacancy rates", "CSV", _URL),
                resource("Community Statistics", "HTML", "https://community.example/search"),
                resource("Elsewhere", "CSV", "https://example.com/data/x.csv"),
            ],
        ),
        "p2": SimpleNamespace(
            name="social-statistics",
            id="p2",
            title="Social statistics",
            resources=[
                resource(
                    "Crime", "CSV", "https://open.yukon.ca/data/a/resource/b/download/crime.csv"
                )
            ],
        ),
    }

    async def fake_detail(portal, dataset_id):
        return details[dataset_id]

    monkeypatch.setattr(client.ckan, "search_datasets", fake_search)
    monkeypatch.setattr(client.ckan, "get_dataset", fake_detail)

    everything = await client.list_tables()
    assert [t.title for t in everything.tables] == ["Rent and vacancy rates", "Crime"]
    modified = everything.tables[0].modified
    assert modified and modified.year == 2026
    assert (await client.list_tables(query="rent vacancy")).total_tables == 1
    assert (await client.list_tables(dataset="social")).tables[0].title == "Crime"
