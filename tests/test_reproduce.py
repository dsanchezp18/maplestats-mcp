"""reproduce_code: builders, renderers, the request probe and the recorder.

No network: argument-only builders need none, and the probe runs against
pytest-httpx. Generated scripts were also run for real on 2026-09-25 (R
4.5, Python with polars, Stata 18) against the sources named in
scripts/smoke_test_modules.py's reproduce steps.
"""

from __future__ import annotations

import json
import re

import pytest

from maplestats_mcp.modules.reproduce import client, probe
from maplestats_mcp.modules.reproduce.render import RENDERERS
from maplestats_mcp.modules.reproduce.spec import Filter, Spec
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.http import RecordedRequest, api_get, recording


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _by_language(result) -> dict[str, str]:
    return {s.language: s.code for s in result.scripts}


# Builders ------------------------------------------------------------------------


async def test_table_all_languages_with_house_layout():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 1810000401})
    code = _by_language(result)
    assert set(code) == {"r", "python", "stata", "julia"}
    assert result.source_url == "https://www150.statcan.gc.ca/n1/tbl/csv/18100004-eng.zip"
    assert 'get_cansim("18-10-0004-01")' in code["r"] and "val_norm" in code["r"]
    assert "http2=True" in code["python"]  # StatCan rejects HTTP/1.1-only clients
    assert 'pl.col("SCALAR_ID")' in code["python"]
    assert "value * 10^scalar_id" in code["stata"] and " cd " not in code["stata"]
    assert "@clean_names" in code["julia"]
    # House layout: header block, then numbered sections in order.
    for language, text in code.items():
        assert text.lstrip().startswith(("# ====", "* ====")), language
        marks = ["0. Setup", "1. Read inputs", "2. Check inputs", "3. Prepare data"]
        positions = [text.index(mark) for mark in marks]
        assert positions == sorted(positions), language
    assert "version 18" in code["stata"] and "log using" in code["stata"]


async def test_every_package_loads_in_setup():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004})
    code = _by_language(result)
    read_at = code["r"].index("# 1. Read inputs")
    assert all(m.start() < read_at for m in re.finditer(r"library\(", code["r"]))
    read_at = code["python"].index("# %% 1. Read inputs")
    assert all(
        m.start() < read_at for m in re.finditer(r"^(import|from) ", code["python"], re.MULTILINE)
    )
    read_at = code["julia"].index("# 1. Read inputs")
    assert all(m.start() < read_at for m in re.finditer(r"^using ", code["julia"], re.MULTILINE))


async def test_one_language_on_request():
    result = await client.reproduce(
        "boc_get_observations", {"series_names": ["FXUSDCAD"], "recent": 5}, "python"
    )
    assert [s.language for s in result.scripts] == ["python"]
    assert 'data.unpivot(index="d"' in result.scripts[0].code


async def test_french_table_uses_semicolons_and_french_columns():
    result = await client.reproduce("wds_get_cube_metadata", {"product_id": 18100004, "lang": "fr"})
    code = _by_language(result)
    assert result.source_url.endswith("18100004-fra.zip")
    assert "separator=';'" in code["python"] and 'pl.col("VALEUR")' in code["python"]
    # Stata's copy offers only HTTP/1.1, which StatCan drops, so it goes via Python.
    assert "separator=';'" in code["stata"] and "python:" in code["stata"]
    assert 'delim = ";"' in code["julia"]
    assert 'language = "fr"' in code["r"]


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
    assert "item['object']['vectorDataPoint']" in code and "client.post(" in code
    assert "scalarFactorCode" in code


async def test_ivt_only_table_gets_r_only():
    result = await client.reproduce(
        "statcan_census_tables_get_downloads", {"pid": "93658", "release": "2006"}
    )
    assert [s.language for s in result.scripts] == ["r"]
    assert "read_ivt" in result.scripts[0].code and "library(canivt)" in result.scripts[0].code
    assert any("canivt" in note for note in result.notes)


