"""reproduce_code returns what the tool returns: row counts, ids and codes.

Each test pins one fix from a live review (2026-10-03) that ran the
generated scripts against their sources and compared them with the tools;
scripts/verify_reproduce_counts.py repeats those runs live. No network
here: the CKAN and Valet existence checks are stubbed unless a test is
about them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from maplestats_mcp.modules.reproduce import builders, cleaning, client, probe
from maplestats_mcp.modules.reproduce.client import RENDERERS
from maplestats_mcp.modules.reproduce.spec import Filter, Spec
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.arcgis import layer_query_url
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.http import RecordedRequest


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def offline(monkeypatch):
    from maplestats_mcp.modules.boc import client as boc_client
    from maplestats_mcp.modules.ckan import client as ckan_client

    calls: list[tuple] = []

    async def found(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(boc_client, "get_observations", found)
    monkeypatch.setattr(ckan_client, "datastore_search", found)
    return calls


def _code(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


def _render(spec: Spec) -> dict[str, str]:
    rendered = {lang: RENDERERS[lang](spec, "example_tool") for lang in RENDERERS}
    return {lang: out[0] for lang, out in rendered.items() if out is not None}


# H1: R vectors keep the latest periods ------------------------------------------


async def test_r_vectors_ask_for_the_latest_periods():
    result = await client.reproduce(
        "wds_get_data_from_vectors", {"vector_ids": [41690973, "v41690914"], "latest_n": 6}, "r"
    )
    code = result.scripts[0].code
    assert "get_cansim_vector_for_latest_periods(" in code
    assert 'c("v41690973", "v41690914")' in code and "periods = 6" in code
    assert "get_cansim_vector(" not in code


async def test_bad_vector_ids_and_counts_are_typed_errors():
    with pytest.raises(InvalidInput, match="vector ids"):
        await client.reproduce("wds_get_data_from_vectors", {"vector_ids": ["abc"]})
    with pytest.raises(InvalidInput, match="latest_n"):
        await client.reproduce("wds_get_data_from_vectors", {"vector_ids": [1], "latest_n": "ten"})
    with pytest.raises(InvalidInput, match="non-empty list"):
        await client.reproduce("wds_get_data_from_vectors", {"vector_ids": 41690973})


# H2: rows keep the vector's own fields ------------------------------------------


def _wds_spec() -> Spec:
    return builders.vector_spec([41690973], 2)


def test_python_vector_rows_keep_vector_and_product_ids():
    code = _render(_wds_spec())["python"]
    start = code.index("records = [")
    end = code.index("data = pl.json_normalize")
    payload = [
        {
            "status": "SUCCESS",
            "object": {
                "vectorId": 41690973,
                "productId": 18100004,
                "coordinate": "2.2.0.0.0.0.0.0.0.0",
                "vectorDataPoint": [{"refPer": "2026-07-01", "value": 1.0}, {"value": 2.0}],
            },
        }
    ]
    namespace = {"payload": payload}
    exec(code[start:end], namespace)  # noqa: S102 - this repository's own generated code
    records = namespace["records"]
    assert len(records) == 2
    assert all(r["vectorId"] == 41690973 and r["productId"] == 18100004 for r in records)
    assert "vectorDataPoint" not in records[0]


def test_julia_and_r_vector_rows_keep_the_parent_fields():
    code = _render(_wds_spec())
    assert 'for (k, v) in item["object"] if !(v isa JSON3.Object' in code["julia"]
    assert 'item["object"]["vectorDataPoint"]' in code["julia"]
    # JSON null reads as nothing in Julia; the cleaning works on missing.
    assert "x === nothing ? missing : x" in code["julia"]
    # Stata runs the same Python block as the Python script.
    assert "isinstance(value, (dict, list))" in code["stata"]


def test_r_each_item_reader_merges_parent_fields():
    spec = _wds_spec()
    spec.native = {}
    code = RENDERERS["r"](spec, "tool")[0]
    assert 'parent <- item[["object"]]' in code
    assert 'parent[["vectorDataPoint"]]' in code and "scalars[setdiff(" in code


# H3: codes stay text --------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "is_code"),
    [
        ("coordinate", True),
        ("vector_id", True),
        ("vectorid", True),
        ("product_id", True),
        ("dguid", True),
        ("geo_dguid", True),
        ("postal_code", True),
        ("fsa", True),
        ("naics_2017_code", True),
        ("noc_2021", True),
        ("value", False),
        ("scalar_factor_code", False),
        ("scalar_id", False),
        ("ref_date", False),
    ],
)
def test_code_column_names(name, is_code):
    assert bool(re.search(cleaning.CODE_COLUMNS, name)) is is_code
    stata = cleaning._STATA_CODE_COLUMNS
    assert "$" not in stata and bool(re.search(stata, name + "|")) is is_code


def test_every_language_reads_delimited_files_as_text():
    spec = Spec(kind="csv", url="https://x.ca/f.csv", file_name="f.csv", method="m")
    code = _render(spec)
    assert "col_types = cols(.default = col_character())" in code["r"]
    assert "infer_schema=False" in code["python"]
    assert "stringcols(_all)" in code["stata"]
    assert "types = String" in code["julia"]
    # The standard cleaning then converts numbers but not codes.
    assert "keep_text" in code["r"] and "parse_guess" in code["r"]
    assert "code_columns.search(column)" in code["python"]
    assert 'regexm(`var\', "^-?0[0-9]")' in code["stata"]
    assert "occursin(code_columns, name)" in code["julia"]
    assert "HasLeadingZero" in code["excel"] and "CodeName(name)" in code["excel"]


def test_numeric_filters_and_sorts_compare_numbers_on_text_columns():
    spec = Spec(
        kind="csv",
        url="https://x.ca/f.csv",
        file_name="f.csv",
        method="m",
        filters=[Filter("ge", ["Value"], 1000)],
        sort_by="Value",
        sort_descending=True,
    )
    code = _render(spec)
    assert "suppressWarnings(as.numeric(`Value`)) >= 1000" in code["r"]
    assert "desc(suppressWarnings(as.numeric(`Value`)))" in code["r"]
    assert "pl.col('Value').cast(pl.Float64, strict=False) >= 1000" in code["python"]
    assert "pl.col('Value').cast(pl.Float64, strict=False), pl.col('Value')" in code["python"]
    assert 'something(tryparse(Float64, string(row["Value"])), NaN) >= 1000' in code["julia"]
    assert "numeric_sort" in code["julia"]


def test_statcan_scaling_reads_text_values():
    spec = builders.table_spec(18100004, "en")
    code = _render(spec)
    assert 'pl.col("VALUE").cast(pl.Float64, strict=False)' in code["python"]
    assert "real(value) * 10^real(scalar_id)" in code["stata"]
    assert "parse(Float64, v) * 10.0^parse(Int, s)" in code["julia"]


# H4: the tool's default limits ------------------------------------------------------


async def test_socrata_and_ckan_send_the_tools_default_limit(offline):
    soda = await client.reproduce(
        "socrata_query_dataset_rows", {"portal": "calgary", "dataset_id": "848s-4m4z"}
    )
    assert soda.source_url == "https://data.calgary.ca/resource/848s-4m4z.csv?%24limit=10"
    assert any("$limit=10" in note for note in soda.notes)
    ckan = await client.reproduce(
        "ckan_datastore_search", {"portal": "on", "resource_id": "abc-123"}
    )
    assert "limit=20&offset=0" in ckan.source_url


async def test_missing_ckan_resource_and_valet_series_raise(monkeypatch):
    from maplestats_mcp.modules.boc import client as boc_client
    from maplestats_mcp.modules.ckan import client as ckan_client

    async def missing(*args, **kwargs):
        raise NotFound("not found")

    monkeypatch.setattr(boc_client, "get_observations", missing)
    monkeypatch.setattr(ckan_client, "datastore_search", missing)
    with pytest.raises(NotFound):
        await client.reproduce("ckan_datastore_search", {"portal": "on", "resource_id": "x"})
    with pytest.raises(NotFound):
        await client.reproduce("boc_get_observations", {"series_names": ["NOPE"]})


# H5: SDMX scripts read the key's series ------------------------------------------------


async def test_sdmx_scripts_replay_the_data_url_with_the_default_last_n():
    result = await client.reproduce("sdmx_get_data", {"product_id": 18100004, "key": "2.2"})
    base = "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/data/DF_18100004/2.2"
    assert result.source_url == f"{base}?lastNObservations=100"
    assert not result.method.startswith("exact: full table")
    code = _code(result)
    assert set(code) == {"r", "python", "stata", "julia", "excel"}
    with pytest.raises(InvalidInput):
        await client.reproduce(
            "sdmx_get_data", {"product_id": 18100004, "key": "2.2", "start_period": "2020-01",
                              "last_n_observations": 3},
        )  # fmt: skip
    with pytest.raises(InvalidInput):
        await client.reproduce("sdmx_get_data", {"product_id": 18100004, "key": "2/2"})


def test_sdmx_vector_with_periods_runs_the_tool_first():
    args = {"vector_id": 41690973, "start_period": "2024-01"}
    assert not builders.argument_only("sdmx_get_vector_data", args)
    assert builders.argument_only("sdmx_get_vector_data", {"vector_id": 41690973})


async def test_sdmx_vector_without_periods_uses_the_tools_default():
    result = await client.reproduce("sdmx_get_vector_data", {"vector_id": 41690973}, "python")
    assert "'latestN': 100" in result.scripts[0].code


def test_python_sdmx_reader_makes_one_row_per_observation():
    spec = builders.sdmx_spec(
        "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/data/DF_1/1", {}, "t"
    )
    code = _render(spec)["python"]
    start = code.index("records = [")
    end = code.index("data = pl.DataFrame")
    xml = (
        '<m:GenericData xmlns:m="urn:m" xmlns:g="urn:g"><m:DataSet>'
        '<g:Series><g:SeriesKey><g:Value id="Geography" value="2"/></g:SeriesKey>'
        '<g:Attributes><g:Value id="SCALAR_FACTOR" value="0"/></g:Attributes>'
        '<g:Obs><g:ObsDimension value="2026-01"/><g:ObsValue value="1.5"/></g:Obs>'
        '<g:Obs><g:ObsDimension value="2026-02"/><g:ObsValue value="1.6"/></g:Obs>'
        "</g:Series></m:DataSet></m:GenericData>"
    )
    namespace = {"root": ET.fromstring(xml)}
    exec(code[start:end], namespace)  # noqa: S102 - this repository's own generated code
    assert namespace["records"] == [
        {"Geography": "2", "SCALAR_FACTOR": "0", "TIME_PERIOD": "2026-01", "OBS_VALUE": "1.5"},
        {"Geography": "2", "SCALAR_FACTOR": "0", "TIME_PERIOD": "2026-02", "OBS_VALUE": "1.6"},
    ]


# H6: Stata keeps quoted line breaks in one cell -----------------------------------------


def test_stata_import_binds_quotes_strictly():
    spec = Spec(kind="csv", url="https://x.ca/f.csv", file_name="f.csv", method="m")
    stata = _render(spec)["stata"]
    assert "bindquote(strict) maxquotedrows(unlimited)" in stata
    json_spec = Spec(kind="json", url="https://x.ca/q", file_name="q.json", method="m")
    assert "bindquote(strict) maxquotedrows(unlimited)" in _render(json_spec)["stata"]


# H7: CMHC CSV exports --------------------------------------------------------------------

_CMHC = (
    " Historical Vacancy Rates by Bedroom Type  \r\n"
    "1990 to 2025 Row / Apartment October\r\n"
    ",Studio,,1 Bedroom,,Total,,\r\n"
    "1990 October,5.0,a ,3.5,a ,3.4,a ,\r\n"
    "1991 October,6.3,a ,4.3,a ,4.3,a ,\r\n"
    "\r\n"
    "Notes\r\n"
    "Source,CMHC Rental Market Survey\r\n"
)


def test_layout_finds_the_header_below_title_lines():
    assert probe._layout(_CMHC) == (",", 2, True)
    assert probe._layout("a,b\n1,2\n") == (",", 0, False)
    assert probe._layout('a,b\n1,"x\n\ny"\n2,z\n') == (",", 0, False)


async def test_probe_reads_cmhc_exports_as_csv(httpx_mock):
    httpx_mock.add_response(
        url="https://x.ca/export", text=_CMHC, headers={"content-type": "text/csv"}
    )
    spec = await probe.spec_from_request(RecordedRequest("GET", "https://x.ca/export", b"", ""), 1)
    assert spec.kind == "csv" and spec.skip_rows == 2 and spec.stop_at_blank
    code = _render(spec)
    assert "splitlines()[2:]" in code["python"] and "if not line.strip()" in code["python"]
    assert 'read_lines("data/raw/export.csv", skip = 2)' in code["r"]
    assert "python:" in code["stata"]
    assert "readlines(" in code["julia"] and "List.FirstN(" in code["excel"]
    # The Python reader keeps the two data rows.
    start = code["python"].index("lines = raw_path")
    end = code["python"].index("data = pl.read_csv")

    class _Path:
        def read_text(self, **kwargs):
            return _CMHC

    namespace: dict[str, Any] = {"raw_path": _Path()}
    exec(code["python"][start:end], namespace)  # noqa: S102 - this repository's own generated code
    assert len(namespace["lines"]) == 3  # header and two rows


# Smaller fixes ----------------------------------------------------------------------------


def test_unsent_arguments_count_every_request_the_tool_made():
    lookup = RecordedRequest(
        "GET",
        "https://x.ca/match?CategoryLevel1=Primary+Rental+Market&RowField=TIMESERIES",
        b"",
        "",
    )
    data = RecordedRequest("POST", "https://x.ca/export", b"TableId=2.2.1", "")
    args = {"category_level_1": "Primary Rental Market", "row_field": "TIMESERIES", "q": "zzz"}
    assert probe.unsent_arguments(args, [data, lookup]) == ["q='zzz'"]


def test_arcgis_query_url_does_not_repeat_the_layer():
    assert layer_query_url("https://x.ca/MapServer/28", 28) == "https://x.ca/MapServer/28/query"
    assert layer_query_url("https://x.ca/FeatureServer", 0) == "https://x.ca/FeatureServer/0/query"


def test_julia_valet_step_makes_one_row_per_date_and_series():
    step = cleaning.specific("julia", "valet")
    assert step is not None and "stack(data" in step.body and "Dates" in step.imports


async def test_french_notes_and_errors(offline):
    result = await client.reproduce(
        "socrata_query_dataset_rows", {"portal": "calgary", "dataset_id": "848s-4m4z"}, lang="fr"
    )
    assert any("paginez" in note for note in result.notes)
    with pytest.raises(InvalidInput, match="ne récupère pas"):
        await client.reproduce("plan_query", {}, lang="fr")


@pytest.mark.parametrize(
    "english",
    [
        # One note from each builder that writes its own (CFIA, PHAC, IP Horizons).
        (
            "The tool returned 13 rows (2011-2026); the scripts parse all year tables on the page "
            "and repeat its year range, disease match (folded for case, accents and apostrophes, "
            "with the abbreviations and other names in constants.DISEASES), order and totals by "
            "disease."
        ),
        (
            "The tool returned 3 detections (3 herds) from 1 disease page(s); the scripts parse the "
            "same pages as the tool does (herd counts such as 'Elk (3 herds)', day and month read "
            "with the row's year, provinces named in the location, BSE's age) and repeat its "
            "filters, order."
        ),
        (
            "The tool matched 5 premises and returned 3; the scripts parse the "
            "investigations-and-orders table as the tool does (hidden padding digits, quarantine "
            "and released markers, premises type, WOAH class, control zone and order) and repeat "
            "its filters, newest-first order, counts by province and limit of 3, and read the "
            "status-by-province table."
        ),
        (
            "The tool returned 1 of 1 matching rows (2 in the file); the scripts repeat its "
            "filters, province match, date bounds, ordering and limit, so they keep the same rows."
        ),
        "Files listed (0): none.",
        (
            "`data` holds the patent; `parties` its owners, inventors, applicants and agents; "
            "`classes` its IPC classes."
        ),
    ],
)
def test_builder_notes_have_french(english):
    from maplestats_mcp.modules.reproduce import french, ip_horizons

    assert french.translate(english) is not None, english
    assert french.translate(ip_horizons._TLS_NOTE) is not None
    out = french.note(english, "fr")
    assert out != english and " ;" not in out  # no-break space before ;
    assert french.note(english, "en") == english
