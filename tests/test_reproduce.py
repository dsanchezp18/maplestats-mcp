"""reproduce_code specs and rendering (no network: argument-based specs only).

The rendered snippets were run for real on 2026-09-24 (R 4.5 and Python
with polars): Valet, Socrata, WDS vectors and a full StatCan table.
"""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.reproduce import client
from maple_data_mcp.shared.errors import InvalidInput

LANGUAGES = ("r", "python", "stata", "julia")


@pytest.mark.parametrize("language", LANGUAGES)
async def test_statcan_table_every_language(language):
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 1810000401}, language)
    assert result.source_url == "https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip"
    assert result.method.startswith("exact")
    if language == "r":
        assert 'get_cansim("18-10-0004-01")' in result.code
    if language == "python":
        # StatCan rejects clients that offer only HTTP/1.1.
        assert "http2=True" in result.code and "httpx[http2]" in result.packages
    if language == "stata":
        assert "import delimited" in result.code and " cd " not in result.code


async def test_valet_and_socrata_keep_their_filters():
    boc = await client.reproduce(
        "boc_get_observations", {"series_names": ["FXUSDCAD", "V39079"], "recent": 5}, "python"
    )
    assert boc.source_url.endswith("/observations/FXUSDCAD,V39079/json?recent=5")
    assert 'records = json.loads(raw_path.read_text(encoding="utf-8"))["observations"]' in boc.code
    soda = await client.reproduce(
        "socrata_query_dataset_rows",
        {"portal": "calgary", "dataset_id": "848s-4m4z", "where": "year > 2020", "limit": 10},
        "julia",
    )
    assert soda.source_url == (
        "https://data.calgary.ca/resource/848s-4m4z.csv?%24where=year+%3E+2020&%24limit=10"
    )


async def test_vectors_flatten_one_object_per_vector():
    result = await client.reproduce(
        "wds_get_data_from_vectors", {"vector_ids": [41690973], "latest_n": 3}, "python"
    )
    assert "for item in json.loads(" in result.code
    assert 'item["object"]["vectorDataPoint"]' in result.code
    assert "client.post(" in result.code


async def test_old_census_table_routes_to_canivt_in_r_and_sdmx_note_elsewhere():
    r_code = await client.reproduce(
        "statcan_census_tables_get_downloads", {"pid": "93658", "release": "2006"}, "r"
    )
    assert "canivt" in r_code.code and "read_ivt" in r_code.code
    python = await client.reproduce(
        "statcan_census_tables_get_downloads", {"pid": "93658", "release": "2006"}, "python"
    )
    assert any("SDMX" in note for note in python.notes)


async def test_provenance_fallback_classifies_urls():
    assert client._spec_from_provenance("https://x.ca/data/file.csv").kind == "csv"
    assert (
        client._spec_from_provenance("https://x.ca/api/3/action/package_show?id=1").kind == "json"
    )
    page = client._spec_from_provenance("https://www03.cmhc-schl.gc.ca/hmip-pimh/en/TableMapChart")
    assert page.kind == "html" and "web page" in page.notes[0]


async def test_bad_requests():
    with pytest.raises(InvalidInput):
        await client.reproduce("plan_query", {}, "r")
    with pytest.raises(InvalidInput):
        await client.reproduce("wds_get_cube_metadata", {"product_id": 12}, "r")
    with pytest.raises(InvalidInput):
        await client.reproduce("boc_get_observations", {}, "r")
