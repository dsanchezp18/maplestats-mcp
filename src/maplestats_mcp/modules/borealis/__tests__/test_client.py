from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.borealis import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SEARCH = re.compile(re.escape(constants.SEARCH_URL) + r"\?.*")
_FILES = re.compile(re.escape(constants.FILES_URL) + r"\?.*")

# Shapes from live responses, 2026-09-25.
_DATASET = {
    "global_id": "doi:10.5683/SP3/JX8P4H",
    "name": "Labour Force Historical Review, 2007 [Canada] [B2020]",
    "published_at": "2016-01-01T00:00:00Z",
}
_LISTING = [
    {"label": "Table-024.ivt", "restricted": False, "dataFile": {"id": 5001, "filesize": 900}},
    {"label": "Table-024.csv", "restricted": False, "dataFile": {"id": 5002, "filesize": 100}},
    {"label": "guide.pdf", "restricted": False, "dataFile": {"id": 5003, "filesize": 50}},
]
_FILE_HIT = {
    "name": "Dec07DA.ivt",
    "file_id": "3393",
    "dataset_name": "Canadian Business Patterns, Dissemination Area (DA) Level",
    "dataset_persistent_id": "doi:10.5683/SP3/1DG0LK",
    "size_in_bytes": 86748851,
    "restricted": False,
}


def test_solr_query_requires_every_word_and_drops_syntax():
    # Bare words are OR'd by Solr; a stray colon or parenthesis would break q.
    assert client.solr_query("labour force", ivt_files=False) == '"labour" AND "force"'
    assert client.solr_query("pay:(test)", ivt_files=True) == '"pay" AND "test" AND fileName:*.ivt'
    assert client.solr_query("", ivt_files=False) == "*"
    assert client.solr_query("", ivt_files=True) == "fileName:*.ivt"


def test_solr_query_keeps_operator_looking_words_literal():
    # A bare -2021 is a prohibit operator and a bare AND/OR/NOT an operator
    # (live 2026-10-17); quoted, they are ordinary terms.
    assert client.solr_query("census -2021", ivt_files=False) == '"census" AND "-2021"'
    assert client.solr_query("census AND 2021", ivt_files=False) == (
        '"census" AND "AND" AND "2021"'
    )
    assert client.solr_query("not or and", ivt_files=False) == '"not" AND "or" AND "and"'
    # A lone hyphen has no term in it.
    assert client.solr_query("census - 2021", ivt_files=False) == '"census" AND "2021"'
    assert client.solr_query("-", ivt_files=False) == "*"


async def test_dataset_search_lists_ivt_files_and_twins(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 44, "items": [_DATASET]}})
    httpx_mock.add_response(url=_FILES, json={"data": _LISTING})
    result = await client.search_ivt("labour force historical review", limit=5)
    assert result.datasets_matched == 44
    assert result.total_matched == 1 and not result.truncated
    # Only the top datasets are read for files, and the limits say so.
    assert "top 10 of 44 matching datasets" in (result.provenance.limits or "")
    assert [f.file_name for f in result.files] == ["Table-024.ivt"]
    item = result.files[0]
    assert item.download_url == "https://borealisdata.ca/api/access/datafile/5001"
    assert item.other_formats == ["Table-024.csv"]
    assert 'read_ivt("data/raw/Table-024.ivt")' in item.r_snippet
    search = httpx_mock.get_requests()[0]
    assert search.url.params["q"] == '"labour" AND "force" AND "historical" AND "review"'
    assert search.url.params["type"] == "dataset"


async def test_files_cut_at_limit_say_so(httpx_mock):
    listing = [
        {"label": f"T{i}.ivt", "restricted": False, "dataFile": {"id": i, "filesize": 9}}
        for i in range(3)
    ]
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 1, "items": [_DATASET]}})
    httpx_mock.add_response(url=_FILES, json={"data": listing})
    result = await client.search_ivt("labour", limit=2)
    assert result.returned_count == 2 and result.total_matched == 3 and result.truncated
    assert (result.provenance.limits or "").startswith("Returned the first 2 of 3 IVT files")


async def test_falls_back_to_file_search(httpx_mock):
    # A dataset with only documentation, then the file-name search.
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 1, "items": [_DATASET]}})
    httpx_mock.add_response(url=_FILES, json={"data": [_LISTING[2]]})
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 1, "items": [_FILE_HIT]}})
    result = await client.search_ivt("dec07da", limit=5)
    assert [f.file_id for f in result.files] == ["3393"]
    assert httpx_mock.get_requests()[-1].url.params["q"] == '"dec07da" AND fileName:*.ivt'


async def test_bad_input_and_shapes(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.search_ivt("x", limit=0)
    httpx_mock.add_response(url=_SEARCH, json={"status": "ERROR"})
    with pytest.raises(UpstreamError):
        await client.search_ivt("")


async def test_search_with_operator_looking_words_sends_them_quoted(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 0, "items": []}})
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 0, "items": []}})
    result = await client.search_ivt("census -2021", limit=5)
    assert result.files == []
    first = httpx_mock.get_requests()[0]
    assert first.url.params["q"] == '"census" AND "-2021"'
    assert first.url.params["type"] == "dataset"


async def test_search_400_is_invalid_input_not_an_upstream_fault(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, status_code=400, json={"status": "ERROR"})
    with pytest.raises(InvalidInput, match="could not parse the query"):
        await client.search_ivt("census")


async def test_search_400_is_invalid_input_in_french(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, status_code=400, json={"status": "ERROR"})
    with pytest.raises(InvalidInput, match="n'a pas pu interpr"):
        await client.search_ivt("recensement", lang="fr")


async def test_non_search_400_stays_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json={"data": {"total_count": 1, "items": [_DATASET]}})
    httpx_mock.add_response(url=_FILES, status_code=400, json={})
    with pytest.raises(UpstreamError, match="HTTP 400"):
        await client.search_ivt("labour")