async def test_canadabuys_script_repeats_the_tools_filters():
    result = await client.reproduce(
        "canadabuys_search_awards",
        {"query": "snow removal", "buyer": "Public Works", "fiscal_year": "2024-2025"},
    )
    code = _by_language(result)
    assert result.source_url.endswith("/2024-2025-awardNotice-avisAttribution.csv")
    # Every query word must match somewhere, as in the tool.
    assert code["python"].count(".str.contains('snow'") == 1
    assert ".str.contains('removal'" in code["python"]
    assert "`contractingEntityName-nomEntitContractante-eng`" in code["r"]
    assert 'occursin("public works"' in code["julia"]
    # Stata filters inside its Python block, before long names are truncated.
    assert "python:" in code["stata"] and "data.filter(" in code["stata"]


async def test_bad_requests():
    with pytest.raises(InvalidInput):
        await client.reproduce("plan_query", {})
    with pytest.raises(InvalidInput):
        await client.reproduce("wds_get_cube_metadata", {"product_id": 12})
    with pytest.raises(InvalidInput):
        await client.reproduce("boc_get_observations", {})


# Renderers ---------------------------------------------------------------------------


def _render(spec: Spec) -> dict[str, str]:
    rendered = {lang: RENDERERS[lang](spec, "example_tool") for lang in RENDERERS}
    return {lang: out[0] for lang, out in rendered.items() if out is not None}


def test_filters_run_on_source_names_in_every_language():
    spec = Spec(
        kind="csv",
        url="https://x.ca/f.csv",
        file_name="f.csv",
        method="exact",
        filters=[
            Filter("is", ["Company Name"], " TC Energy "),
            Filter("starts", ["Fiscal Year"], "2023"),
            Filter("ge", ["Date"], "2024-01-01"),
            Filter("ge", ["Value"], 1000),
        ],
    )
    code = _render(spec)
    assert 'str_to_lower(str_trim(`Company Name`)) == "tc energy"' in code["r"]
    assert 'str_starts(as.character(`Fiscal Year`), fixed("2023"))' in code["r"]
    assert "pl.col('Value').cast(pl.Float64, strict=False) >= 1000" in code["python"]
    assert "str.strip_chars().str.to_lowercase() == 'tc energy'" in code["python"]
    assert 'startswith(coalesce(string(row["Fiscal Year"]), ""), "2023")' in code["julia"]
    # Filters come before name cleaning, so they use the source's names.
    assert code["r"].index("filter(") < code["r"].index("clean_names()")


def test_json_record_field_and_post_form():
    spec = Spec(
        kind="json",
        url="https://x.ca/query",
        file_name="q.json",
        method="exact",
        records_path=["features"],
        record_field="attributes",
        post_form={"where": "1=1", "f": "json"},
        headers={"Accept": "application/json"},
    )
    code = _render(spec)
    assert 'payload[["features"]][["attributes"]]' in code["r"]
    assert 'req_body_form(!!!list(`where` = "1=1", `f` = "json"))' in code["r"]
    assert "[row['attributes'] for row in payload['features']]" in code["python"]
    assert "data={'where': '1=1', 'f': 'json'}" in code["python"]
    assert '"Content-Type" => "application/x-www-form-urlencoded"' in code["julia"]


def test_html_tables_skip_julia_and_xlsx_reads_its_sheet():
    html = _render(Spec(kind="html_table", url="https://x.ca/p", file_name="p.html", method="m"))
    assert "julia" not in html and "html_table()" in html["r"]
    assert "pd.read_html" in html["python"]
    xlsx = _render(
        Spec(
            kind="xlsx",
            url="https://x.ca/d.xlsx",
            file_name="d.xlsx",
            method="m",
            sheet="Table 1",
            skip_rows=1,
        )
    )
    assert 'read_xlsx("data/raw/d.xlsx", sheet = "Table 1", start_row = 2)' in xlsx["r"]
    assert 'sheet("Table 1") cellrange(A2) firstrow' in xlsx["stata"]


