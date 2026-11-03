# ============================================================
# Tests for the data and sources drawn under an answer
# Author: Daniel Sanchez
# Purpose: Check that series, table rows and sources come from tool results
# Inputs:  trimmed copies of real MapleStats tool results
# Outputs: pass/fail
# ============================================================

import json
from types import SimpleNamespace

import app as chat_app
import results

# wds_get_data_from_vectors for v3823103, trimmed (shape as served 2026-11-02).
WDS = {
    "series": [
        {
            "product_id": 34100133,
            "coordinate": "125.3.3.0.0.0.0.0.0.0",
            "vector_id": 3823103,
            "context": {
                "table_id": "34-10-0133-01",
                "table_title": "CMHC, average rents for areas with a population of 10,000 and over",
                "table_url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410013301",
                "series_title": "Toronto, Ontario;Row and apartment structures of three units and over;Two bedroom units",
                "unit": "Dollars",
                "scale": "units",
                "frequency": "Annual",
                "geography": "Toronto, Ontario",
                "table_release_time": "2025-12-17T08:30",
                "notes": [
                    "Unit is current (nominal) dollars, not adjusted for inflation."
                ],
            },
            "observations": [
                {
                    "ref_period": "2025-01-01",
                    "value": 2045.0,
                    "status": "normal",
                    "release_time": "2025-12-17T13:30:00Z",
                    "scale_multiplier": 1,
                },
                {
                    "ref_period": "2024-01-01",
                    "value": 1972.0,
                    "status": "normal",
                    "release_time": "2025-02-04T13:30:00Z",
                    "scale_multiplier": 1,
                },
            ],
        }
    ],
    "failed": [],
    "provenance": {
        "source": "statcan-wds",
        "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
        "caveats": ["These tables republish CMHC's Rental Market Survey..."],
        "licence": "Source: Statistics Canada.",
    },
}

SDMX = {
    "dataflow_id": "DF_11100190",
    "series": [
        {
            "series_key": {"Geography": "17"},
            "vector_id": 96415851,
            "uom_code": "455",
            "context": {"unit": "2024 constant dollars", "table_id": "11-10-0190-01"},
            "observations": [
                {
                    "period": "2024",
                    "value": 82500.0,
                    "status": "data quality: excellent",
                }
            ],
        }
    ],
    "provenance": {
        "source": "statcan-sdmx",
        "url": "https://www150.statcan.gc.ca/t1/wds/sdmx/x",
    },
}


def test_wds_series_come_with_their_citation():
    out = results.collect([("wds_get_data_from_vectors", json.dumps(WDS))])
    (series,) = out["data"]
    assert series["vector_id"] == "v3823103"
    assert series["title"].startswith("Toronto, Ontario · Row and apartment")
    assert series["unit"] == "Dollars" and series["scale"] is None
    assert series["release"] == "2025-12-17"
    assert [p["period"] for p in series["points"]] == ["2024-01-01", "2025-01-01"]
    assert (
        series["points"][1]["value"] == 2045.0 and series["points"][1]["status"] is None
    )
    assert series["caveats"] and series["notes"]
    assert out["sources"][0]["source"] == "statcan-wds"


def test_sdmx_series_and_quality_flags():
    (series,) = results.collect([("sdmx_get_vector_data", SDMX)])["data"]
    assert series["unit"] == "2024 constant dollars"
    assert series["points"] == [
        {"period": "2024", "value": 82500.0, "status": "data quality: excellent"}
    ]


def test_discovery_and_bad_results_add_nothing():
    out = results.collect(
        [
            ("search_tools", '[{"name": "x"}]'),
            ("plan_query", '{"topics": []}'),
            ("wds_get_data_from_vectors", "not json"),
        ]
    )
    assert out == {"data": [], "sources": []}


def test_a_refetched_series_is_kept_once():
    out = results.collect([("a", WDS), ("b", WDS)])
    assert len(out["data"]) == 1 and len(out["sources"]) == 2


def test_a_non_statcan_result_still_lists_its_source():
    boc = {
        "observations": [],
        "provenance": {
            "source": "boc-valet",
            "url": "https://www.bankofcanada.ca/valet/x",
        },
    }
    out = results.collect([("boc_get_observations", boc)])
    assert out["data"] == [] and out["sources"][0]["source"] == "boc-valet"


