"""reproduce_code for calls with `transform` or `frequency`.

The scripts must fetch the same levels as the tool, reaching back as far as
it did for the lag, and apply the same formula. The generated Python was
run live on 2026-10-27 for eight calls (WDS vectors, coordinate and range,
SDMX key and vector, Valet daily and monthly) and matched the tool's values;
here the offline checks: routing, the request, and the code each language gets.
"""

from __future__ import annotations

from typing import Any

import pytest

from maplestats_mcp.modules.reproduce import builders, client
from maplestats_mcp.modules.reproduce.render import RENDERERS, stata_statements
from maplestats_mcp.shared.errors import InvalidInput


def _computed(transform: str, applied: str | None = None, ppy: int | None = 12) -> dict[str, Any]:
    return {
        "requested_transform": transform,
        "transform": applied or transform,
        "source_periods_per_year": ppy,
        "formula": f"Computed by MapleStats: {transform} = 100 * (x_t / x_{{t-12}} - 1)",
        "points": [],
    }


WDS_RESULT = {
    "series": [
        {"vector_id": 41690973, "transformed": _computed("yoy_pct_change")},
        {"vector_id": 2062815, "transformed": _computed("yoy_pct_change", "yoy_diff")},
    ]
}
ARGS = {"vector_ids": [41690973, 2062815], "latest_n": 3, "transform": "yoy_pct_change"}


def test_routing_with_and_without_a_transform():
    assert builders.argument_only("wds_get_data_from_vectors", {"vector_ids": [1]})
    assert not builders.argument_only("wds_get_data_from_vectors", ARGS)
    plain = {"product_id": 18100004, "coordinate": "2.2"}
    assert builders.builder_for("wds_get_data_from_cube_coord", plain) is builders._table
    assert (
        builders.builder_for("wds_get_data_from_cube_coord", {**plain, "transform": "diff"})
        is builders._cube_coord
    )
    assert (
        builders.builder_for("wds_get_data_by_reference_period_range", {"vector_ids": [1]}) is None
    )
    with pytest.raises(InvalidInput):
        builders.transform_request({"transform": "growth"})


async def test_vector_script_fetches_the_lag_and_applies_the_formula():
    spec = await builders._vectors(ARGS, WDS_RESULT)
    # 3 months plus the 12 before them, as the tool asked WDS.
    assert spec.post_json == [
        {"vectorId": 41690973, "latestN": 15},
        {"vectorId": 2062815, "latestN": 15},
    ]
    assert "excel" not in spec.languages
    assert spec.native == {} and spec.source == ""
    assert any("Power Query" in note for note in spec.notes)
    code = {lang: RENDERERS[lang](spec, "wds_get_data_from_vectors") for lang in RENDERERS}
    assert all(out is not None for out in code.values())
    python = code["python"][0]
    assert "STEP_MONTHS = {'41690973': 1, '2062815': 1}" in python
    assert "RATE_SERIES = ['2062815']" in python
    assert "LATEST_N = 3" in python
    compile(python, "script.py", "exec")
    r = code["r"][0]
    assert 'rate_series <- c("2062815")' in r and "get_cansim" not in r
    julia = code["julia"][0]
    assert 'rate_series = Set{String}(["2062815"])' in julia
    # Stata runs the step in its Python block, one statement per line.
    block = stata_statements(spec.prepare["python"].body)
    compile(block, "stata_block.py", "exec")


async def test_reference_range_and_sdmx_requests_start_earlier():
    args = {
        "vector_ids": [41690973],
        "start_ref_period": "2026-07",
        "end_ref_period": "2026-09",
        "transform": "pct_change",
    }
    result = {"series": [{"vector_id": 41690973, "transformed": _computed("pct_change")}]}
    spec = await builders._reference_range(args, result)
    assert "startRefPeriod=2026-06-01" in spec.url and "endReferencePeriod=2026-09-30" in spec.url
    assert "WINDOW_START = date.fromisoformat('2026-07-01')" in spec.prepare["python"].body

    args = {
        "product_id": 18100004,
        "key": "2.2",
        "start_period": "2024-01",
        "end_period": "2025-12",
        "transform": "yoy_pct_change",
        "frequency": "annual",
    }
    result = {"series": [{"vector_id": 41690973, "transformed": _computed("yoy_pct_change")}]}
    spec = await builders._sdmx_data(args, result)
    # One year for the lag and one more so the first year is whole.
    assert spec.url.endswith("?startPeriod=2022-01&endPeriod=2025-12")
    assert "FREQUENCY_MONTHS = 12" in spec.prepare["python"].body


async def test_valet_script_uses_the_window_the_tool_returned():
    args = {"series_names": ["V41690973"], "recent": 3, "transform": "yoy_pct_change"}
    result = {
        "observations": [
            {"ref_date": d, "values": {}} for d in ("2026-07-01", "2026-08-01", "2026-09-01")
        ],
        "transformed": {"V41690973": _computed("yoy_pct_change")},
    }
    spec = await builders._boc(args, result)
    assert spec.url.endswith("/V41690973/json?start_date=2025-07-01&end_date=2026-09-01")
    assert any("recent window" in note for note in spec.notes)
    assert 'pl.col("d").str.to_date()' in spec.prepare["python"].body


