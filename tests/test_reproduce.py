"""reproduce_code: retrieval plus cleaning scripts (argument-based specs, no network).

Generated scripts were run for real on 2026-09-24 (R 4.5 and Python with
polars) against Valet, Socrata, WDS vectors and full StatCan tables.
"""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.reproduce import client
from maple_data_mcp.shared.errors import InvalidInput


def _by_language(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


async def test_all_languages_by_default_with_cleaning():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 1810000401})
    code = _by_language(result)
    assert set(code) == {"r", "python", "stata", "julia"}
    assert result.source_url == "https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip"
    assert 'get_cansim("18-10-0004-01")' in code["r"] and "val_norm" in code["r"]
    assert "http2=True" in code["python"]  # StatCan rejects HTTP/1.1-only clients
    assert 'pl.col("SCALAR_ID")' in code["python"]  # scale VALUE by its power of ten
    assert "value * 10^scalar_id" in code["stata"] and " cd " not in code["stata"]
    assert "@clean_names" in code["julia"]
    # Standard cleaning in every language.
    assert "str_trim" in code["r"] and "strip_chars" in code["python"]
    assert "strtrim" in code["stata"] and "destring" in code["stata"]


async def test_one_language_on_request():
    result = await client.reproduce(
        "boc_get_observations", {"series_names": ["FXUSDCAD"], "recent": 5}, "python"
    )
    assert [s.language for s in result.scripts] == ["python"]
    assert 'data.unpivot(index="d"' in result.scripts[0].code  # Valet made long


async def test_french_table_uses_semicolons_and_french_columns():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004, "lang": "fr"})
    code = _by_language(result)
    assert result.source_url.endswith("18100004-fra.zip")
    assert 'separator=";"' in code["python"] and 'pl.col("VALEUR")' in code["python"]
    assert 'delimiters(";")' in code["stata"]
    assert 'delim = ";"' in code["julia"]
    assert 'language = "fr"' in code["r"]


async def test_zip_scripts_skip_metadata_files():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004})
    code = _by_language(result)
    assert '"metadata" not in n.lower()' in code["python"]
    assert 'strpos(lower("`file\'"), "metadata") == 0' in code["stata"]
    assert "get_cansim" in code["r"]  # R uses cansim, not the ZIP


async def test_valet_and_socrata_keep_their_filters():
    boc = await client.reproduce(
        "boc_get_observations", {"series_names": ["FXUSDCAD", "V39079"], "recent": 5}
    )
    assert boc.source_url.endswith("/observations/FXUSDCAD,V39079/json?recent=5")
    soda = await client.reproduce(
        "socrata_query_dataset_rows",
        {"portal": "calgary", "dataset_id": "848s-4m4z", "where": "year > 2020", "limit": 10},
    )
    assert soda.source_url == (
        "https://data.calgary.ca/resource/848s-4m4z.csv?%24where=year+%3E+2020&%24limit=10"
    )


async def test_vectors_flatten_one_object_per_vector():
    result = await client.reproduce(
        "wds_get_data_from_vectors", {"vector_ids": [41690973], "latest_n": 3}, "python"
    )
    code = result.scripts[0].code
    assert 'item["object"]["vectorDataPoint"]' in code and "client.post(" in code
    assert "scalarFactorCode" in code


async def test_ivt_only_table_gets_r_only():
    result = await client.reproduce(
        "statcan_census_tables_get_downloads", {"pid": "93658", "release": "2006"}
    )
    assert [s.language for s in result.scripts] == ["r"]
    assert "read_ivt" in result.scripts[0].code
    assert any("canivt" in note for note in result.notes)


async def test_provenance_fallback_classifies_urls():
    assert client._spec_from_provenance("https://x.ca/data/file.csv").kind == "csv"
    assert (
        client._spec_from_provenance("https://x.ca/api/3/action/package_show?id=1").kind == "json"
    )
    page = client._spec_from_provenance("https://www03.cmhc-schl.gc.ca/hmip-pimh/en/TableMapChart")
    assert page.kind == "html" and "web page" in page.notes[0]


async def test_bad_requests():
    with pytest.raises(InvalidInput):
        await client.reproduce("plan_query", {})
    with pytest.raises(InvalidInput):
        await client.reproduce("wds_get_cube_metadata", {"product_id": 12})
    with pytest.raises(InvalidInput):
        await client.reproduce("boc_get_observations", {})