def test_file_kind_downloads_without_a_table():
    code = _render(Spec(kind="file", url="https://x.ca/a.txt", file_name="a.txt", method="m"))
    assert "2. Check inputs" not in code["r"] and "download.file" in code["r"]
    assert 'copy "https://x.ca/a.txt"' in code["stata"]


def test_stata_python_blocks_are_one_line_statements():
    from maplestats_mcp.modules.reproduce.render import stata_statements

    code = (
        "import httpx  # client\n"
        "with httpx.Client(\n"
        "    timeout=300,\n"
        ") as client:\n"
        "    response = client.get(  # fetch\n"
        '        "https://x.ca"\n'
        "    )\n"
        "    data = response.json()\n"
        "rows = []\n"
        "for item in data:\n"
        "    if item:\n"
        "        rows.append(item)\n"
    )
    out = stata_statements(code).splitlines()
    assert out[0] == "import httpx"
    assert out[1] == (
        'with httpx.Client(timeout=300) as client: response = client.get("https://x.ca"); '
        "data = response.json()"
    )
    assert out[2] == "rows = []"
    assert out[3].startswith("exec(") and "for item in data:" in eval(out[3][5:-1])


# Probe ---------------------------------------------------------------------------------


def test_find_records_locates_rows():
    assert probe.find_records([{"a": 1}]) == {}
    assert probe.find_records({"features": [{"attributes": {"a": 1}}]}) == {
        "records_path": ["features"],
        "record_field": "attributes",
    }
    geojson = {"type": "FeatureCollection", "features": [{"properties": {"a": 1}}]}
    assert probe.find_records(geojson)["record_field"] == "properties"
    assert probe.find_records({"result": {"results": [{"a": 1}, {"a": 2}]}, "help": "x"}) == {
        "records_path": ["result", "results"]
    }
    assert probe.find_records({"id": 1, "name": "x"}) == {"single_object": True}
    # SDG data files: one list per column.
    assert probe.find_records({"Year": [2015, 2016], "Value": [1.0, 2.0]}) == {"columnar": True}
    recalls = {"ResultSet": [[{"Name": "Recall number", "Value": {"Literal": "2023191"}}]]}
    assert probe.find_records(recalls) == {"records_path": ["ResultSet"], "name_value": True}
    wds = [{"status": "SUCCESS", "object": {"vectorDataPoint": [{"value": 1}]}}]
    assert probe.find_records(wds) == {
        "records_path": ["object", "vectorDataPoint"],
        "each_item": True,
    }
    assert probe.find_records([{"status": "SUCCESS", "object": {"vectorId": 1}}]) == {
        "record_field": "object"
    }


def test_choose_takes_the_last_endpoint_and_its_first_page():
    requests = [
        RecordedRequest("GET", "https://x.ca/meta", b"", "", status=200),
        RecordedRequest("GET", "https://x.ca/data?offset=0", b"", "", status=200),
        RecordedRequest("GET", "https://x.ca/data?offset=500", b"", "", status=200),
        RecordedRequest("GET", "https://x.ca/broken", b"", "", status=500),
    ]
    chosen, pages = probe.choose(requests)
    assert chosen is not None and chosen.url.endswith("offset=0") and pages == 2
    # The endpoint the result names as its source wins over later lookups.
    search = [
        RecordedRequest("GET", "https://x.ca/package_search?q=a", b"", "", status=200),
        RecordedRequest("GET", "https://x.ca/package_show?id=1", b"", "", status=200),
        RecordedRequest("HEAD", "https://x.ca/file.csv", b"", "", status=200),
    ]
    chosen, _ = probe.choose(search, "https://x.ca/package_search")
    assert chosen is not None and chosen.url.endswith("q=a")
    # A named web page the tool mined for an API call loses to that call.
    mined = [
        RecordedRequest(
            "GET", "https://api.x.ca/tile", b"", "", status=200, response_type="text/plain"
        ),
        RecordedRequest(
            "GET", "https://x.ca/dashboard/", b"", "", status=200, response_type="text/html"
        ),
    ]
    chosen, _ = probe.choose(mined, "https://x.ca/dashboard/")
    assert chosen is not None and chosen.url == "https://api.x.ca/tile"