async def test_reproduce_says_why_there_is_no_excel_query(monkeypatch):
    async def run_tool(tool, args, lang="en"):
        return WDS_RESULT, []

    monkeypatch.setattr(client, "_run_tool", run_tool)
    result = await client.reproduce("wds_get_data_from_vectors", ARGS)
    assert {s.language for s in result.scripts} == {"r", "python", "stata", "julia"}
    assert any("Power Query cannot apply the transform" in note for note in result.notes)
    french = await client.reproduce("wds_get_data_from_vectors", ARGS, lang="fr")
    assert any("Power Query ne peut pas appliquer" in note for note in french.notes)


def test_generated_python_matches_the_tool_offline():
    pl = pytest.importorskip("polars")
    from datetime import date

    from maplestats_mcp.shared.transform import transform_series

    plan = builders._Plan(
        builders.TransformRequest("yoy_pct_change"), "wds", {"1": 1}, [], "", latest_n=3
    )
    months = [(2025 + (m - 1) // 12, (m - 1) % 12 + 1) for m in range(1, 16)]
    levels = [100 + i * 0.7 for i in range(15)]
    data = pl.DataFrame(
        {
            "vectorId": [1] * 15,
            "refPer": [f"{y}-{m:02d}-01" for y, m in months],
            "value": levels,
        }
    )
    code = builders._python_transform(plan)
    namespace = {"data": data, "pl": pl}
    exec("\n".join(code.imports) + "\n" + code.body, namespace)  # noqa: S102
    expected = transform_series(
        [(date(y, m, 1), v) for (y, m), v in zip(months, levels, strict=True)],
        source_ppy=12,
        transform="yoy_pct_change",
        latest_n=3,
    )
    assert namespace["data"]["value"].to_list() == pytest.approx([p.value for p in expected.points])


def test_window_is_read_and_checked():
    request = builders.transform_request({"transform": "moving_average", "window": 3})
    assert request is not None and request.window == 3
    for bad in ({"transform": "moving_average"}, {"transform": "diff", "window": 3}):
        with pytest.raises(InvalidInput, match="window"):
            builders.transform_request(bad)
    with pytest.raises(InvalidInput, match="whole number"):
        builders.transform_request({"transform": "moving_average", "window": "3"})


async def test_moving_average_script_fetches_the_window_and_every_language_has_it():
    args = {
        "vector_ids": [2062815],
        "latest_n": 3,
        "transform": "moving_average",
        "window": 3,
        "frequency": "annual",
    }
    computed = {
        **_computed("moving_average"),
        "formula": "Computed by MapleStats: moving_average_3 = mean(x_{t-2}, x_{t-1}, x_t)",
    }
    spec = await builders._vectors(
        args, {"series": [{"vector_id": 2062815, "transformed": computed}]}
    )
    # 3 years plus the 2 before them, in months, and 11 for a year still running.
    assert spec.post_json == [{"vectorId": 2062815, "latestN": 5 * 12 + 11}]
    assert spec.title.endswith("(moving_average 3, annual average)")
    code = {lang: RENDERERS[lang](spec, "wds_get_data_from_vectors") for lang in RENDERERS}
    python = code["python"][0]
    assert "WINDOW = 3" in python and "moving_average_3 = mean(x_{t-2}, x_{t-1}, x_t)" in python
    compile(python, "script.py", "exec")
    assert "ma_window <- 3L" in code["r"][0] and "moving_average = rowMeans(" in code["r"][0]
    assert "ma_window = 3" in code["julia"][0]
    compile(stata_statements(spec.prepare["python"].body), "stata_block.py", "exec")


@pytest.mark.parametrize("frequency", [None, "annual"])
def test_generated_python_moving_average_matches_the_tool_offline(frequency):
    pl = pytest.importorskip("polars")
    from datetime import date

    from maplestats_mcp.shared.transform import transform_series

    request = builders.TransformRequest("moving_average", frequency, window=3)
    plan = builders._Plan(request, "wds", {"1": 1}, [], "", latest_n=4)
    months = [(2019 + (m - 1) // 12, (m - 1) % 12 + 1) for m in range(1, 85)]
    levels: list[float | None] = [5 + (i % 7) * 0.3 for i in range(84)]
    levels[79] = None  # 2025-08 has no value
    del months[70], levels[70]  # and 2024-11 no row
    data = pl.DataFrame(
        {
            "vectorId": [1] * len(months),
            "refPer": [f"{y}-{m:02d}-01" for y, m in months],
            "value": levels,
        }
    )
    code = builders._python_transform(plan)
    namespace = {"data": data, "pl": pl}
    exec("\n".join(code.imports) + "\n" + code.body, namespace)  # noqa: S102
    expected = transform_series(
        [(date(y, m, 1), v) for (y, m), v in zip(months, levels, strict=True)],
        source_ppy=12,
        transform="moving_average",
        frequency=frequency,
        window=3,
        latest_n=4,
    )
    got = namespace["data"]["value"].to_list()
    assert len(got) == 4
    want = [p.value for p in expected.points]
    assert [v is None for v in got] == [v is None for v in want]
    assert any(v is not None for v in want) and any(v is None for v in want)
    assert [v for v in got if v is not None] == pytest.approx([v for v in want if v is not None])