def test_anthropic_backend_returns_the_data_it_saw(monkeypatch):
    import asyncio

    from tests.test_app import _fake_anthropic

    use = SimpleNamespace(
        type="mcp_tool_use",
        id="t1",
        name="call_tool",
        input={"name": "wds_get_data_from_vectors", "arguments": {}},
    )
    result = SimpleNamespace(
        type="mcp_tool_result",
        tool_use_id="t1",
        is_error=False,
        content=[SimpleNamespace(type="text", text=json.dumps(WDS))],
    )
    answer = SimpleNamespace(type="text", text="Rent was $2,045.")
    _fake_anthropic(
        monkeypatch,
        [SimpleNamespace(content=[use, result, answer], stop_reason="end_turn")],
    )
    out = asyncio.run(chat_app.ask_anthropic([{"role": "user", "content": "rent?"}]))
    assert out["answer"] == "Rent was $2,045."
    assert out["data"][0]["vector_id"] == "v3823103"
    assert out["sources"][0]["tool"] == "wds_get_data_from_vectors"


def test_bank_of_canada_series_are_charted():
    valet = {
        "series": {
            "V39079": {"label": "Target for the overnight rate", "unit": "Percent"}
        },
        "observations": [
            {"ref_date": "2026-10-30", "values": {"V39079": 2.5}},
            {"ref_date": "2026-10-28", "values": {"V39079": 2.25}},
        ],
        "provenance": {"source": "boc", "url": "https://www.bankofcanada.ca/valet/x"},
    }
    (series,) = results.collect([("boc_get_observations", valet)])["data"]
    assert series["unit"] == "Percent" and series["vector_id"] == "V39079"
    assert [p["value"] for p in series["points"]] == [2.25, 2.5]


# cmhc_get_table_data for Toronto's average rents, trimmed (shape as served 2026-11-03).
CMHC = {
    "table_id": "2.2.11",
    "table_name": "Historical Average Rents by Bedroom Type",
    "geography_name": "Toronto",
    "category_level_1": "Primary Rental Market",
    "category_level_2": "Average Rent ($)",
    "column_field": "2",
    "row_field": "TIMESERIES",
    "columns": ["2 Bedroom", "Total"],
    "rows": [
        {
            "period": "2025 October",
            "values": {
                "2 Bedroom": {"value": 2045.0, "flag": "a"},
                "Total": {"value": 1849.0, "flag": "a"},
            },
        },
        {
            "period": "2019 October",
            "values": {
                "2 Bedroom": {"value": 1563.0, "flag": "a"},
                "Total": {"value": None, "flag": "**"},
            },
        },
    ],
    "notes": ["Source: CMHC Rental Market Survey"],
    "provenance": {
        "source": "cmhc",
        "url": "https://www03.cmhc-schl.gc.ca/hmip-pimh/en/TableMapChart/ExportTable",
    },
}


def test_cmhc_time_series_become_one_series_per_column():
    out = results.collect([("cmhc_get_table_data", CMHC)])
    two_bed, total = out["data"]
    assert two_bed["title"] == "Toronto · Average Rent ($) · 2 Bedroom"
    assert [(p["period"], p["value"]) for p in two_bed["points"]] == [
        ("2019-10-01", 1563.0),
        ("2025-10-01", 2045.0),
    ]
    assert total["points"][0] == {"period": "2019-10-01", "value": None, "status": "**"}
    assert out["sources"][0]["source"] == "cmhc"


def test_cmhc_cross_tabs_and_french_months():
    cross = {
        **CMHC,
        "row_field": "21",
        "rows": [{**CMHC["rows"][0], "period": "Ontario"}],
    }
    assert results.collect([("cmhc_get_table_data", cross)])["data"] == []
    french = {**CMHC, "rows": [{**CMHC["rows"][0], "period": "2025 octobre"}]}
    points = results.collect([("cmhc_get_table_data", french)])["data"][0]["points"]
    assert points[0]["period"] == "2025-10-01"