def test_unsent_arguments_are_the_ones_applied_locally():
    request = RecordedRequest("GET", "https://x.ca/items?station=3031093&f=json", b"", "")
    unsent = probe.unsent_arguments(
        {"station": "3031093", "query": "rain", "limit": 5, "lang": "en"}, request
    )
    assert unsent == ["query='rain'"]


async def test_probe_classifies_responses(httpx_mock):
    httpx_mock.add_response(url="https://x.ca/rows", json={"data": [{"a": 1}, {"a": 2}]})
    spec = await probe.spec_from_request(RecordedRequest("GET", "https://x.ca/rows", b"", ""), 1)
    assert spec.kind == "json" and spec.records_path == ["data"]

    httpx_mock.add_response(
        url="https://x.ca/quakes",
        text="#EventID|Time\n1|2026\n",
        headers={"content-type": "text/plain"},
    )
    spec = await probe.spec_from_request(RecordedRequest("GET", "https://x.ca/quakes", b"", ""), 1)
    assert spec.kind == "csv" and spec.delimiter == "|" and spec.header_prefix == "#"

    httpx_mock.add_response(
        url="https://x.ca/page",
        text="<html><table><tr><td>1</td></tr></table><table><tr></tr><tr></tr></table></html>",
        headers={"content-type": "text/html"},
    )
    spec = await probe.spec_from_request(RecordedRequest("GET", "https://x.ca/page", b"", ""), 1)
    assert spec.kind == "html_table" and spec.html_table_index == 1

    httpx_mock.add_response(
        url="https://x.ca/feed",
        text='<?xml version="1.0"?><rss><channel><item><title>a</title></item></channel></rss>',
        headers={"content-type": "application/xml"},
    )
    spec = await probe.spec_from_request(RecordedRequest("GET", "https://x.ca/feed", b"", ""), 1)
    assert spec.kind == "feed"


async def test_probe_refuses_browser_session_forms():
    request = RecordedRequest(
        "POST",
        "https://x.ca/form",
        b"__VIEWSTATE=abc&q=1",
        "application/x-www-form-urlencoded",
        status=200,
    )
    spec = await probe.spec_from_request(request, 1)
    assert spec.kind == "none" and "browser session" in spec.notes[0]


async def test_probe_replays_post_json(httpx_mock):
    httpx_mock.add_response(url="https://x.ca/srch", method="POST", json={"docs": [{"id": 1}]})
    request = RecordedRequest(
        "POST", "https://x.ca/srch", json.dumps({"q": "maple"}).encode(), "application/json"
    )
    spec = await probe.spec_from_request(request, 1)
    assert spec.post_json == {"q": "maple"} and spec.records_path == ["docs"]
    assert json.loads(httpx_mock.get_requests()[0].content) == {"q": "maple"}


# Recorder -------------------------------------------------------------------------------


async def test_recording_captures_requests_and_bypasses_the_cache(httpx_mock):
    httpx_mock.add_response(url="https://x.ca/api?a=1", json={"ok": True}, is_reusable=True)

    async def fetch():
        return await api_get("https://x.ca/api", params={"a": 1})

    await cached_fetch("k", 60, fetch)  # warm the cache
    with recording() as requests:
        await cached_fetch("k", 60, fetch)
    assert [r.url for r in requests] == ["https://x.ca/api?a=1"]
    assert requests[0].status == 200 and "json" in requests[0].response_type
    with recording() as none_outside:
        pass
    assert none_outside == []
