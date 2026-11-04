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


# wds_get_data_from_vectors([41690973], latest_n=3, transform="yoy_pct_change"),
# trimmed: the CPI, all-items, Canada (shape of TransformedSeries in
# src/maplestats_mcp/shared/transform.py; the server fetches 15 months so the
# year-earlier level is there, and returns the 3 asked for).
WDS_YOY = {
    "series": [
        {
            "product_id": 18100004,
            "coordinate": "2.2.0.0.0.0.0.0.0.0",
            "vector_id": 41690973,
            "context": {
                "table_id": "18-10-0004-01",
                "table_title": "Consumer Price Index, monthly, not seasonally adjusted",
                "table_url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401",
                "series_title": "Canada;All-items",
                "unit": "2002=100",
                "scale": "units",
                "frequency": "Monthly",
                "geography": "Canada",
                "notes": ["Not seasonally adjusted."],
            },
            "observations": [
                {"ref_period": "2026-07-01", "value": 169.9, "status": "normal"},
                {"ref_period": "2026-08-01", "value": 169.8, "status": "normal"},
                {
                    "ref_period": "2026-09-01",
                    "value": 170.0,
                    "status": "normal",
                    "release_time": "2026-10-19T12:30:00Z",
                },
            ],
            "transformed": {
                "requested_transform": "yoy_pct_change",
                "transform": "yoy_pct_change",
                "frequency": "monthly",
                "periods_per_year": 12,
                "source_periods_per_year": 12,
                "aggregation": None,
                "window": None,
                "formula": (
                    "Computed by MapleStats: yoy_pct_change = 100 * (x_t / x_{t-12} - 1), "
                    "t in months (the same period a year earlier, matched by date)"
                ),
                "unit": "percent",
                "notes": [],
                "points": [
                    {
                        "period": "2026-07",
                        "ref_date": "2026-07-01",
                        "level": 169.9,
                        "value": 3.0321406913,
                    },
                    {
                        "period": "2026-08",
                        "ref_date": "2026-08-01",
                        "level": 169.8,
                        "value": 2.7848664649,
                    },
                    {
                        "period": "2026-09",
                        "ref_date": "2026-09-01",
                        "level": 170.0,
                        "value": 3.0927835052,
                    },
                ],
            },
        }
    ],
    "failed": [],
    "provenance": {
        "source": "statcan-wds",
        "url": "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
        "coverage": "Computed by MapleStats from the published values (see each "
        "series' transformed.formula); 15 periods was fetched so the lag reaches "
        "back far enough, and the 3 requested are returned.",
    },
}


def test_percent_change_is_charted_in_its_own_unit_before_the_levels():
    yoy, levels = results.collect([("wds_get_data_from_vectors", WDS_YOY)])["data"]
    assert yoy["title"] == "Canada · All-items (% change from a year earlier)"
    assert yoy["unit"] == "percent" and yoy["scale"] is None
    assert yoy["vector_id"] == "v41690973"
    assert yoy["table_id"] == "18-10-0004-01"
    assert [(p["period"], round(p["value"], 1)) for p in yoy["points"]] == [
        ("2026-07-01", 3.0),
        ("2026-08-01", 2.8),
        ("2026-09-01", 3.1),
    ]
    assert yoy["notes"][0].startswith("Computed by MapleStats: yoy_pct_change")
    assert "Not seasonally adjusted." in yoy["notes"]
    # The published index stays, as a second series in its own unit.
    assert levels["unit"] == "2002=100"
    assert [p["value"] for p in levels["points"]] == [169.9, 169.8, 170.0]
    assert "companion" not in levels and "transform" not in levels


def test_percent_change_of_a_rate_from_sdmx_is_in_points():
    sdmx = {
        "dataflow_id": "DF_14100287",
        "series": [
            {
                "series_key": {"Geography": "1"},
                "vector_id": 2062815,
                "context": {
                    "unit": "Percentage",
                    "series_title": "Canada;Unemployment rate",
                },
                "observations": [
                    {"period": "2026-08", "value": 6.4},
                    {"period": "2026-09", "value": 6.5},
                ],
                "transformed": {
                    "requested_transform": "pct_change",
                    "transform": "diff",
                    "frequency": "monthly",
                    "formula": "Computed by MapleStats: diff = x_t - x_{t-1}, t in months",
                    "unit": "percentage points",
                    "notes": ["The series is a percentage or rate: change in points."],
                    "points": [
                        {
                            "period": "2026-08",
                            "ref_date": "2026-08-01",
                            "level": 6.4,
                            "value": -0.1,
                        },
                        {
                            "period": "2026-09",
                            "ref_date": "2026-09-01",
                            "level": 6.5,
                            "value": 0.1,
                        },
                    ],
                },
            }
        ],
        "provenance": {"source": "statcan-sdmx", "url": "https://x/sdmx"},
    }
    diff, level = results.collect([("sdmx_get_data", sdmx)])["data"]
    assert diff["unit"] == "percentage points"
    assert diff["title"].endswith("(change from previous period)")
    assert diff["notes"][:2] == [
        "Computed by MapleStats: diff = x_t - x_{t-1}, t in months",
        "The series is a percentage or rate: change in points.",
    ]
    assert [p["value"] for p in diff["points"]] == [-0.1, 0.1]
    assert level["unit"] == "Percentage"


def _yoy_series(vector):
    item = json.loads(json.dumps(WDS_YOY["series"][0]))
    item["vector_id"] = vector
    return item


def test_levels_give_way_to_computed_series_under_max_series():
    some = {**WDS_YOY, "series": [_yoy_series(v) for v in range(1, 6)]}
    data = results.collect([("wds_get_data_from_vectors", some)])["data"]
    assert len(data) == results.MAX_SERIES
    computed = [s for s in data if s["unit"] == "percent"]
    assert len(computed) == 5  # every computed series, and levels while room is left
    many = {**WDS_YOY, "series": [_yoy_series(v) for v in range(1, 9)]}
    data = results.collect([("wds_get_data_from_vectors", many)])["data"]
    assert len(data) == results.MAX_SERIES
    assert all(s["unit"] == "percent" for s in data)


def test_a_transform_without_values_keeps_the_levels_only():
    item = _yoy_series(41690973)
    for point in item["transformed"]["points"]:
        point["value"] = None
    (series,) = results.collect([("w", {**WDS_YOY, "series": [item]})])["data"]
    assert series["unit"] == "2002=100"


def test_bank_of_canada_transformed_series_are_charted():
    valet = {
        "series": {"V41690973": {"label": "CPI", "unit": "Index"}},
        "observations": [{"ref_date": "2026-09-01", "values": {"V41690973": 170.0}}],
        "transformed": {
            "V41690973": {
                "transform": "yoy_pct_change",
                "formula": "Computed by MapleStats: yoy_pct_change = ...",
                "unit": "percent",
                "points": [
                    {"period": "2026-09", "ref_date": "2026-09-01", "value": 3.09}
                ],
            }
        },
        "provenance": {"source": "boc", "url": "https://www.bankofcanada.ca/valet/x"},
    }
    yoy, level = results.collect([("boc_get_observations", valet)])["data"]
    assert yoy["unit"] == "percent" and yoy["points"][0]["value"] == 3.09
    assert level["unit"] == "Index"
